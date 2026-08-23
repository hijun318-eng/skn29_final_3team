"""AnalysisPlan의 연산·GROUP BY·ORDER BY·LIMIT을 SQLGlot AST와 대조한다."""

from __future__ import annotations

from typing import Any

from sqlglot import exp

from app.services.analysis.logical_plan import AnalysisOperation, AnalysisPlan
from app.services.sql_guard.schema import canonical_fqn, canonical_identifier
from app.services.sql_guard.scopes import ProjectionScopeEvidence, resolve_scope_operand
from src.ai.sql_policy import SqlValidationResult


def operation_violation(
    plan: AnalysisPlan,
    result: SqlValidationResult,
    package: Any,
    output_scope: ProjectionScopeEvidence,
) -> str | None:
    """서버가 확정한 분석 연산을 모델 SQL이 실제 출력 형태로 구현했는지 검증한다.

    질문 문구는 보지 않는다. 최종 SELECT scope의 물리 lineage와 AnalysisPlan의 필드·지표
    binding만 비교하며, 해석할 수 없는 ordinal·임의 계산 차원은 안전한 것으로 추정하지 않는다.
    """

    select = output_scope.scope.expression
    expected_dimensions = {_field_identity(item) for item in plan.dimension_fields}
    group = select.args.get("group")
    group_count = len(group.expressions) if isinstance(group, exp.Group) else 0
    group_fields = set(output_scope.scope.group_fields)

    if plan.operation is AnalysisOperation.TIME_TREND:
        if len(plan.time_fields) != 1:
            return "time_trend는 하나의 공통 governed time field를 요구합니다."
        expected_groups = expected_dimensions | {_field_identity(plan.time_fields[0])}
    elif plan.operation in {
        AnalysisOperation.BREAKDOWN,
        AnalysisOperation.TOP_N,
        AnalysisOperation.BOTTOM_N,
    }:
        expected_groups = expected_dimensions
    elif plan.operation is AnalysisOperation.PERIOD_COMPARISON:
        expected_groups = expected_dimensions
    else:
        expected_groups = set()

    if group_count != len(expected_groups) or group_fields != expected_groups:
        return "SQL GROUP BY가 AnalysisPlan의 차원·시간 grain과 정확히 일치하지 않습니다."

    if plan.operation is AnalysisOperation.TIME_TREND:
        if error := _time_trend_bucket_violation(plan, result, output_scope):
            return error

    projected_origins = set(output_scope.scope.column_origins.values())
    if not expected_groups <= projected_origins:
        return "AnalysisPlan의 GROUP BY 필드가 최종 결과 projection에 모두 포함되지 않았습니다."

    result_fields = {
        canonical_identifier(metric.result_field)
        for metric in getattr(package, "metrics", ())
    }
    if plan.operation is AnalysisOperation.PERIOD_COMPARISON:
        result_fields |= {f"{field}__comparison" for field in result_fields}
    for alias, projection in output_scope.scope.projections.items():
        origin = output_scope.scope.column_origins.get(alias)
        if alias not in result_fields and origin not in expected_groups:
            return (
                "최종 projection에 AnalysisPlan 지표나 GROUP BY 필드가 아닌 출력이 포함되었습니다."
            )

    order = select.args.get("order")
    ordered = tuple(order.expressions) if isinstance(order, exp.Order) else ()
    if plan.operation in {AnalysisOperation.TOP_N, AnalysisOperation.BOTTOM_N}:
        if result.limit != plan.result_limit:
            return "순위 분석 LIMIT이 AnalysisPlan result_limit과 일치하지 않습니다."
        if not ordered:
            return "순위 분석에는 첫 번째 출력 지표 기준 ORDER BY가 필요합니다."
        target_field = _output_result_field(plan, package)
        if not _orders_alias(ordered[0], target_field):
            return "순위 분석 ORDER BY가 첫 번째 출력 지표를 기준으로 하지 않습니다."
        descending = bool(ordered[0].args.get("desc"))
        if descending != (plan.operation is AnalysisOperation.TOP_N):
            return "순위 분석의 정렬 방향이 AnalysisPlan과 일치하지 않습니다."
        dimension_aliases = _dimension_aliases(plan, output_scope)
        if dimension_aliases is None or len(ordered) != len(dimension_aliases) + 1:
            return "순위 분석에는 모든 차원의 안정적인 오름차순 tie-breaker가 필요합니다."
        for order_expression, alias in zip(ordered[1:], dimension_aliases, strict=True):
            if not _orders_alias(order_expression, alias) or bool(
                order_expression.args.get("desc")
            ):
                return "순위 분석 차원 tie-breaker가 AnalysisPlan 순서와 일치하지 않습니다."
    elif plan.operation is AnalysisOperation.TIME_TREND:
        time_aliases = {
            alias
            for alias, origin in output_scope.scope.column_origins.items()
            if origin == _field_identity(plan.time_fields[0])
        }
        dimension_aliases = _dimension_aliases(plan, output_scope)
        if (
            len(time_aliases) != 1
            or dimension_aliases is None
            or len(ordered) != len(dimension_aliases) + 1
            or not any(_orders_alias(ordered[0], alias) for alias in time_aliases)
        ):
            return "time_trend는 governed time projection을 오름차순 정렬해야 합니다."
        if bool(ordered[0].args.get("desc")) or any(
            not _orders_alias(order_expression, alias)
            or bool(order_expression.args.get("desc"))
            for order_expression, alias in zip(
                ordered[1:], dimension_aliases, strict=True
            )
        ):
            return "time_trend의 시간 정렬은 오름차순이어야 합니다."
    elif plan.operation in {
        AnalysisOperation.BREAKDOWN,
        AnalysisOperation.PERIOD_COMPARISON,
    }:
        dimension_aliases = _dimension_aliases(plan, output_scope)
        if dimension_aliases is None or len(ordered) != len(dimension_aliases):
            return "차원 결과는 모든 GROUP BY 필드의 안정적인 오름차순 정렬을 요구합니다."
        for order_expression, alias in zip(ordered, dimension_aliases, strict=True):
            if not _orders_alias(order_expression, alias) or bool(
                order_expression.args.get("desc")
            ):
                return "차원 결과 ORDER BY가 AnalysisPlan 차원 순서와 일치하지 않습니다."
    return None


def _output_result_field(plan: AnalysisPlan, package: Any) -> str:
    by_id = {str(metric.id): metric for metric in getattr(package, "metrics", ())}
    metric = by_id.get(plan.output_metric_ids[0]) if plan.output_metric_ids else None
    if metric is None:
        raise ValueError("AnalysisPlan 출력 Metric이 Runtime Context에 없습니다.")
    return canonical_identifier(metric.result_field)


def _time_trend_bucket_violation(
    plan: AnalysisPlan,
    result: SqlValidationResult,
    output_scope: ProjectionScopeEvidence,
) -> str | None:
    """시간 projection과 GROUP BY가 계획 grain의 정확한 구조인지 검증한다."""

    if result.expression is None or len(plan.time_fields) != 1:
        return "time_trend 시간 AST를 검증할 수 없습니다."
    identity = _field_identity(plan.time_fields[0])
    aliases = [
        alias
        for alias, origin in output_scope.scope.column_origins.items()
        if origin == identity
    ]
    if len(aliases) != 1 or canonical_identifier(aliases[0]) != "period":
        return "time_trend 시간 projection은 단일 period alias여야 합니다."
    projection = output_scope.scope.projections.get(aliases[0])
    if projection is None:
        return "time_trend period projection을 찾을 수 없습니다."
    value = projection.this if isinstance(projection, exp.Alias) else projection
    group = output_scope.scope.expression.args.get("group")
    matching_groups = [
        item
        for item in (group.expressions if isinstance(group, exp.Group) else ())
        if resolve_scope_operand(item, output_scope.scope) == identity
    ]
    if len(matching_groups) != 1:
        return "time_trend period GROUP BY를 유일하게 확인할 수 없습니다."

    truncations = tuple(
        node
        for node in result.expression.walk()
        if isinstance(node, (exp.TimestampTrunc, exp.DateTrunc))
    )
    if plan.time_bucket == "day":
        if truncations or not isinstance(value, exp.Column):
            return "day time_trend는 governed time field를 변환 없이 사용해야 합니다."
        if resolve_scope_operand(value, output_scope.scope) != identity:
            return "day time_trend projection이 governed time field와 다릅니다."
    else:
        if not isinstance(value, exp.Cast):
            return "coarser time_trend는 DATE로 CAST한 DATE_TRUNC projection을 요구합니다."
        target_type = value.args.get("to")
        truncated = value.this
        if (
            not isinstance(target_type, exp.DataType)
            or target_type.sql(dialect="trino").upper() != "DATE"
            or not isinstance(truncated, (exp.TimestampTrunc, exp.DateTrunc))
        ):
            return "coarser time_trend의 CAST·DATE_TRUNC 구조가 계약과 다릅니다."
        unit = truncated.args.get("unit")
        unit_name = getattr(unit, "name", "")
        if str(unit_name).casefold() != plan.time_bucket:
            return "DATE_TRUNC calendar unit이 AnalysisPlan time bucket과 다릅니다."
        if resolve_scope_operand(truncated.this, output_scope.scope) != identity:
            return "DATE_TRUNC operand가 governed time field와 다릅니다."
        if len(truncations) != 2:
            return "coarser time_trend는 projection과 GROUP BY의 DATE_TRUNC만 허용합니다."

    if matching_groups[0].sql(dialect="trino") != value.sql(dialect="trino"):
        return "time_trend projection과 GROUP BY 시간 표현식이 동일하지 않습니다."
    return None


def _dimension_aliases(
    plan: AnalysisPlan,
    output_scope: ProjectionScopeEvidence,
) -> tuple[str, ...] | None:
    """계획 차원마다 유일한 최종 projection alias를 계획 순서대로 반환한다."""

    aliases: list[str] = []
    for field in plan.dimension_fields:
        identity = _field_identity(field)
        candidates = [
            alias
            for alias, origin in output_scope.scope.column_origins.items()
            if origin == identity
        ]
        if len(candidates) != 1:
            return None
        aliases.append(candidates[0])
    return tuple(aliases)


def _field_identity(field: Any) -> str:
    return f"{canonical_fqn(field.asset_fqn)}.{canonical_identifier(field.column)}"


def _orders_alias(ordered: exp.Expression, alias: str) -> bool:
    value = ordered.this if isinstance(ordered, exp.Ordered) else ordered
    return (
        isinstance(value, exp.Column)
        and value.args.get("table") is None
        and canonical_identifier(value.name) == canonical_identifier(alias)
    )
