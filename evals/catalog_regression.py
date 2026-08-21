"""카탈로그에서 범용 BI 구조 조합을 생성하고 release-bound 관측을 채점한다.

이 모듈은 자연어 예문을 합성하지 않는다. 승인 후보의 Metric·asset별 Dimension·시간 mode와
Backend가 실제 구현한 capability를 교차해 Context→Plan→Guard 회귀용 단일·pairwise 구조 case를 만든다.
Node 1 자연어 정확도는 사람이 검토한 별도 Gold가 담당하며, review-only 후보는 관측값이
있더라도 점수화하지 않는다.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from statistics import median
from typing import Any

from src.data.analysis_capability_contract import (
    AnalysisCapabilityContract,
    AssetAnalysisCapability,
)
from src.data.governance_contract import canonical_sha256


CATALOG_REGRESSION_VERSION = "answervice.catalog_regression.v1"
_CANDIDATE_KEYS = {
    "contract_version",
    "state",
    "runtime_source",
    "release_id",
    "source_release_id",
    "serving_schema",
    "source_sql_sha256",
    "views",
    "dimension_families",
    "planning_contract",
    "metrics",
    "activation_gaps",
}
_RUNTIME_CAPABILITY_KEYS = {
    "version",
    "max_metrics_per_plan",
    "operations",
    "time_modes",
    "period_comparison_unsupported_aggregations",
    "ranking_tie_breaker",
}
_RUNTIME_EVIDENCE_KEYS = {
    "active_release_id",
    "candidate_sha256",
    "verified",
}
_DIRECT_METRIC_KEYS = {"id", "visibility", "asset", "column", "aggregation"}
_DERIVED_METRIC_KEYS = {"id", "visibility", "operands"}
_OPERATIONS_WITH_DIMENSION = {"breakdown", "top_n", "bottom_n"}
_RANKING_OPERATIONS = {"top_n", "bottom_n"}


class CatalogRegressionError(ValueError):
    """카탈로그 회귀 입력·case·관측이 versioned 계약을 위반했음을 나타낸다."""


def build_catalog_regression(
    candidate_value: object,
    capability: AnalysisCapabilityContract,
    runtime_capabilities_value: object,
    *,
    runtime_evidence_value: object | None = None,
) -> dict[str, Any]:
    """후보 카탈로그와 실제 Backend capability의 단일·pairwise Metric 구조 행렬을 만든다.

    반환 행렬은 질문 템플릿이나 정답 SQL을 포함하지 않는다. 각 case는 Metric, 물리 asset,
    선택 Dimension binding, 연산, 시간 mode와 현재 기술 blocker만 보존한다. 후보 승인과
    active release read-back이 모두 확인되기 전에는 ``scorable``을 열지 않는다.
    """

    candidate = _mapping(candidate_value, "semantic candidate")
    _exact_keys(candidate, _CANDIDATE_KEYS, "semantic candidate")
    runtime = _runtime_capabilities(runtime_capabilities_value)
    candidate_sha256 = canonical_sha256(candidate)
    metrics = _metric_index(candidate["metrics"])
    capabilities = {item.asset_fqn: item for item in capability.assets}
    declared_assets = {
        _text(item.get("fqn"), "candidate view fqn")
        for item in _mappings(candidate["views"], "candidate views")
    }
    if set(capabilities) != declared_assets:
        raise CatalogRegressionError(
            "analysis capability assets differ from candidate views"
        )
    if capability.max_metrics_per_plan != runtime["max_metrics_per_plan"]:
        raise CatalogRegressionError(
            "candidate and runtime max_metrics_per_plan differ"
        )

    resolved_assets = {
        metric_id: _metric_assets(metric_id, metrics, frozenset())
        for metric_id in metrics
    }
    cases: list[dict[str, Any]] = []
    for metric_id, metric in sorted(metrics.items()):
        if metric["visibility"] != "BUSINESS":
            continue
        assets = resolved_assets[metric_id]
        asset_capability = (
            capabilities.get(assets[0]) if len(assets) == 1 else None
        )
        dimensions = asset_capability.dimensions if asset_capability else ()
        time_mode = asset_capability.time_mode if asset_capability else "unresolved"
        aggregation = (
            "ratio" if "operands" in metric else str(metric["aggregation"]).casefold()
        )

        if "aggregate" in capability.operations:
            cases.append(
                _case(
                    (metric_id,),
                    assets,
                    None,
                    (),
                    "aggregate",
                    time_mode,
                    (aggregation,),
                    asset_capability,
                    runtime,
                )
            )
        for dimension in dimensions:
            for operation in sorted(
                _OPERATIONS_WITH_DIMENSION.intersection(capability.operations)
            ):
                cases.append(
                    _case(
                        (metric_id,),
                        assets,
                        dimension.id,
                        dimension.columns,
                        operation,
                        time_mode,
                        (aggregation,),
                        asset_capability,
                        runtime,
                    )
                )
        non_time_dimensions = tuple(
            item
            for item in dimensions
            if asset_capability is not None
            and asset_capability.time_field not in item.columns
        )
        if "time_trend" in capability.operations:
            for dimension in (None, *non_time_dimensions):
                cases.append(
                    _case(
                        (metric_id,),
                        assets,
                        dimension.id if dimension else None,
                        dimension.columns if dimension else (),
                        "time_trend",
                        time_mode,
                        (aggregation,),
                        asset_capability,
                        runtime,
                    )
                )
        if "period_comparison" in capability.operations:
            for dimension in (None, *non_time_dimensions):
                cases.append(
                    _case(
                        (metric_id,),
                        assets,
                        dimension.id if dimension else None,
                        dimension.columns if dimension else (),
                        "period_comparison",
                        time_mode,
                        (aggregation,),
                        asset_capability,
                        runtime,
                    )
                )

    # 최대 4개 지표 조합을 전수 생성하면 후보가 늘 때 O(n^4)로 폭증한다. 대신 모든
    # BUSINESS 지표 쌍의 aggregate 상호작용을 covering matrix로 생성해 동일 asset 실행과
    # cross-asset JOIN 부재를 빠짐없이 노출한다. 3~4개 계획의 shape는 runtime unit Gate가
    # 담당하고, pairwise로 열리지 않은 조합은 activation 시 실행할 수 없다.
    business_metric_ids = sorted(
        metric_id
        for metric_id, metric in metrics.items()
        if metric["visibility"] == "BUSINESS"
    )
    for index, left_id in enumerate(business_metric_ids):
        for right_id in business_metric_ids[index + 1 :]:
            metric_ids = (left_id, right_id)
            assets = tuple(
                sorted(
                    set(resolved_assets[left_id])
                    | set(resolved_assets[right_id])
                )
            )
            asset_capability = (
                capabilities.get(assets[0]) if len(assets) == 1 else None
            )
            time_modes = {
                capabilities[asset].time_mode
                for asset in assets
                if asset in capabilities
            }
            time_mode = next(iter(time_modes)) if len(time_modes) == 1 else "mixed"
            aggregations = tuple(
                "ratio"
                if "operands" in metrics[metric_id]
                else str(metrics[metric_id]["aggregation"]).casefold()
                for metric_id in metric_ids
            )
            cases.append(
                _case(
                    metric_ids,
                    assets,
                    None,
                    (),
                    "aggregate",
                    time_mode,
                    aggregations,
                    asset_capability,
                    runtime,
                )
            )

    cases.sort(
        key=lambda item: (
            tuple(item["metric_ids"]),
            item["operation"],
            item["dimension_id"] or "",
        )
    )
    case_ids = [str(item["case_id"]) for item in cases]
    if not cases or len(case_ids) != len(set(case_ids)):
        raise CatalogRegressionError("catalog regression case ids are empty or duplicate")

    global_blockers = _global_blockers(
        candidate,
        candidate_sha256,
        runtime_evidence_value,
    )
    structural_counts = Counter(str(item["structural_status"]) for item in cases)
    operation_counts = Counter(str(item["operation"]) for item in cases)
    metric_arity_counts = Counter(len(item["metric_ids"]) for item in cases)
    blocker_counts = Counter(
        blocker for item in cases for blocker in item["technical_blockers"]
    )
    business_count = sum(
        item["visibility"] == "BUSINESS" for item in metrics.values()
    )
    support_count = len(metrics) - business_count
    return {
        "contract_version": CATALOG_REGRESSION_VERSION,
        "candidate_sha256": candidate_sha256,
        "release_id": candidate["release_id"],
        "source_release_id": candidate["source_release_id"],
        "source_sql_sha256": candidate["source_sql_sha256"],
        "runtime_capabilities_sha256": canonical_sha256(runtime),
        "status": "SCORABLE" if not global_blockers else "REVIEW_REQUIRED",
        "scorable": not global_blockers,
        "global_blockers": global_blockers,
        "business_metric_count": business_count,
        "support_metric_count": support_count,
        "case_count": len(cases),
        "case_content_sha256": canonical_sha256(cases),
        "summary": {
            "structural_status_counts": dict(sorted(structural_counts.items())),
            "operation_counts": dict(sorted(operation_counts.items())),
            "metric_arity_counts": {
                str(key): value for key, value in sorted(metric_arity_counts.items())
            },
            "technical_blocker_counts": dict(sorted(blocker_counts.items())),
        },
        "cases": cases,
    }


def evaluate_catalog_observations(
    regression_value: object,
    observations: Iterable[object],
    *,
    repeat: int,
) -> dict[str, Any]:
    """활성 release의 반복 관측을 구조 case 기대값과 exact 비교해 회귀율을 계산한다.

    review-only 또는 live read-back이 없는 행렬은 관측 파일이 있더라도 점수화하지 않는다.
    각 case의 모든 반복이 기대 projection과 같아야 통과하며 출력 hash가 같아야 결정적이다.
    """

    regression = _mapping(regression_value, "catalog regression")
    if regression.get("scorable") is not True:
        raise CatalogRegressionError(
            "review-only or unverified catalog regression cannot be scored"
        )
    if not isinstance(repeat, int) or isinstance(repeat, bool) or repeat < 1:
        raise CatalogRegressionError("repeat must be a positive integer")
    case_values = regression.get("cases")
    if not isinstance(case_values, list) or not case_values:
        raise CatalogRegressionError("catalog regression cases are missing")
    case_index = {
        _text(item.get("case_id"), "catalog case id"): item
        for item in _mappings(case_values, "catalog cases")
    }
    if len(case_index) != len(case_values):
        raise CatalogRegressionError("catalog case ids are duplicate")
    rows: dict[str, list[Mapping[str, Any]]] = {
        case_id: [] for case_id in case_index
    }
    for value in observations:
        row = _mapping(value, "catalog observation")
        _exact_keys(
            row,
            {"case_id", "attempt", "latency_ms", "output"},
            "catalog observation",
        )
        case_id = _text(row["case_id"], "catalog observation case_id")
        if case_id not in rows:
            raise CatalogRegressionError(
                "catalog observation references an unknown case"
            )
        attempt = row["attempt"]
        latency = row["latency_ms"]
        if (
            not isinstance(attempt, int)
            or isinstance(attempt, bool)
            or not isinstance(latency, (int, float))
            or isinstance(latency, bool)
            or latency < 0
        ):
            raise CatalogRegressionError(
                "catalog observation attempt or latency is invalid"
            )
        rows[case_id].append(row)

    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    for case_id, case in case_index.items():
        observed = sorted(rows[case_id], key=lambda item: item["attempt"])
        if [item["attempt"] for item in observed] != list(range(1, repeat + 1)):
            raise CatalogRegressionError(
                "every catalog case requires exactly one observation per repeat"
            )
        outputs = [_mapping(item["output"], "catalog output") for item in observed]
        matches = [dict(item) == case["expected"] for item in outputs]
        hashes = [canonical_sha256(item) for item in outputs]
        latencies.extend(float(item["latency_ms"]) for item in observed)
        results.append(
            {
                "case_id": case_id,
                "operation": case["operation"],
                "passed": all(matches),
                "deterministic": len(set(hashes)) == 1,
                "attempts": repeat,
            }
        )
    ordered = sorted(latencies)
    by_operation = {
        operation: _accuracy(
            [item for item in results if item["operation"] == operation]
        )
        for operation in sorted({str(item["operation"]) for item in results})
    }
    return {
        "contract_version": CATALOG_REGRESSION_VERSION,
        "case_content_sha256": regression["case_content_sha256"],
        "repeat": repeat,
        "total": len(results),
        "passed": sum(bool(item["passed"]) for item in results),
        "deterministic": sum(bool(item["deterministic"]) for item in results),
        "accuracy": _accuracy(results),
        "operation_accuracy": by_operation,
        "p50_ms": median(ordered),
        "p95_ms": ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)],
        "results": results,
    }


def _case(
    metric_ids: tuple[str, ...],
    assets: tuple[str, ...],
    dimension_id: str | None,
    dimension_columns: tuple[str, ...],
    operation: str,
    time_mode: str,
    aggregations: tuple[str, ...],
    asset_capability: AssetAnalysisCapability | None,
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    """하나의 구조 조합을 안정 ID·기술 blocker·기대 관측 projection으로 만든다."""

    blockers: list[str] = []
    if len(assets) != 1 or asset_capability is None:
        blockers.append("JOIN_GRAPH_REQUIRED")
    if operation not in runtime["operations"]:
        blockers.append("OPERATION_NOT_IMPLEMENTED")
    if time_mode not in runtime["time_modes"]:
        blockers.append("TIME_MODE_NOT_IMPLEMENTED")
    if operation == "time_trend":
        if time_mode != "range":
            blockers.append("TIME_TREND_REQUIRES_RANGE")
        # 현재 sidecar는 time field만 선언하며 질문의 일·주·월 grain 허용 범위를 승인하지 않았다.
        blockers.append("TIME_GRAIN_CONTRACT_REQUIRED")
    if operation == "period_comparison":
        if time_mode != "range":
            blockers.append("PERIOD_COMPARISON_REQUIRES_RANGE")
        blockers.append("COMPARISON_WINDOW_CONTRACT_REQUIRED")
        if any(
            aggregation in runtime["period_comparison_unsupported_aggregations"]
            for aggregation in aggregations
        ):
            blockers.append("PERIOD_COMPARISON_AGGREGATION_UNSUPPORTED")
    if operation in _RANKING_OPERATIONS and (
        runtime["ranking_tie_breaker"] != "all_dimensions_ascending"
    ):
        blockers.append("RANKING_TIE_BREAKER_NOT_IMPLEMENTED")
    blockers = list(dict.fromkeys(blockers))
    identity = {
        "metric_ids": list(metric_ids),
        "asset_fqns": list(assets),
        "dimension_id": dimension_id,
        "dimension_columns": list(dimension_columns),
        "operation": operation,
        "time_mode": time_mode,
        "result_limit": 10 if operation in _RANKING_OPERATIONS else None,
    }
    expected = {
        **identity,
        "outcome": "ALLOW" if not blockers else "BLOCK",
        "blocker_codes": blockers,
    }
    return {
        "case_id": "CAT-" + canonical_sha256(identity)[:20].upper(),
        **identity,
        "structural_status": "READY" if not blockers else "BLOCKED",
        "technical_blockers": blockers,
        "expected": expected,
    }


def _metric_index(value: object) -> dict[str, Mapping[str, Any]]:
    """Metric 후보를 direct·derived exact shape와 dependency graph에 맞춰 인덱싱한다."""

    metrics: dict[str, Mapping[str, Any]] = {}
    for metric in _mappings(value, "candidate metrics"):
        keys = set(metric)
        if keys != _DIRECT_METRIC_KEYS and keys != _DERIVED_METRIC_KEYS:
            raise CatalogRegressionError("candidate metric fields are invalid")
        metric_id = _text(metric["id"], "candidate metric id")
        if metric_id in metrics or metric["visibility"] not in {"BUSINESS", "SUPPORT"}:
            raise CatalogRegressionError(
                "candidate metric id or visibility is invalid"
            )
        if keys == _DIRECT_METRIC_KEYS:
            _text(metric["asset"], "candidate metric asset")
            _text(metric["column"], "candidate metric column")
            _text(metric["aggregation"], "candidate metric aggregation")
        else:
            operands = metric["operands"]
            if (
                not isinstance(operands, list)
                or len(operands) != 2
                or any(not isinstance(item, str) or not item for item in operands)
                or len(set(operands)) != 2
            ):
                raise CatalogRegressionError(
                    "derived candidate metric requires two unique operands"
                )
        metrics[metric_id] = metric
    if not metrics:
        raise CatalogRegressionError("candidate metrics are empty")
    for metric in metrics.values():
        if "operands" in metric and any(
            operand not in metrics for operand in metric["operands"]
        ):
            raise CatalogRegressionError("candidate metric operand is missing")
    return metrics


def _metric_assets(
    metric_id: str,
    metrics: Mapping[str, Mapping[str, Any]],
    visiting: frozenset[str],
) -> tuple[str, ...]:
    """derived dependency를 순환 없이 따라가 Metric의 물리 asset 집합을 반환한다."""

    if metric_id in visiting:
        raise CatalogRegressionError("candidate metric dependency is cyclic")
    metric = metrics[metric_id]
    if "asset" in metric:
        return (str(metric["asset"]),)
    assets = {
        asset
        for operand in metric["operands"]
        for asset in _metric_assets(
            str(operand),
            metrics,
            visiting | {metric_id},
        )
    }
    return tuple(sorted(assets))


def _runtime_capabilities(value: object) -> Mapping[str, Any]:
    """Backend capability snapshot을 exact key·typed collection으로 검증한다."""

    runtime = _mapping(value, "runtime analysis capabilities")
    _exact_keys(runtime, _RUNTIME_CAPABILITY_KEYS, "runtime analysis capabilities")
    _text(runtime["version"], "runtime capability version")
    maximum = runtime["max_metrics_per_plan"]
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
        raise CatalogRegressionError("runtime max_metrics_per_plan is invalid")
    for name in (
        "operations",
        "time_modes",
        "period_comparison_unsupported_aggregations",
    ):
        values = runtime[name]
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(item, str) or not item for item in values)
            or len(values) != len(set(values))
        ):
            raise CatalogRegressionError(f"runtime capability {name} is invalid")
    _text(runtime["ranking_tie_breaker"], "runtime ranking tie breaker")
    return runtime


def _global_blockers(
    candidate: Mapping[str, Any],
    candidate_sha256: str,
    runtime_evidence_value: object | None,
) -> list[str]:
    """업무 승인·runtime source·live active release 증거의 전역 Gate를 반환한다."""

    blockers = []
    if candidate.get("state") != "APPROVED":
        blockers.append("SEMANTIC_APPROVAL_REQUIRED")
    if candidate.get("runtime_source") is not True:
        blockers.append("RUNTIME_SOURCE_DISABLED")
    if runtime_evidence_value is None:
        blockers.append("ACTIVE_RELEASE_READBACK_REQUIRED")
        return blockers
    evidence = _mapping(runtime_evidence_value, "runtime evidence")
    _exact_keys(evidence, _RUNTIME_EVIDENCE_KEYS, "runtime evidence")
    if (
        evidence.get("verified") is not True
        or evidence.get("active_release_id") != candidate.get("release_id")
        or evidence.get("candidate_sha256") != candidate_sha256
    ):
        blockers.append("ACTIVE_RELEASE_READBACK_MISMATCH")
    return blockers


def _mappings(value: object, context: str) -> tuple[Mapping[str, Any], ...]:
    """배열의 모든 항목을 Mapping으로 검증해 순서를 보존한다."""

    if not isinstance(value, list):
        raise CatalogRegressionError(f"{context} must be an array")
    return tuple(_mapping(item, context) for item in value)


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    """입력 하나가 Mapping인지 확인한다."""

    if not isinstance(value, Mapping):
        raise CatalogRegressionError(f"{context} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    """versioned 객체가 누락·추가 필드 없이 exact shape인지 확인한다."""

    if set(value) != expected:
        raise CatalogRegressionError(f"{context} fields do not match the contract")


def _text(value: object, context: str) -> str:
    """필수 문자열을 공백이 아닌 값으로 검증한다."""

    if not isinstance(value, str) or not value.strip():
        raise CatalogRegressionError(f"{context} must be non-empty text")
    return value


def _accuracy(rows: list[Mapping[str, Any]]) -> float:
    """비어 있지 않은 결과 집합의 통과 비율을 여섯 자리로 계산한다."""

    if not rows:
        raise CatalogRegressionError("accuracy requires at least one result")
    return round(sum(bool(item["passed"]) for item in rows) / len(rows), 6)
