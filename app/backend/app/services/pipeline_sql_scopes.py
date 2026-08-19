"""SQLGlot SELECT scope별 물리·derived source, projection origin, WHERE/JOIN 비교를 구축하며 모호한 비수식 column은 lineage로 추정하지 않는다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from app.services.pipeline_sql_schema import (
    canonical_identifier,
    identifier_node,
    reverse_operator,
)
from src.ai.sql_policy import SqlValidationResult


@dataclass(frozen=True)
class SourceEvidence:
    """FROM/JOIN source가 직접 물리 FQN인지 검증된 derived scope인지 구분하는 lineage 단위다.

    둘 중 확인된 근거만 보존하며 복합·미해석 derived lineage는 단일 endpoint로 축약하지
    않아 join graph 검증이 출처를 추정하지 못하게 한다.
    """
    physical_table: str | None
    derived_scope: ScopeEvidence | None

    @property
    def physical_tables(self) -> frozenset[str]:
        """직접 table 또는 derived scope가 실제 의존하는 물리 FQN 집합을 반환한다.

        lineage가 해석되지 않은 source는 빈 집합으로 남겨 상위 join 검증이 이를 승인하지 못하게 한다.
        """
        if self.physical_table is not None:
            return frozenset({self.physical_table})
        if self.derived_scope is not None:
            return frozenset(self.derived_scope.physical_tables)
        return frozenset()

    @property
    def endpoint(self) -> str | None:
        """join graph의 단일 endpoint로 사용할 수 있는 물리 FQN을 반환한다.

        직접 table은 그대로 반환하고 derived source는 join 없는 단일-table scope일 때만
        endpoint를 전달하며, 복합 lineage는 ``None``으로 보수적으로 처리한다.
        """
        if self.physical_table is not None:
            return self.physical_table
        if self.derived_scope is not None:
            return self.derived_scope.derived_endpoint
        return None


@dataclass(frozen=True)
class JoinClauseEvidence:
    """SQLGlot JOIN 한 절에서 추출한 오른쪽 source, join kind와 최상위 ON 비교 집합이다.

    이 구조는 각 절을 승인 edge와 개별 대조하기 위한 것으로, 다른 WHERE나 인접 JOIN의
    조건을 합쳐 누락된 ON predicate를 보충하지 않는다.
    """
    source: SourceEvidence | None
    kind: str
    comparisons: frozenset[tuple[str, str, str]]


@dataclass(frozen=True)
class ScopeEvidence:
    """하나의 SELECT scope에서 해석된 source lineage, projection, filter, group과 join 증거다.

    원본 SQLGlot expression과 alias별 source·column origin을 함께 유지해 CTE/서브쿼리
    경계를 섞지 않는다. 물리 table 순서와 최상위 비교만 semantic validator에 제공한다.
    """
    expression: exp.Select
    sources: dict[str, SourceEvidence]
    physical_tables: tuple[str, ...]
    base_source: SourceEvidence | None
    projections: dict[str, exp.Expression]
    column_origins: dict[str, str]
    where_comparisons: frozenset[tuple[str, str, str]]
    all_comparisons: frozenset[tuple[str, str, str]]
    group_fields: frozenset[str]
    joins: tuple[JoinClauseEvidence, ...]

    @property
    def derived_endpoint(self) -> str | None:
        """derived scope가 한 물리 table의 투명한 endpoint인지 판정한다.

        join이 있거나 물리 table 수가 하나가 아니면 ``None``을 반환해 복합 query를 단일 asset으로 축약하지 않는다.
        """
        if self.joins or len(self.physical_tables) != 1:
            return None
        return self.physical_tables[0]


@dataclass(frozen=True)
class ProjectionScopeEvidence:
    """최종 출력 projection 집합과 그 projection을 소유한 SELECT scope를 결속한다.

    metric shape·alias·aggregate를 검사할 때 같은 scope의 WHERE, GROUP BY, JOIN lineage만
    참조하게 하여 child CTE나 sibling expression의 조건을 승인 근거로 재사용하지 못하게 한다.
    """
    scope: ScopeEvidence
    projections: tuple[exp.Expression, ...]

    @property
    def physical_tables(self) -> tuple[str, ...]:
        """선택된 projection을 소유한 scope의 물리 table lineage를 원래 순서로 반환한다."""
        return self.scope.physical_tables

    @property
    def base_table(self) -> str | None:
        """출력 scope의 FROM source가 단일 governed endpoint이면 그 FQN을 반환한다.

        base source가 없거나 derived lineage가 복합이면 ``None``으로 남겨 join 기준점을 추정하지 않는다.
        """
        source = self.scope.base_source
        return source.endpoint if source is not None else None

    @property
    def where_comparisons(self) -> frozenset[tuple[str, str, str]]:
        """해당 projection scope의 최상위 WHERE에서 확정된 비교 근거만 반환한다."""
        return self.scope.where_comparisons

    @property
    def all_comparisons(self) -> frozenset[tuple[str, str, str]]:
        """중첩 query를 제외한 현재 scope 전체의 비교 근거를 반환한다.

        join graph 검사가 WHERE나 JOIN ON에 숨은 미승인 cross-asset 조건을 함께 탐지하는 데 사용한다.
        """
        return self.scope.all_comparisons

    @property
    def joins(self) -> tuple[JoinClauseEvidence, ...]:
        """현재 출력 scope에 선언된 join source·kind·predicate 근거를 AST 순서대로 반환한다."""
        return self.scope.joins


def projection_scope_evidence(
    result: SqlValidationResult,
    projection_alias: object,
) -> ProjectionScopeEvidence | None:
    """검증된 root SELECT에서 지정 output alias의 scope-local AST 근거를 찾는다.

    root가 SELECT가 아니거나 alias가 없거나 scope 구축에 실패하면 ``None``을 반환해 metric
    검증이 fail-closed 되며, 일치하면 정확히 그 projection 하나만 묶어 반환한다.
    """
    if not isinstance(result.expression, exp.Select):
        return None
    scopes = scope_evidence(result)
    root = scopes.get(id(result.expression))
    if root is None:
        return None
    target = canonical_identifier(projection_alias)
    projection = root.projections.get(target)
    if projection is None:
        return None
    return ProjectionScopeEvidence(root, (projection,))


def scope_evidence(result: SqlValidationResult) -> dict[int, ScopeEvidence]:
    """공유 SQLGlot AST의 SELECT scope를 자식부터 lineage 증거로 구축한다.

    parse expression이 없으면 빈 mapping을 반환한다. key는 AST 객체 identity이므로 같은
    이름의 CTE나 alias가 있어도 서로 다른 scope 근거를 합치지 않는다.
    """
    if result.expression is None:
        return {}
    built: dict[int, ScopeEvidence] = {}
    for scope in traverse_scope(result.expression):
        if isinstance(scope.expression, exp.Select):
            evidence = _build_scope(scope, built)
            built[id(scope.expression)] = evidence
    return built


def resolve_scope_operand(
    value: exp.Expression,
    scope: ScopeEvidence,
) -> str | None:
    """범위 operand 후보를 거버넌스 제약과 입력 증거로 판정해 하나의 결과로 좁힌다."""
    while isinstance(value, (exp.Cast, exp.Paren, exp.FromISO8601Timestamp)):
        value = value.this
    if isinstance(value, exp.Placeholder):
        return f":{value.name}"
    resolved = source_column(value, scope)
    if resolved is None:
        return None
    source, name = resolved
    if source.physical_table is not None:
        return f"{source.physical_table}.{name}"
    if source.derived_scope is not None:
        return source.derived_scope.column_origins.get(name)
    return None


def source_column(
    value: exp.Expression,
    scope: ScopeEvidence,
) -> tuple[SourceEvidence, str] | None:
    """column AST를 현재 scope의 source와 표준 column 이름으로 해석한다.

    qualifier가 있으면 해당 alias만 사용하고, 없으면 source가 정확히 하나일 때만 연결한다.
    literal·복합식·모호한 비수식 column은 ``None``으로 반환해 lineage를 추측하지 않는다.
    """
    while isinstance(value, exp.Paren):
        value = value.this
    if not isinstance(value, exp.Column):
        return None
    name = identifier_node(value.this)
    qualifier = value.args.get("table")
    if qualifier is not None:
        source = scope.sources.get(identifier_node(qualifier))
        return (source, name) if source is not None else None
    if len(scope.sources) == 1:
        return next(iter(scope.sources.values())), name
    return None


def _build_scope(
    scope: Scope,
    built: dict[int, ScopeEvidence],
) -> ScopeEvidence:
    select = scope.expression
    sources: dict[str, SourceEvidence] = {}
    for alias, (node, source) in scope.selected_sources.items():
        key = _source_key(alias, node)
        if isinstance(source, exp.Table):
            table = ".".join(identifier_node(item) for item in source.parts)
            sources[key] = SourceEvidence(table, None)
        elif isinstance(source, Scope):
            sources[key] = SourceEvidence(None, built.get(id(source.expression)))
    tables = tuple(
        dict.fromkeys(
            table
            for source in sources.values()
            for table in source.physical_tables
        )
    )
    placeholder = ScopeEvidence(
        expression=select,
        sources=sources,
        physical_tables=tables,
        base_source=None,
        projections={},
        column_origins={},
        where_comparisons=frozenset(),
        all_comparisons=frozenset(),
        group_fields=frozenset(),
        joins=(),
    )
    projections = {
        canonical_identifier(item.alias_or_name): item
        for item in select.expressions
        if item.alias_or_name
    }
    origins = {
        name: identity
        for name, item in projections.items()
        if (
            identity := resolve_scope_operand(
                item.this if isinstance(item, exp.Alias) else item,
                placeholder,
            )
        )
    }
    from_clause = select.args.get("from_")
    base_expression = from_clause.this if isinstance(from_clause, exp.From) else None
    base_source = _expression_source(base_expression, sources)
    where = select.args.get("where")
    where_values = (
        _clause_comparisons(where.this, placeholder)
        if isinstance(where, exp.Where) and where.this is not None
        else set()
    )
    group = select.args.get("group")
    group_fields = frozenset(
        identity
        for item in (group.expressions if isinstance(group, exp.Group) else ())
        if (identity := resolve_scope_operand(item, placeholder))
    )
    joins = tuple(
        JoinClauseEvidence(
            source=_expression_source(join.this, sources),
            kind=_join_kind(join),
            comparisons=frozenset(
                _clause_comparisons(on, placeholder) if on is not None else ()
            ),
        )
        for join in select.args.get("joins", ())
        if isinstance(join, exp.Join)
        for on in (join.args.get("on"),)
    )
    return ScopeEvidence(
        expression=select,
        sources=sources,
        physical_tables=tables,
        base_source=base_source,
        projections=projections,
        column_origins=origins,
        where_comparisons=frozenset(where_values),
        all_comparisons=frozenset(_all_comparisons(select, placeholder)),
        group_fields=group_fields,
        joins=joins,
    )


def _clause_comparisons(
    expression: exp.Expression,
    scope: ScopeEvidence,
) -> set[tuple[str, str, str]]:
    values: set[tuple[str, str, str]] = set()
    for conjunct in _top_level_conjuncts(expression):
        values.update(_comparison(conjunct, scope))
    return values


def _all_comparisons(
    expression: exp.Expression,
    scope: ScopeEvidence,
) -> set[tuple[str, str, str]]:
    values: set[tuple[str, str, str]] = set()
    for node in expression.walk(
        prune=lambda item: item is not expression and isinstance(item, exp.Query)
    ):
        values.update(_comparison(node, scope))
    return values


def _comparison(
    expression: exp.Expression,
    scope: ScopeEvidence,
) -> set[tuple[str, str, str]]:
    node = _without_parentheses(expression)
    operators = (
        (exp.EQ, "eq"),
        (exp.NEQ, "neq"),
        (exp.GT, "gt"),
        (exp.GTE, "gte"),
        (exp.LT, "lt"),
        (exp.LTE, "lte"),
    )
    operator = next(
        (name for kind, name in operators if isinstance(node, kind)),
        None,
    )
    if operator is None:
        return set()
    left = resolve_scope_operand(node.this, scope)
    right = resolve_scope_operand(node.expression, scope)
    if not left or not right:
        return set()
    return {
        (left, operator, right),
        (right, reverse_operator(operator), left),
    }


def _top_level_conjuncts(
    expression: exp.Expression,
) -> tuple[exp.Expression, ...]:
    pending = [expression]
    conjuncts: list[exp.Expression] = []
    while pending:
        current = _without_parentheses(pending.pop())
        if isinstance(current, exp.And):
            pending.extend((current.expression, current.this))
        else:
            conjuncts.append(current)
    return tuple(conjuncts)


def _without_parentheses(expression: exp.Expression) -> exp.Expression:
    while isinstance(expression, exp.Paren):
        expression = expression.this
    return expression


def _source_key(alias: str, node: exp.Expression) -> str:
    alias_node = node.args.get("alias")
    return (
        identifier_node(alias_node.this)
        if isinstance(alias_node, exp.TableAlias)
        else canonical_identifier(alias)
    )


def _expression_source(
    expression: exp.Expression | None,
    sources: dict[str, SourceEvidence],
) -> SourceEvidence | None:
    if not isinstance(expression, exp.Table):
        return None
    alias = expression.args.get("alias")
    key = (
        identifier_node(alias.this)
        if isinstance(alias, exp.TableAlias)
        else identifier_node(expression.this)
    )
    return sources.get(key)


def _join_kind(join: exp.Join) -> str:
    side = str(join.side or "").casefold()
    kind = str(join.kind or "").casefold()
    if side in {"left", "right", "full"}:
        return side
    if kind in {"inner", "cross"}:
        return kind
    return "inner"
