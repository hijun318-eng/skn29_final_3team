"""Trino SQL을 한 번 parsing한 SQLGlot AST에서 read-only 정책과 lineage를 함께 판정한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import sqlglot
from sqlglot import ErrorLevel, exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import Scope, traverse_scope


TRINO_DIALECT = "trino"
DEFAULT_MAX_LIMIT = 1_000


@dataclass(frozen=True)
class SqlViolation:
    """한 AST 정책 위반의 안정된 code와 진단 message, 선택적 node path를 보존한다."""
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class ColumnReference:
    """AST의 컬럼 사용 한 건과 qualifier로 해석한 physical source를 보존한다.

    source scope를 하나로 결정할 수 없으면 ``source_table``은 ``None``이며, ``sql``에는
    원래 quoted identity를 지운 별칭이 아니라 Trino dialect의 컬럼 표현을 남긴다.
    """
    name: str
    qualifier: str | None
    source_table: str | None
    sql: str


@dataclass(frozen=True)
class JoinReference:
    """한 join node의 source·alias·종류와 AST에서 분해한 AND 조건을 순서대로 보존한다."""
    source: str
    alias: str | None
    kind: str
    on_conjuncts: tuple[str, ...]


@dataclass(frozen=True)
class SqlValidationResult:
    """한 parsing 결과의 query AST·표준 SQL·lineage·clause와 모든 정책 위반을 반환한다.

    root가 query가 아니거나 parsing이 실패하면 ``expression``과 ``canonical_sql``은 비어
    있고 violations만 남는다. 호출자는 ``ok`` 또는 ``raise_for_violations``로 실행 가능 여부를 결정한다.
    """
    expression: exp.Query | None
    canonical_sql: str | None
    physical_tables: tuple[str, ...]
    columns: tuple[ColumnReference, ...]
    projection_aliases: tuple[str, ...]
    functions: tuple[str, ...]
    joins: tuple[JoinReference, ...]
    placeholders: tuple[str, ...]
    where_expressions: tuple[str, ...]
    group_expressions: tuple[str, ...]
    order_expressions: tuple[str, ...]
    limit: int | None
    violations: tuple[SqlViolation, ...]

    @property
    def ok(self) -> bool:
        """SqlValidationResult에 누적된 정책 위반이 없는지 계산한다."""
        return not self.violations

    def raise_for_violations(self) -> None:
        """수집된 SQL 정책 위반이 있으면 전체 진단을 담은 구조화된 예외를 발생시킨다."""
        if self.violations:
            raise SqlPolicyError(self.violations)


class SqlPolicyError(ValueError):
    """SQLGlot AST가 read-only statement·identifier·literal·parameter 안전 정책을 위반했음을 알린다."""
    def __init__(self, violations: Iterable[SqlViolation]) -> None:
        self.violations = tuple(violations)
        summary = "; ".join(
            f"{item.code}: {item.message}" for item in self.violations
        )
        super().__init__(summary or "SQL policy validation failed")


def validate_sql(
    sql: str,
    *,
    require_limit: bool = True,
    max_limit: int = DEFAULT_MAX_LIMIT,
) -> SqlValidationResult:
    """Trino SQL을 한 번 parsing해 단일 read-only query 정책과 AST lineage를 반환한다.

    parse·statement·comment·star·limit·placeholder 위반을 가능한 범위까지 누적하고, 실행
    계층이 동일 AST를 재사용할 수 있도록 query expression과 canonical SQL도 함께 보존한다.
    """
    if max_limit <= 0:
        raise ValueError("max_limit must be positive")

    violations: list[SqlViolation] = []
    try:
        # 문자열·정규식 검사는 주석, quoted identifier, 중첩 CTE에서 우회될 수 있다.
        # 동일 dialect의 AST를 한 번만 만들고 이후 안전성·lineage 판정을 모두 이 트리에서 수행한다.
        parsed = sqlglot.parse(sql, read=TRINO_DIALECT, error_level=ErrorLevel.RAISE)
    except (ParseError, ValueError) as error:
        violations.append(SqlViolation("SQL_PARSE_ERROR", str(error)))
        return _empty_result(violations)

    statements = [statement for statement in parsed if statement is not None]
    if len(statements) != 1:
        violations.append(
            SqlViolation(
                "SINGLE_STATEMENT_REQUIRED",
                f"expected one statement, received {len(statements)}",
            )
        )
    if not statements:
        return _empty_result(violations)

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        violations.append(
            SqlViolation("READ_ONLY_QUERY_REQUIRED", "root expression must be a query")
        )

    forbidden_types = (exp.DDL, exp.DML, exp.Command, exp.SetOperation)
    # root가 Query여도 CTE나 하위 식에 write/command가 숨을 수 있으므로 전체 AST를 순회한다.
    # 하나라도 발견하면 SQL을 보정하지 않고 원문 전체를 fail-closed로 거부한다.
    forbidden = next(
        (node for node in statement.walk() if isinstance(node, forbidden_types)),
        None,
    )
    if forbidden is not None:
        violations.append(
            SqlViolation(
                "FORBIDDEN_STATEMENT",
                f"{type(forbidden).__name__} is not allowed",
            )
        )
    if statement.find(exp.Star) is not None:
        violations.append(SqlViolation("STAR_FORBIDDEN", "star projections are not allowed"))
    if any(node.comments for node in statement.walk()):
        violations.append(SqlViolation("COMMENTS_FORBIDDEN", "SQL comments are not allowed"))

    limit = _validate_limit(statement, require_limit, max_limit, violations)
    query = statement if isinstance(statement, exp.Query) else None
    if query is None:
        return _empty_result(violations)

    placeholder_nodes = tuple(query.find_all(exp.Placeholder))
    invalid_placeholder = next(
        (item for item in placeholder_nodes if not _is_parameter_name(item.this)),
        None,
    )
    if invalid_placeholder is not None:
        violations.append(
            SqlViolation(
                "NAMED_PLACEHOLDER_REQUIRED",
                "placeholders must use an ASCII name such as :period_start",
            )
        )
    physical_tables, columns = _lineage(query)
    return SqlValidationResult(
        expression=query,
        canonical_sql=query.sql(dialect=TRINO_DIALECT),
        physical_tables=physical_tables,
        columns=columns,
        projection_aliases=_projection_aliases(query),
        functions=_functions(query),
        joins=_joins(query),
        placeholders=tuple(_placeholder_name(item) for item in placeholder_nodes),
        where_expressions=_clause_expressions(query, exp.Where),
        group_expressions=_clause_expressions(query, exp.Group),
        order_expressions=_clause_expressions(query, exp.Order),
        limit=limit,
        violations=tuple(violations),
    )


def canonicalize_table_fqn(value: str) -> str:
    """단일 table identifier를 Trino AST로 parsing해 비교 가능한 FQN으로 반환한다.

    unquoted identifier만 case-fold하고 quoted identifier는 SQL 표현을 보존하며, table로
    해석되지 않는 값이나 빈 값은 ``ValueError``로 거부한다.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError("table FQN must be a non-empty string")
    try:
        table = sqlglot.parse_one(
            value,
            read=TRINO_DIALECT,
            into=exp.Table,
            error_level=ErrorLevel.RAISE,
        )
    except (ParseError, ValueError) as error:
        raise ValueError("table FQN is invalid") from error
    if not isinstance(table, exp.Table) or not table.parts:
        raise ValueError("table FQN is invalid")
    return _table_fqn(table)


def _empty_result(violations: Iterable[SqlViolation]) -> SqlValidationResult:
    return SqlValidationResult(
        expression=None,
        canonical_sql=None,
        physical_tables=(),
        columns=(),
        projection_aliases=(),
        functions=(),
        joins=(),
        placeholders=(),
        where_expressions=(),
        group_expressions=(),
        order_expressions=(),
        limit=None,
        violations=tuple(violations),
    )


def _validate_limit(
    statement: exp.Expression,
    require_limit: bool,
    max_limit: int,
    violations: list[SqlViolation],
) -> int | None:
    limit_node = statement.args.get("limit")
    if limit_node is None:
        if require_limit:
            violations.append(SqlViolation("LIMIT_REQUIRED", "top-level LIMIT is required"))
        return None
    value = limit_node.expression if isinstance(limit_node, exp.Limit) else None
    if not isinstance(value, exp.Literal) or value.is_string:
        violations.append(
            SqlViolation("LITERAL_LIMIT_REQUIRED", "top-level LIMIT must be an integer literal")
        )
        return None
    try:
        parsed_limit = int(value.this)
    except (TypeError, ValueError):
        violations.append(
            SqlViolation("LITERAL_LIMIT_REQUIRED", "top-level LIMIT must be an integer literal")
        )
        return None
    if str(parsed_limit) != str(value.this) or not 1 <= parsed_limit <= max_limit:
        violations.append(
            SqlViolation(
                "LIMIT_OUT_OF_RANGE",
                f"top-level LIMIT must be between 1 and {max_limit}",
            )
        )
    return parsed_limit


def _lineage(query: exp.Query) -> tuple[tuple[str, ...], tuple[ColumnReference, ...]]:
    tables: list[str] = []
    columns: list[ColumnReference] = []
    for scope in traverse_scope(query):
        source_tables = {
            _source_alias_key(alias, node): _table_fqn(source)
            for alias, (node, source) in scope.selected_sources.items()
            if isinstance(source, exp.Table)
        }
        for fqn in source_tables.values():
            _append_unique(tables, fqn)
        for column in scope.columns:
            qualifier_node = column.args.get("table")
            qualifier = _identifier_value(qualifier_node) if qualifier_node else None
            source = source_tables.get(qualifier) if qualifier else None
            if source is None and not qualifier and len(source_tables) == 1:
                source = next(iter(source_tables.values()))
            reference = ColumnReference(
                name=_identifier_value(column.this),
                qualifier=qualifier,
                source_table=source,
                sql=column.sql(dialect=TRINO_DIALECT),
            )
            if reference not in columns:
                columns.append(reference)
    return tuple(tables), tuple(columns)


def _table_fqn(table: exp.Table) -> str:
    return ".".join(_identifier_value(part) for part in table.parts)


def _source_alias_key(alias: str, source_node: exp.Expression) -> str:
    alias_expression = source_node.args.get("alias")
    if isinstance(alias_expression, exp.TableAlias) and isinstance(
        alias_expression.this, exp.Identifier
    ):
        return _identifier_value(alias_expression.this)
    if isinstance(source_node, exp.Table) and isinstance(
        source_node.this, exp.Identifier
    ):
        return _identifier_value(source_node.this)
    return alias.casefold()


def _identifier_value(identifier: exp.Expression) -> str:
    if not isinstance(identifier, exp.Identifier):
        return identifier.sql(dialect=TRINO_DIALECT)
    if identifier.args.get("quoted"):
        return identifier.sql(dialect=TRINO_DIALECT)
    return identifier.name.casefold()


def _projection_aliases(query: exp.Query) -> tuple[str, ...]:
    # 최종 결과 column만 evidence로 남긴다. CTE 정의 안의 SELECT까지 find_all로 훑으면
    # 외부에 노출되지 않는 중간 projection이 결과 alias로 잘못 섞인다.
    aliases: list[str] = []
    for projection in query.expressions:
        name = projection.alias or projection.output_name
        if name:
            _append_unique(aliases, name)
    return tuple(aliases)


_FUNCTION_TYPES = tuple(exp.ALL_FUNCTIONS)


def _functions(query: exp.Query) -> tuple[str, ...]:
    functions: list[str] = []
    for node in query.walk():
        if not isinstance(node, _FUNCTION_TYPES) or isinstance(
            node, (exp.Binary, exp.Connector, exp.Predicate)
        ):
            continue
        name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
        _append_unique(functions, str(name).upper())
    return tuple(functions)


def _joins(query: exp.Query) -> tuple[JoinReference, ...]:
    joins: list[JoinReference] = []
    for join in query.find_all(exp.Join):
        source_expression = join.this
        source = (
            _table_fqn(source_expression)
            if isinstance(source_expression, exp.Table)
            else source_expression.sql(dialect=TRINO_DIALECT)
        )
        kind_parts = [join.side, join.kind, join.method]
        kind = " ".join(part.upper() for part in kind_parts if part) or "INNER"
        on_expression = join.args.get("on")
        joins.append(
            JoinReference(
                source=source,
                alias=source_expression.alias or None,
                kind=kind,
                on_conjuncts=_conjuncts(on_expression),
            )
        )
    return tuple(joins)


def _conjuncts(expression: exp.Expression | None) -> tuple[str, ...]:
    if expression is None:
        return ()
    if isinstance(expression, exp.And):
        return (*_conjuncts(expression.this), *_conjuncts(expression.expression))
    return (expression.sql(dialect=TRINO_DIALECT),)


def _clause_expressions(query: exp.Query, clause_type: type[exp.Expression]) -> tuple[str, ...]:
    values: list[str] = []
    for clause in query.find_all(clause_type):
        expressions = clause.expressions or ([clause.this] if clause.this is not None else [])
        for expression in expressions:
            _append_unique(values, expression.sql(dialect=TRINO_DIALECT))
    return tuple(values)


def _placeholder_name(placeholder: exp.Placeholder) -> str:
    return str(placeholder.this) if placeholder.this else "?"


def _is_parameter_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.isascii()
        and (value[0].isalpha() or value[0] == "_")
        and all(character.isalnum() or character == "_" for character in value)
    )


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
