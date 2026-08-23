"""SQLGlot AST의 SELECT Scope 분석 및 Lineage/Join/Projection 증거 추출 모듈.

[핵심 목적]
복잡한 중첩 쿼리, 서브쿼리, CTE(공통 테이블 식별자), 파생 테이블(Derived Table) 구조에서
각 SELECT scope별 물리적 테이블 출처(Source Evidence), 프로젝션 식별자(Projection Origin),
WHERE/JOIN 절의 비교 연산 증거(Comparison Evidence)를 정밀하게 추출하고 보존합니다.

[보안 및 거버넌스 원칙]
1. 비수식 컬럼의 임의 추정 금지: 모호한 컬럼명이 여러 소스에 걸쳐 있을 때 임의로 출처를 추측하지 않고 검증을 차단(Fail-closed)합니다.
2. 스코프 격리: 하위 서브쿼리나 형제 CTE의 조건을 상위 쿼리의 승인 증거로 부당하게 혼용하지 않도록 스코프 경계를 명확히 분리합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from app.services.sql_guard.schema import (
    canonical_identifier,
    identifier_node,
    reverse_operator,
)
from src.ai.sql_policy import SqlValidationResult


@dataclass(frozen=True)
class SourceEvidence:
    """FROM 또는 JOIN 절의 소스가 물리 테이블인지 검증된 파생 스코프(Derived Scope)인지 나타내는 증거 클래스."""

    physical_table: str | None
    derived_scope: ScopeEvidence | None

    @property
    def physical_tables(self) -> frozenset[str]:
        """직접 테이블 또는 파생 스코프가 의존하는 실제 물리 FQN 집합을 반환합니다."""
        if self.physical_table is not None:
            return frozenset({self.physical_table})
        if self.derived_scope is not None:
            return frozenset(self.derived_scope.physical_tables)
        return frozenset()

    @property
    def endpoint(self) -> str | None:
        """조인 그래프 검증에 사용할 수 있는 단일 물리 FQN 엔드포인트를 반환합니다."""
        if self.physical_table is not None:
            return self.physical_table
        if self.derived_scope is not None:
            return self.derived_scope.derived_endpoint
        return None


@dataclass(frozen=True)
class JoinClauseEvidence:
    """단일 JOIN 절에서 추출한 조인 대상 소스, 조인 종류(INNER/LEFT 등), ON 절의 비교 조건 집합."""

    source: SourceEvidence | None
    kind: str
    comparisons: frozenset[tuple[str, str, str]]


@dataclass(frozen=True)
class ScopeEvidence:
    """단일 SELECT 스코프에서 분석된 소스 리니지, 프로젝션 컬럼, 필터 및 조인 증거 데이터 클래스."""

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
        """파생 스코프가 조인이 없는 단일 물리 테이블의 투명한 엔드포인트인지 검사합니다."""
        if self.joins or len(self.physical_tables) != 1:
            return None
        return self.physical_tables[0]


@dataclass(frozen=True)
class ProjectionScopeEvidence:
    """최종 출력 프로젝션 집합과 해당 프로젝션을 소유한 SELECT 스코프를 묶은 증거 클래스."""

    scope: ScopeEvidence
    projections: tuple[exp.Expression, ...]

    @property
    def physical_tables(self) -> tuple[str, ...]:
        """프로젝션을 소유한 스코프의 물리 테이블 목록을 반환합니다."""
        return self.scope.physical_tables

    @property
    def base_table(self) -> str | None:
        """FROM 절의 기본 테이블 FQN을 반환합니다."""
        source = self.scope.base_source
        return source.endpoint if source is not None else None

    @property
    def where_comparisons(self) -> frozenset[tuple[str, str, str]]:
        """해당 스코프의 WHERE 절 비교 조건들을 반환합니다."""
        return self.scope.where_comparisons

    @property
    def all_comparisons(self) -> frozenset[tuple[str, str, str]]:
        """해당 스코프 전체의 모든 비교 조건들을 반환합니다."""
        return self.scope.all_comparisons

    @property
    def joins(self) -> tuple[JoinClauseEvidence, ...]:
        """해당 스코프에 선언된 조인 목록을 반환합니다."""
        return self.scope.joins


def projection_scope_evidence(
    result: SqlValidationResult,
    projection_alias: object,
) -> ProjectionScopeEvidence | None:
    """루트 SELECT 문에서 지정된 출력 alias에 해당하는 스코프 로컬 증거를 조회합니다."""
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
    """SQLGlot AST의 모든 SELECT 스코프를 순회하며 각 스코프별 증거 맵을 구축합니다."""
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
    """스코프 내의 표현식 노드를 'FQN.column' 또는 ':named_param' 형태로 해석합니다."""
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
    """컬럼 AST 노드를 현재 스코프의 소스 증거와 표준 컬럼명 튜플로 해석합니다."""
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
    """단일 SQLGlot Scope 객체로부터 ScopeEvidence 객체를 조립하는 내부 함수."""
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
        clause_comparisons(where.this, placeholder)
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
                clause_comparisons(on, placeholder) if on is not None else ()
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


def clause_comparisons(
    expression: exp.Expression,
    scope: ScopeEvidence,
) -> set[tuple[str, str, str]]:
    """AND 조건으로 결합된 최상위 비교 표현식들을 (left, op, right) 튜플 집합으로 추출합니다."""
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
    if not isinstance(expression, (exp.Table, exp.Subquery)):
        return None
    alias = expression.args.get("alias")
    if isinstance(alias, exp.TableAlias):
        key = identifier_node(alias.this)
    elif isinstance(expression, exp.Table):
        key = identifier_node(expression.this)
    else:
        return None
    return sources.get(key)


def _join_kind(join: exp.Join) -> str:
    side = str(join.side or "").casefold()
    kind = str(join.kind or "").casefold()
    if side in {"left", "right", "full"}:
        return side
    if kind in {"inner", "cross"}:
        return kind
    return "inner"
