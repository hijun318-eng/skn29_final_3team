"""승인 ContextPackage에서 실행 시간·Glossary 지표·entitlement를 provider-neutral 입력으로 추출한다.

Provider-neutral access to governed runtime ContextPackage data.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo


_CONTRACT_NAMES = {
    "schema_context",
    "metric_rules",
    "join_graph",
    "time_rules",
    "parameter_contract",
    "query_policy",
}


def execution_time(
    context: Any,
    package: Any,
) -> dict[str, str]:
    """런타임 컨텍스트에서 timezone이 포함된 기준 실행 시각을 검증해 읽는다."""
    contracts = getattr(package, "runtime_contracts", None)
    if not isinstance(contracts, dict) or set(contracts) != _CONTRACT_NAMES:
        raise ValueError("runtime Context contracts are incomplete")
    time_rules = contracts["time_rules"]
    timezone = ZoneInfo(context.timezone)
    as_of = datetime.combine(context.as_of, time.min, timezone)
    bindings = {item.name: item for item in package.parameter_bindings}
    mode = str(time_rules.get("mode") or "range")
    if mode == "latest_snapshot":
        parameter = str(time_rules.get("as_of_parameter") or "")
        binding = bindings.get(parameter)
        if (
            time_rules.get("selection") != "max_source_value_lt_as_of"
            or binding is None
            or binding.value_type != "date"
            or not isinstance(binding.value, str)
        ):
            raise ValueError("runtime Context snapshot binding is incomplete")
        try:
            cutoff = date.fromisoformat(binding.value)
        except ValueError as error:
            raise ValueError("runtime Context snapshot cutoff is not an ISO date") from error
        return {
            "as_of": as_of.isoformat(),
            "timezone": context.timezone,
            "calendar_id": str(time_rules["calendar_id"]),
            "time_mode": mode,
            "snapshot_cutoff": cutoff.isoformat(),
            "selection": "max_source_value_lt_as_of",
        }
    if mode != "range":
        raise ValueError("runtime Context time mode is unsupported")
    start_name = str(time_rules["start_parameter"])
    end_name = str(time_rules["end_parameter"])
    if {start_name, end_name}.difference(bindings):
        raise ValueError("runtime Context period bindings are incomplete")
    start, end = bindings[start_name], bindings[end_name]
    if (
        start.value_type != "date"
        or end.value_type != "date"
        or not isinstance(start.value, str)
        or not isinstance(end.value, str)
    ):
        raise ValueError("runtime Context period bindings must be typed dates")
    try:
        start_date = date.fromisoformat(start.value)
        end_date = date.fromisoformat(end.value)
    except ValueError as error:
        raise ValueError("runtime Context period binding is not an ISO date") from error
    if start_date >= end_date:
        raise ValueError("runtime Context period range is invalid")
    return {
        "as_of": as_of.isoformat(),
        "timezone": context.timezone,
        "calendar_id": str(time_rules["calendar_id"]),
        "period_start": datetime.combine(start_date, time.min, timezone).isoformat(),
        "period_end_exclusive": datetime.combine(end_date, time.min, timezone).isoformat(),
    }


def metric_term(metric_id: str, package: Any) -> Any:
    """승인된 Context의 DataHub 용어 중 ``metric_id``와 정확히 일치하는 항목을 찾는다.

    지표가 누락되면 모델이 이름을 추정하지 못하도록 ``ValueError``로 닫힌다.
    """
    try:
        return next(term for term in package.metric_terms if term.id == metric_id)
    except (AttributeError, StopIteration) as error:
        raise ValueError(
            f"Approved Context is missing DataHub Metric Glossary Term: {metric_id}"
        ) from error


def metric_label(metric_id: str, package: Any) -> str:
    """DataHub Glossary가 소유하는 지표의 사용자 표시명을 반환한다."""
    return metric_term(metric_id, package).label


def metric_unit(metric_id: str, package: Any) -> str:
    """해결된 metric 계약의 단위를 우선하고, 없을 때만 동일 ID의 Glossary 단위를 사용한다."""
    for metric in getattr(package, "metrics", ()):
        if metric.id == metric_id and metric.unit:
            return metric.unit
    return metric_term(metric_id, package).unit


def metric_selection(assets: list[dict[str, Any]], package: Any) -> dict[str, Any]:
    """단일 지표 선택이 모든 권한 부여 asset 범위 안에 있는지 검증한다.

    asset이나 선택 지표가 없거나, 둘 이상의 지표가 선택됐거나, 명시된 entitlement 밖이면
    모델 호출 전에 ``ValueError``를 발생시킨다.
    """
    if not assets:
        raise ValueError("node3 requires entitled Context assets")
    selected = {
        str(metric.id)
        for metric in getattr(package, "metrics", ())
        if getattr(metric, "visibility", "BUSINESS") == "BUSINESS"
    }
    if len(selected) != 1:
        raise ValueError("node3 requires exactly one resolved Context metric")
    selected_metric = next(iter(selected))
    explicit_entitlements = {
        str(metric_id)
        for asset in assets
        for metric_id in asset.get("entitled_metric_ids", ())
    }
    if explicit_entitlements and selected_metric not in explicit_entitlements:
        raise ValueError("node3 selected metric is outside entitlement")
    return {
        "selected_metric_id": selected_metric,
        "context_metric_ids": [selected_metric] * len(assets),
        "entitled_metric_ids": sorted(explicit_entitlements or {selected_metric}),
    }


def serialize_context_package(payload: dict[str, Any]) -> dict[str, Any]:
    """거버넌스 컨텍스트를 provider 독립적인 표준 모델 입력으로 직렬화한다."""
    contracts = getattr(payload["package"], "runtime_contracts", None)
    if not isinstance(contracts, dict) or set(contracts) != _CONTRACT_NAMES:
        raise ValueError("Node 2 requires all six runtime Context contracts")
    return deepcopy(contracts)
