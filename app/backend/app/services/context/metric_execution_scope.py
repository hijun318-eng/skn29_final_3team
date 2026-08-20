"""공개 Metric 선택을 숨은 operand 및 Metric별 join 실행 범위로 확장한다."""

from __future__ import annotations

from typing import Any

from app.services.context.builder import ContextBuildError, ContextBuildErrorCode
from app.services.context.values import RATIO_ZERO_POLICIES
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V2


def ratio_reference(
    metric_terms: dict[str, dict[str, object]],
    executable_metrics: dict[str, dict[str, object]],
    metric_id: str,
) -> dict[str, str] | None:
    """공개 ratio Term의 두 operand가 실행 registry의 column Metric인지 검증한다."""

    term = metric_terms[metric_id]
    if term.get("kind") != "ratio":
        return None
    numerator_id = term.get("numerator_metric_id")
    denominator_id = term.get("denominator_metric_id")
    zero_policy = term.get("zero_policy")
    numerator = executable_metrics.get(str(numerator_id))
    denominator = executable_metrics.get(str(denominator_id))
    if (
        not isinstance(numerator_id, str)
        or not isinstance(denominator_id, str)
        or numerator_id == denominator_id
        or numerator is None
        or denominator is None
        or str(numerator.get("aggregation", "")).casefold() == "ratio"
        or str(denominator.get("aggregation", "")).casefold() == "ratio"
        or not isinstance(zero_policy, str)
        or zero_policy not in RATIO_ZERO_POLICIES
    ):
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "Ratio metric term의 분자·분모 참조가 승인된 실행 metric을 가리키지 않습니다.",
        )
    return {
        "numerator_metric_id": numerator_id,
        "denominator_metric_id": denominator_id,
        "zero_policy": zero_policy,
    }


def synthetic_ratio_metric(
    metric_id: str,
    term: dict[str, object],
    ratio: dict[str, str],
    published: dict[str, object],
) -> dict[str, object]:
    """Glossary identity와 발행 runtime 정책을 결합한 canonical ratio 실행 항목을 만든다."""

    policy_fields = {
        key: published[key]
        for key in (
            "visibility",
            "governance_version",
            "allowed_roles",
            "contains_pii",
            "allowed_join_ids",
            "join_required",
            "query_strategies",
        )
        if key in published
    }
    return {
        "id": metric_id,
        "asset_fqn": "",
        "field": "",
        "aggregation": "ratio",
        "time_field": "",
        "required_filters": [],
        "result_field": str(published.get("result_field") or metric_id),
        "unit": str(term.get("unit") or published.get("unit") or ""),
        "reduction": "ratio",
        "numerator_metric_id": ratio["numerator_metric_id"],
        "denominator_metric_id": ratio["denominator_metric_id"],
        "zero_policy": ratio["zero_policy"],
        **policy_fields,
    }


def select_assets_for_metrics(
    assets: list[dict[str, object]],
    keep_ids: set[str],
    synthetic: dict[str, object] | None,
) -> list[dict[str, object]]:
    """선택 Metric과 operand만 남기고 v2 Metric이 허용한 join edge 밖을 제거한다."""

    selected_assets: list[dict[str, object]] = []
    injected = False
    for asset in assets:
        item = dict(asset)
        if "metrics" in item:
            kept = tuple(
                metric
                for metric in item.get("metrics", ())
                if isinstance(metric, dict) and metric.get("id") in keep_ids
            )
            if synthetic is not None:
                kept = tuple(
                    metric for metric in kept if metric.get("id") != synthetic["id"]
                )
            if (
                synthetic is not None
                and not injected
                and any(
                    metric.get("id") == synthetic["numerator_metric_id"]
                    for metric in kept
                )
            ):
                kept = kept + (synthetic,)
                injected = True
            item["metrics"] = kept
            item["entitled_metric_ids"] = sorted(
                str(metric["id"])
                for metric in kept
                if metric.get("visibility", "BUSINESS") == "BUSINESS"
            )
        selected_assets.append(item)
    if synthetic is not None and not injected:
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "Ratio metric의 분자 metric이 승인된 asset에서 발견되지 않았습니다.",
        )
    selected_assets = _restrict_v2_joins(selected_assets)
    if not any(asset.get("join_ids") for asset in selected_assets):
        selected_assets = [asset for asset in selected_assets if asset.get("metrics")]
    return selected_assets


def _restrict_v2_joins(
    assets: list[dict[str, object]],
) -> list[dict[str, object]]:
    metrics = [
        metric
        for asset in assets
        for metric in asset.get("metrics", ())
        if isinstance(metric, dict)
    ]
    versions = {
        str(metric.get("governance_version") or "") for metric in metrics
    }
    if versions != {RUNTIME_GOVERNANCE_VERSION_V2}:
        raise ContextBuildError(
            ContextBuildErrorCode.GOVERNANCE_VERSION_UNSUPPORTED,
            "Production 분석에는 단일 v2 runtime governance release가 필요합니다.",
        )
    scopes = {
        tuple(sorted(map(str, metric.get("allowed_join_ids", ()))))
        for metric in metrics
    }
    if len(scopes) != 1:
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "선택 Metric들의 허용 join 범위가 서로 다릅니다.",
        )
    allowed = set(next(iter(scopes), ()))
    join_required = any(metric.get("join_required") is True for metric in metrics)
    retained_ids: set[str] = set()
    result = []
    for asset in assets:
        item = dict(asset)
        join_ids = [
            str(edge_id)
            for edge_id in asset.get("join_ids", ())
            if str(edge_id) in allowed
        ]
        retained_ids.update(join_ids)
        item["join_ids"] = join_ids
        graph = item.get("join_graph")
        if isinstance(graph, dict) and isinstance(graph.get("edges"), list):
            item["join_graph"] = {
                "edges": [
                    edge
                    for edge in graph["edges"]
                    if isinstance(edge, dict) and str(edge.get("id")) in allowed
                ]
            }
        result.append(item)
    if join_required and not retained_ids:
        raise ContextBuildError(
            ContextBuildErrorCode.INVALID_METRIC,
            "Metric이 요구한 승인 join edge가 선택된 asset graph에 없습니다.",
        )
    return result
