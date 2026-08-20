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

from app.services.context.contract import GovernedJoin
from app.services.sql_guard.schema import canonical_fqn, field_identity, reverse_operator
from app.services.sql_guard.scopes import ProjectionScopeEvidence, SourceEvidence


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


def join_violation(
    package: Any,
    physical_tables: set[str],
    scope: ProjectionScopeEvidence,
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> JoinDecision:
    """출력 스코프의 실제 JOIN 구문들을 runtime join_graph와 정밀 대조하여 검증합니다.

    Args:
        package: ContextPackage 인스턴스 (join_graph 포함)
        physical_tables: 쿼리에서 사용된 물리 테이블 FQN 집합
        scope: 프로젝션 스코프 증거
        assets: 승인된 자산 룩업 맵

    Returns:
        JoinDecision 객체 (위반 여부 및 사용된 조인 ID 목록)
    """
    graph: tuple[GovernedJoin, ...] = tuple(getattr(package, "join_graph", ()))
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
    return JoinDecision(None, frozenset(used))


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
