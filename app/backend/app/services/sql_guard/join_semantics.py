"""SQLGlot AST의 테이블 조인 위상(Topology) 및 사전 집계(Preaggregation Grain) 검증 모듈.

[핵심 목적]
다중 테이블(Cross-Asset) 조회 시, LLM이 생성한 JOIN 절이 DataHub에 승인된 조인 관계(GovernedJoin Graph)에
부합하는지 엄격히 검증합니다.

[주요 검증 항목]
1. 조인 그래프 일치 (Join Graph Topology): 물리 테이블 도입 순서와 연결 엣지(Edge)가 승인된 관계와 일치하는지 검증
2. 필수 조인 조건 (Required Join Predicates): 동등 조인(`a.id = b.id`) 및 유효기간 시계열 조인(`event BETWEEN from AND to`) 누락 방지
3. 사전 집계 단위 (Preaggregation Grain): 1:N 조인 시 집계 왜곡(Fan-out)을 방지하기 위해 사전 집계 서브쿼리가 올바른 Grain으로 작성되었는지 검증
4. 미승인 Cross-asset 조건 차단: 승인되지 않은 임의 테이블 간의 결합 조건이 포함되어 있는지 검사
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlglot import exp

from app.services.context.contract import GovernedJoin
from app.services.context.fanout_policy import (
    AssetGrainEvidence,
    FanoutDecision,
    FanoutPlan,
    GrainSafetyEvidence,
    RelatedSideUse,
    decide_fanout_plan,
)
from app.services.sql_guard.schema import (
    canonical_fqn,
    comparison_evidence,
    field_identity,
    reverse_operator,
    source_aliases,
)
from app.services.sql_guard.scopes import (
    ProjectionScopeEvidence,
    SourceEvidence,
    scope_evidence,
)
from src.ai.sql_policy import SqlValidationResult
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V2


@dataclass(frozen=True)
class JoinDecision:
    """출력 AST의 조인 위상 검증 결과 및 승인된 조인 엣지 ID 목록.

    Attributes:
        violation: 위반 발생 시 상세 오류 메시지 (성공 시 None)
        used_join_ids: 검증을 통과하여 승인된 GovernedJoin ID 집합
        code: 위반 코드 (기본 'JOIN_GRAPH_MISMATCH' 또는 'GRAIN_VIOLATION')
    """

    violation: str | None
    used_join_ids: frozenset[str] = frozenset()
    code: str = "JOIN_GRAPH_MISMATCH"
    fanout_decisions: tuple[FanoutDecision, ...] = ()


def join_violation(
    package: Any,
    physical_tables: set[str],
    scope: ProjectionScopeEvidence,
    assets: dict[str, tuple[Any, frozenset[str]]],
    *,
    result: SqlValidationResult | None = None,
    logical_plan: Any | None = None,
) -> JoinDecision:
    """[책임] 출력 스코프의 실제 JOIN 구문들을 승인된 DataHub join_graph 및 Grain 정책과 대조 검증한다.
    - 입출력: ContextPackage, 물리 테이블 집합, ProjectionScopeEvidence, assets 수신 → 검증 결과 JoinDecision 반환
    - 주의조건: 미승인 조인 엣지 사용, 필수 조인 키 누락, 1:N 조인 시 사전 집계(Preaggregation) 누락 시 차단 반환
    """
    graph: tuple[GovernedJoin, ...] = tuple(getattr(package, "join_graph", ()))
    if (
        len(physical_tables) == 2
        and len(scope.physical_tables) == 1
        and not scope.joins
    ):
        return _semi_join_decision(
            package,
            physical_tables,
            scope,
            assets,
            result,
            logical_plan,
        )
    if set(scope.physical_tables) != physical_tables:
        return JoinDecision(
            "출력 스코프는 거버넌스 승인을 받은 모든 물리 테이블을 정확히 한 번씩만 참조해야 합니다."
        )
    base = scope.scope.base_source
    base_endpoint = base.endpoint if base is not None else None
    if base_endpoint not in physical_tables:
        return JoinDecision("출력 스코프의 기본 FROM 소스에 미해결 리니지가 존재합니다.")
    if len(physical_tables) == 1:
        if scope.joins:
            return JoinDecision("단일 테이블 조회 스코프에 미해결 조인 절이 포함되어 있습니다.")
        return JoinDecision(None)
    if len(scope.joins) != len(physical_tables) - 1:
        return JoinDecision("모든 물리 테이블은 명시적인 1개의 JOIN 절을 통해 도입되어야 합니다.")

    joined_sources = {base_endpoint: base}
    used: set[str] = set()
    allowed_cross_table: set[tuple[str, str, str]] = set()

    for actual in scope.joins:
        introduced = actual.source
        endpoint = introduced.endpoint if introduced is not None else None
        if endpoint is None or endpoint in joined_sources:
            return JoinDecision("조인 대상 소스가 미해결 상태이거나 중복으로 도입되었습니다.")
        candidates = [
            item
            for item in graph
            if item.id not in used
            and endpoint in _endpoints(item)
            and bool((_endpoints(item) - {endpoint}) & set(joined_sources))
        ]
        if len(candidates) != 1:
            return JoinDecision("각 SQL 조인은 정확히 1개의 승인된 거버넌스 조인 엣지와 매칭되어야 합니다.")
        join = candidates[0]

        # 사전 집계(Preaggregation Grain) 검증
        if join.preaggregation_required:
            error = _preaggregation_violation(
                join,
                {**joined_sources, endpoint: introduced},
                assets,
            )
            if error:
                return JoinDecision(error, code="GRAIN_VIOLATION")

        expected_kind = _oriented_join_kind(join, endpoint)
        if actual.kind != expected_kind:
            return JoinDecision(
                f"조인 {join.id!r}의 SQL 조인 유형은 {expected_kind!r}이어야 합니다."
            )
        allowed_for_join = _join_comparisons(join, assets)
        required = _required_join_comparisons(join, assets)
        if not required.issubset(actual.comparisons):
            return JoinDecision(f"조인 {join.id!r}에 필요한 필수 조인 조건식(ON Predicate)이 누락되었습니다.")
        if any(
            _is_cross_asset(item, assets) and item not in allowed_for_join
            for item in actual.comparisons
        ):
            return JoinDecision("SQL에 승인되지 않은 테이블 간 조인 조건식이 포함되어 있습니다.")
        allowed_cross_table.update(allowed_for_join)
        joined_sources[endpoint] = introduced
        used.add(join.id)

    if set(joined_sources) != physical_tables:
        return JoinDecision("물리 테이블들이 승인된 join_graph로 완전히 연결되지 않았습니다.")
    if any(
        _is_cross_asset(item, assets) and item not in allowed_cross_table
        for item in scope.all_comparisons
    ):
        return JoinDecision("SQL에 승인되지 않은 테이블 간 비교 조건식이 포함되어 있습니다.")
    if error := _metric_join_permission_violation(package, frozenset(used)):
        return JoinDecision(error, code="JOIN_PERMISSION_DENIED")
    fanout, error = _fanout_decisions(
        package,
        tuple(item for item in graph if item.id in used),
        joined_sources,
        scope,
        assets,
    )
    if error:
        return JoinDecision(error, code="GRAIN_VIOLATION")
    return JoinDecision(None, frozenset(used), fanout_decisions=fanout)


def _semi_join_decision(
    package: Any,
    physical_tables: set[str],
    scope: ProjectionScopeEvidence,
    assets: dict[str, tuple[Any, frozenset[str]]],
    result: SqlValidationResult | None,
    logical_plan: Any | None,
) -> JoinDecision:
    """filter-only many side를 정확한 correlated EXISTS shape로만 승인한다."""

    if (
        result is None
        or result.expression is None
        or not isinstance(scope.scope.expression, exp.Select)
        or logical_plan is None
        or len(getattr(logical_plan, "joins", ())) != 1
        or getattr(logical_plan.joins[0], "plan", "")
        != FanoutPlan.SEMI_JOIN.value
    ):
        return JoinDecision("SEMI_JOIN은 서버 소유 AnalysisPlan과 SQL AST 증거가 필요합니다.")
    graph = tuple(getattr(package, "join_graph", ()))
    candidates = [item for item in graph if _endpoints(item) == physical_tables]
    if (
        len(candidates) != 1
        or candidates[0].id != logical_plan.joins[0].join_id
    ):
        return JoinDecision("SEMI_JOIN은 정확히 1개의 승인 edge와 일치해야 합니다.")
    join = candidates[0]
    oriented = _oriented_many_one(join)
    if oriented is None:
        return JoinDecision("SEMI_JOIN은 one-to-many 계열 cardinality만 지원합니다.")
    many_asset, one_asset = oriented
    base = scope.scope.base_source
    if base is None or base.endpoint != one_asset:
        return JoinDecision("SEMI_JOIN의 Measure source는 고유성이 증명된 one side여야 합니다.")

    where = scope.scope.expression.args.get("where")
    if not isinstance(where, exp.Where) or where.this is None:
        return JoinDecision("SEMI_JOIN의 correlated EXISTS 조건이 누락되었습니다.")
    conjuncts = _top_level_conjuncts(where.this)
    exists_nodes = [item for item in conjuncts if isinstance(_unwrap(item), exp.Exists)]
    if (
        len(exists_nodes) != 1
        or any(
            isinstance(node, (exp.Or, exp.Not))
            for node in where.this.walk()
        )
    ):
        return JoinDecision("SEMI_JOIN은 최상위 AND에 정확히 1개의 EXISTS만 허용합니다.")
    exists = _unwrap(exists_nodes[0])
    assert isinstance(exists, exp.Exists)
    inner = exists.this
    if not isinstance(inner, exp.Select) or not _minimal_semi_select(inner):
        return JoinDecision("SEMI_JOIN subquery는 SELECT 1과 WHERE predicate만 포함해야 합니다.")
    scopes = scope_evidence(result)
    inner_scope = scopes.get(id(inner))
    if (
        inner_scope is None
        or inner_scope.physical_tables != (many_asset,)
        or inner_scope.joins
        or inner_scope.group_fields
    ):
        return JoinDecision("SEMI_JOIN subquery는 many side 물리 테이블 하나만 참조해야 합니다.")
    inner_where = inner.args.get("where")
    inner_conjuncts = (
        _top_level_conjuncts(inner_where.this)
        if isinstance(inner_where, exp.Where) and inner_where.this is not None
        else ()
    )
    comparison_types = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)
    if not inner_conjuncts or any(
        not isinstance(_unwrap(item), comparison_types) for item in inner_conjuncts
    ):
        return JoinDecision("SEMI_JOIN subquery WHERE는 승인 비교 predicate의 AND만 허용합니다.")

    aliases = source_aliases(result)
    comparisons = comparison_evidence(inner, aliases, result.physical_tables)
    required = _required_join_comparisons(join, assets)
    if not required.issubset(comparisons):
        return JoinDecision("SEMI_JOIN correlation에 승인 join key가 누락되었습니다.")
    allowed = _join_comparisons(join, assets)
    if any(
        _is_cross_asset(item, assets) and item not in allowed
        for item in comparisons
    ):
        return JoinDecision("SEMI_JOIN에 승인되지 않은 cross-asset 비교가 포함되었습니다.")

    many_filters = [
        item
        for item in getattr(logical_plan, "filter_fields", ())
        if canonical_fqn(str(item.asset_fqn)) == many_asset
    ]
    if not many_filters or any(
        (field_identity(item.qualified, assets), item.operator, f":{item.parameter}")
        not in comparisons
        for item in many_filters
    ):
        return JoinDecision("SEMI_JOIN many side의 계획 필터 predicate가 누락되었습니다.")
    root_comparisons = set(scope.scope.where_comparisons)
    if any(
        canonical_fqn(str(item.asset_fqn)) == one_asset
        and (
            field_identity(item.qualified, assets),
            item.operator,
            f":{item.parameter}",
        )
        not in root_comparisons
        for item in getattr(logical_plan, "filter_fields", ())
    ):
        return JoinDecision("SEMI_JOIN one side의 계획 필터 predicate가 누락되었습니다.")
    if error := _metric_join_permission_violation(package, frozenset({join.id})):
        return JoinDecision(error, code="JOIN_PERMISSION_DENIED")
    try:
        decision = decide_fanout_plan(
            join,
            GrainSafetyEvidence(
                measure_assets=frozenset({one_asset}),
                related_side_use=RelatedSideUse.FILTER_ONLY,
                assets=tuple(
                    _asset_grain_evidence(package, endpoint)
                    for endpoint in sorted(physical_tables)
                ),
            ),
        )
    except ValueError as error:
        return JoinDecision(str(error), code="GRAIN_VIOLATION")
    if (
        decision.plan is not FanoutPlan.SEMI_JOIN
        or logical_plan.joins[0].reason != decision.reason.value
    ):
        return JoinDecision(
            "SEMI_JOIN AST와 서버 fan-out 결정이 일치하지 않습니다.",
            code="GRAIN_VIOLATION",
        )
    return JoinDecision(
        None,
        frozenset({join.id}),
        fanout_decisions=(decision,),
    )


def _minimal_semi_select(value: exp.Select) -> bool:
    if len(value.expressions) != 1:
        return False
    projection = value.expressions[0]
    projection = projection.this if isinstance(projection, exp.Alias) else projection
    if (
        not isinstance(projection, exp.Literal)
        or projection.is_string
        or str(projection.this) != "1"
    ):
        return False
    required = value.args.get("from_") is not None and value.args.get("where") is not None
    forbidden = {
        "joins",
        "group",
        "having",
        "qualify",
        "order",
        "limit",
        "offset",
        "with_",
        "distinct",
    }
    return bool(required) and not any(value.args.get(name) for name in forbidden)


def _top_level_conjuncts(value: exp.Expression) -> tuple[exp.Expression, ...]:
    pending = [value]
    result: list[exp.Expression] = []
    while pending:
        item = _unwrap(pending.pop())
        if isinstance(item, exp.And):
            pending.extend((item.expression, item.this))
        else:
            result.append(item)
    return tuple(result)


def _unwrap(value: exp.Expression) -> exp.Expression:
    while isinstance(value, exp.Paren):
        value = value.this
    return value


def _oriented_many_one(join: GovernedJoin) -> tuple[str, str] | None:
    if join.cardinality == "many_to_one":
        return canonical_fqn(join.left), canonical_fqn(join.right)
    if join.cardinality == "one_to_many":
        return canonical_fqn(join.right), canonical_fqn(join.left)
    return None


def _metric_join_permission_violation(
    package: Any,
    used_join_ids: frozenset[str],
) -> str | None:
    """v2 Metric의 edge whitelist가 실제 SQL JOIN 전체를 허용하는지 확인한다."""

    if not used_join_ids:
        return None
    governed = [
        metric
        for metric in tuple(getattr(package, "metrics", ()))
        if str(getattr(metric, "governance_version", ""))
        == RUNTIME_GOVERNANCE_VERSION_V2
    ]
    if not governed:
        return None
    denied = [
        str(metric.id)
        for metric in governed
        if not used_join_ids <= set(getattr(metric, "allowed_join_ids", ()))
    ]
    if denied:
        return (
            "실제 SQL JOIN edge가 선택 Metric의 allowed_join_ids 범위를 벗어났습니다: "
            + ", ".join(sorted(denied))
        )
    return None


def _fanout_decisions(
    package: Any,
    joins: tuple[GovernedJoin, ...],
    sources: dict[str, SourceEvidence],
    scope: ProjectionScopeEvidence,
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> tuple[tuple[FanoutDecision, ...], str | None]:
    """실제 SQL이 사용한 edge마다 measure 방향과 grain 증거로 팬아웃 계획을 검증한다."""

    measure_assets = frozenset(
        canonical_fqn(str(metric.asset_fqn))
        for metric in tuple(getattr(package, "metrics", ()))
        if str(getattr(metric, "aggregation", "")).casefold() != "ratio"
        and str(getattr(metric, "asset_fqn", ""))
    )
    if not measure_assets:
        return (), "JOIN된 SQL의 Measure source asset을 Runtime Context에서 확인할 수 없습니다."
    group_assets = {
        _asset_name(field, assets) for field in scope.scope.group_fields
    } - {""}
    result: list[FanoutDecision] = []
    for join in joins:
        left_component, right_component = _edge_components(join, joins)
        measure_sides = frozenset(
            endpoint
            for endpoint, component in (
                (canonical_fqn(join.left), left_component),
                (canonical_fqn(join.right), right_component),
            )
            if component & measure_assets
        )
        if not measure_sides:
            return (), f"조인 {join.id!r} 어느 쪽에도 Measure grain 증거가 없습니다."
        if len(measure_sides) == 2:
            related_use = RelatedSideUse.SECOND_MEASURE
            common = tuple(join.equality_conditions)
        else:
            non_measure_component = (
                right_component
                if canonical_fqn(join.left) in measure_sides
                else left_component
            )
            related_use = (
                RelatedSideUse.DIMENSION_BREAKDOWN
                if non_measure_component & group_assets
                else RelatedSideUse.FILTER_ONLY
            )
            common = ()
        try:
            evidence = GrainSafetyEvidence(
                measure_assets=measure_sides,
                related_side_use=related_use,
                assets=tuple(
                    _asset_grain_evidence(package, endpoint)
                    for endpoint in sorted({join.left, join.right})
                ),
                common_grain_bindings=common,
            )
            decision = decide_fanout_plan(join, evidence)
        except ValueError as error:
            return (), f"조인 {join.id!r}의 grain 증거가 유효하지 않습니다: {error}"
        if decision.plan is FanoutPlan.REJECT:
            return (), (
                f"조인 {join.id!r}의 팬아웃 안전성을 증명하지 못했습니다: "
                f"{decision.reason.value}"
            )
        if decision.plan is FanoutPlan.SEMI_JOIN:
            # 이 함수에 도달한 edge는 실제 AST의 일반 JOIN 절이다. SEMI_JOIN 결정은
            # EXISTS/IN 격리 형태가 필요하므로 현재 JOIN을 성공으로 오인하지 않는다.
            return (), f"조인 {join.id!r}은 Measure 중복 방지를 위해 SEMI_JOIN 격리가 필요합니다."
        if decision.plan is FanoutPlan.PREAGGREGATE:
            if error := _preaggregation_violation(join, sources, assets):
                return (), error
        result.append(decision)
    return tuple(sorted(result, key=lambda item: item.join_id)), None


def _asset_grain_evidence(package: Any, asset_fqn: str) -> AssetGrainEvidence:
    contracts = getattr(package, "runtime_contracts", None)
    context = contracts.get("schema_context") if isinstance(contracts, dict) else None
    raw_assets = context.get("assets") if isinstance(context, dict) else None
    matches = [
        item
        for item in raw_assets or ()
        if isinstance(item, dict) and canonical_fqn(str(item.get("fqn"))) == asset_fqn
    ]
    if len(matches) != 1:
        raise ValueError("asset grain metadata must resolve exactly once")
    columns = matches[0].get("columns")
    grain = matches[0].get("grain")
    if not isinstance(columns, list) or not isinstance(grain, dict):
        raise ValueError("asset grain metadata is incomplete")
    fields = frozenset(
        f"{asset_fqn}.{item['name']}"
        for item in columns
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )
    raw_keys = grain.get("keys")
    if len(fields) != len(columns) or not isinstance(raw_keys, list) or not raw_keys:
        raise ValueError("asset grain fields are invalid")
    key = tuple(f"{asset_fqn}.{item}" for item in map(str, raw_keys))
    return AssetGrainEvidence(
        asset_fqn=asset_fqn,
        available_fields=fields,
        unique_key_sets=(key,),
    )


def _edge_components(
    removed: GovernedJoin,
    joins: tuple[GovernedJoin, ...],
) -> tuple[frozenset[str], frozenset[str]]:
    adjacency: dict[str, set[str]] = {}
    for join in joins:
        if join.id == removed.id:
            continue
        left, right = canonical_fqn(join.left), canonical_fqn(join.right)
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)

    def walk(start: str) -> frozenset[str]:
        pending = [start]
        visited: set[str] = set()
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            pending.extend(adjacency.get(node, ()))
        return frozenset(visited)

    return walk(canonical_fqn(removed.left)), walk(canonical_fqn(removed.right))


def _preaggregation_violation(
    join: GovernedJoin,
    sources: dict[str, SourceEvidence],
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> str | None:
    """1:N 조인 왜곡을 방지하기 위한 사전 집계 Grain 일치 여부를 검증합니다."""
    required_fields = {
        field_identity(item, assets)
        for item in (*join.preaggregation_grain, *join.preaggregation_keys)
    }
    endpoints = {_asset_name(item, assets) for item in required_fields}
    if len(endpoints) != 1:
        return f"preaggregation for join {join.id!r} must target exactly one join endpoint"
    endpoint = next(iter(endpoints))
    source = sources.get(endpoint)
    child = source.derived_scope if source is not None else None
    direct = child.base_source if child is not None else None
    if (
        child is None
        or direct is None
        or direct.physical_table != endpoint
        or child.joins
        or set(child.physical_tables) != {endpoint}
    ):
        return f"preaggregation for join {join.id!r} must be a direct child scope"
    forbidden = {"limit", "order", "having", "qualify", "sample"}
    if any(child.expression.args.get(name) is not None for name in forbidden):
        return f"preaggregation for join {join.id!r} cannot contain lossy clauses"
    if set(child.group_fields) != required_fields:
        return f"preaggregation for join {join.id!r} must group exactly by required grain"
    projected = set(child.column_origins.values())
    join_fields = {
        field_identity(value, assets)
        for pair in join.equality_conditions
        for value in pair
        if _asset_name(field_identity(value, assets), assets) == endpoint
    }
    join_fields.update(
        field_identity(value, assets)
        for condition in join.temporal_conditions
        for value in condition[:3]
        if _asset_name(field_identity(value, assets), assets) == endpoint
    )
    required_keys = {
        field_identity(item, assets) for item in join.preaggregation_keys
    }
    if not (required_keys | join_fields).issubset(projected):
        return f"preaggregation for join {join.id!r} must project all join and grain keys"
    return None


def _required_join_comparisons(
    join: GovernedJoin,
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> set[tuple[str, str, str]]:
    required = {
        (field_identity(left, assets), "eq", field_identity(right, assets))
        for left, right in join.equality_conditions
    }
    for event, valid_from, valid_to, end_exclusive in join.temporal_conditions:
        required.update(
            {
                (field_identity(event, assets), "gte", field_identity(valid_from, assets)),
                (
                    field_identity(event, assets),
                    "lt" if end_exclusive else "lte",
                    field_identity(valid_to, assets),
                ),
            }
        )
    return required


def _join_comparisons(
    join: GovernedJoin,
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> set[tuple[str, str, str]]:
    required = _required_join_comparisons(join, assets)
    return required | {
        (right, reverse_operator(operator), left)
        for left, operator, right in required
    }


def _endpoints(join: GovernedJoin) -> set[str]:
    return {canonical_fqn(join.left), canonical_fqn(join.right)}


def _asset_name(
    field: str,
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> str:
    matches = [fqn for fqn in assets if field.startswith(f"{fqn}.")]
    return max(matches, key=len) if matches else ""


def _oriented_join_kind(join: GovernedJoin, introduced_source: str) -> str:
    kind = join.kind.casefold()
    if introduced_source == canonical_fqn(join.right):
        return kind
    return {"left": "right", "right": "left"}.get(kind, kind)


def _is_cross_asset(
    comparison: tuple[str, str, str],
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> bool:
    left, _, right = comparison
    return (
        not left.startswith(":")
        and not right.startswith(":")
        and _asset_name(left, assets) != _asset_name(right, assets)
    )
