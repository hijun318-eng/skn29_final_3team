"""SQLGlot 출력 scope의 table 도입·join kind·predicate·preaggregation grain을 runtime join graph와 정확히 대조하고 사용 edge만 승인한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.pipeline_context_contract import GovernedJoin
from app.services.pipeline_sql_schema import canonical_fqn, field_identity, reverse_operator
from app.services.pipeline_sql_scopes import ProjectionScopeEvidence, SourceEvidence


@dataclass(frozen=True)
class JoinDecision:
    """출력 AST의 join topology가 승인 graph와 일치하는지와 사용 edge ID를 함께 반환한다.

    endpoint·kind·ON equality/temporal 조건·preaggregation 중 하나라도 다르면 첫 위반을
    기록하고 edge ID를 승인 증거로 내보내지 않는다.
    """
    violation: str | None
    used_join_ids: frozenset[str] = frozenset()


def join_violation(
    package: Any,
    physical_tables: set[str],
    scope: ProjectionScopeEvidence,
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> JoinDecision:
    """출력 scope의 실제 join topology를 runtime ``join_graph``와 정확히 대조한다.

    table 도입 순서, join kind, equality·temporal 조건, preaggregation grain을 검증해 첫
    위반 설명을 반환한다. 완전 일치할 때만 사용된 edge ID를 ``JoinDecision``에 확정한다.
    """
    graph: tuple[GovernedJoin, ...] = tuple(getattr(package, "join_graph", ()))
    if set(scope.physical_tables) != physical_tables:
        return JoinDecision(
            "The output scope must derive from every governed physical table exactly once."
        )
    base = scope.scope.base_source
    base_endpoint = base.endpoint if base is not None else None
    if base_endpoint not in physical_tables:
        return JoinDecision("The output scope base source has unresolved lineage.")
    if len(physical_tables) == 1:
        if scope.joins:
            return JoinDecision("The output scope contains an unresolved join source.")
        return JoinDecision(None)
    if len(scope.joins) != len(physical_tables) - 1:
        return JoinDecision("Every physical table must be introduced by one explicit join.")

    joined_sources = {base_endpoint: base}
    used: set[str] = set()
    allowed_cross_table: set[tuple[str, str, str]] = set()
    for actual in scope.joins:
        introduced = actual.source
        endpoint = introduced.endpoint if introduced is not None else None
        if endpoint is None or endpoint in joined_sources:
            return JoinDecision("A join source is unresolved or introduced more than once.")
        candidates = [
            item
            for item in graph
            if item.id not in used
            and endpoint in _endpoints(item)
            and bool((_endpoints(item) - {endpoint}) & set(joined_sources))
        ]
        if len(candidates) != 1:
            return JoinDecision("Each SQL join must resolve to exactly one governed edge.")
        join = candidates[0]
        if join.preaggregation_required:
            error = _preaggregation_violation(
                join,
                {**joined_sources, endpoint: introduced},
                assets,
            )
            if error:
                return JoinDecision(error)
        expected_kind = _oriented_join_kind(join, endpoint)
        if actual.kind != expected_kind:
            return JoinDecision(
                f"SQL join kind for {join.id!r} must be {expected_kind!r}."
            )
        allowed_for_join = _join_comparisons(join, assets)
        required = _required_join_comparisons(join, assets)
        if not required.issubset(actual.comparisons):
            return JoinDecision(f"Governed predicates for join {join.id!r} are incomplete.")
        if any(
            _is_cross_asset(item, assets) and item not in allowed_for_join
            for item in actual.comparisons
        ):
            return JoinDecision("SQL contains an undeclared cross-asset join predicate.")
        allowed_cross_table.update(allowed_for_join)
        joined_sources[endpoint] = introduced
        used.add(join.id)

    if set(joined_sources) != physical_tables:
        return JoinDecision("SQL physical tables are not connected by the governed join_graph.")
    if any(
        _is_cross_asset(item, assets) and item not in allowed_cross_table
        for item in scope.all_comparisons
    ):
        return JoinDecision("SQL contains an undeclared cross-asset predicate.")
    return JoinDecision(None, frozenset(used))


def _preaggregation_violation(
    join: GovernedJoin,
    sources: dict[str, SourceEvidence],
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> str | None:
    required_fields = {
        field_identity(item, assets)
        for item in (*join.preaggregation_grain, *join.preaggregation_keys)
    }
    endpoints = {_asset_name(item, assets) for item in required_fields}
    if len(endpoints) != 1:
        return f"Governed preaggregation for {join.id!r} must target one endpoint."
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
        return f"Governed preaggregation for {join.id!r} requires a direct child scope."
    forbidden = {"limit", "order", "having", "qualify", "sample"}
    if any(child.expression.args.get(name) is not None for name in forbidden):
        return f"Governed preaggregation for {join.id!r} contains a lossy child clause."
    if set(child.group_fields) != required_fields:
        return f"Governed preaggregation grain for {join.id!r} is not exact."
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
        return f"Governed preaggregation join keys for {join.id!r} are not projected."
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
