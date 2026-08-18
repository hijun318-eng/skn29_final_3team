"""runtime metric별 필수 filter와 반개방 기간 predicate를 AST 근거에서 확인하고, 검증된 table·column·join·metric만 응답 lineage로 직렬화한다."""

from __future__ import annotations

from typing import Any

from app.services.pipeline_sql_join_semantics import JoinDecision, join_violation
from app.services.pipeline_sql_metric_semantics import (
    MetricMatch,
    match_metric,
    metric_matches,
)
from app.services.pipeline_sql_schema import canonical_fqn, field_identity
from src.ai.sql_policy import SqlValidationResult


def required_filter_violation(
    package: Any,
    comparisons: set[tuple[str, str, str]],
    assets: dict[str, tuple[Any, frozenset[str]]],
    metric_id: str | None = None,
) -> str | None:
    """runtime metric 규칙의 필수 filter가 AST 비교 근거에 모두 있는지 검사한다.

    metric ID를 지정하면 정확히 한 규칙만 허용하고, field·operator·named parameter가
    승인 schema와 일치하지 않는 첫 사유를 반환한다. 모두 충족할 때만 ``None``이다.
    """
    contracts = getattr(package, "runtime_contracts", None) or {}
    rules = contracts.get("metric_rules") or ()
    selected = [
        item
        for item in rules
        if metric_id is None or str(item.get("id")) == metric_id
    ]
    if metric_id is not None and len(selected) != 1:
        return f"Runtime metric rule {metric_id!r} is missing or duplicated."
    for rule in selected:
        for item in rule.get("required_filters", ()):
            field_value = item.get("field") if isinstance(item, dict) else None
            if not isinstance(field_value, dict):
                return "Runtime required filter field is invalid."
            field = field_identity(
                f"{field_value.get('asset_fqn')}.{field_value.get('column')}",
                assets,
            )
            parameter = str(item.get("parameter") or "")
            operator = str(item.get("operator") or "")
            if not parameter or (field, operator, f":{parameter}") not in comparisons:
                return f"Required filter parameter {parameter!r} is missing."
    return None


def time_rule_violation(
    package: Any,
    comparisons: set[tuple[str, str, str]],
    assets: dict[str, tuple[Any, frozenset[str]]],
    metric: Any | None = None,
) -> str | None:
    """metric time field가 runtime 기간 parameter로 반개방 조건을 구현했는지 검사한다.

    metric이 명시되지 않으면 단일 metric context에서만 선택하며, ``>= start``와 ``< end``
    AST 근거가 모두 없으면 위반 설명을 반환한다. 고정 날짜나 질문 문구는 사용하지 않는다.
    """
    contracts = getattr(package, "runtime_contracts", None) or {}
    time_rules = contracts.get("time_rules") or {}
    selected = metric or (package.metrics[0] if len(package.metrics) == 1 else None)
    if selected is None:
        return "A metric-specific time rule is required."
    if not selected.time_field:
        return None
    field = field_identity(f"{selected.asset_fqn}.{selected.time_field}", assets)
    start_parameter = str(time_rules.get("start_parameter") or "")
    end_parameter = str(time_rules.get("end_parameter") or "")
    required = {
        (field, "gte", f":{start_parameter}"),
        (field, "lt", f":{end_parameter}"),
    }
    if not start_parameter or not end_parameter or not required.issubset(comparisons):
        return "Metric time field must use the governed half-open period parameters."
    return None


def references(
    result: SqlValidationResult,
    package: Any,
    assets: dict[str, tuple[Any, frozenset[str]]],
    used_join_ids: frozenset[str],
) -> tuple[dict[str, Any], ...]:
    """승인 AST의 물리 table별 column·join·metric lineage를 응답 근거로 만든다.

    SQLGlot이 확인한 table과 column만 포함하고 runtime graph에서 실제 사용이 확정된 join ID,
    해당 asset의 metric ID를 정렬해 반환한다. 모델이 선언한 references를 그대로 복사하지 않는다.
    """
    graph = tuple(getattr(package, "join_graph", ()))
    metrics = tuple(getattr(package, "metrics", ()))
    output = []
    for fqn in result.physical_tables:
        asset = assets[fqn][0]
        columns = sorted({item.name for item in result.columns if item.source_table == fqn})
        output.append(
            {
                "urn": asset.urn,
                "fqn": fqn,
                "columns": columns,
                "join_ids": sorted(
                    item.id
                    for item in graph
                    if item.id in used_join_ids
                    and fqn in {canonical_fqn(item.left), canonical_fqn(item.right)}
                ),
                "metric_ids": sorted(
                    str(metric.id)
                    for metric in metrics
                    if canonical_fqn(metric.asset_fqn) == fqn
                ),
            }
        )
    return tuple(output)


__all__ = [
    "JoinDecision",
    "MetricMatch",
    "join_violation",
    "match_metric",
    "metric_matches",
    "references",
    "required_filter_violation",
    "time_rule_violation",
]
