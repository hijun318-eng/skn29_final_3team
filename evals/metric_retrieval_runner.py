"""Active DataHub release의 검색 자기일관성과 후보 fail-closed Gate를 실행한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.datahub_catalog import (  # noqa: E402
    DataHubCatalogClient,
    DataHubCatalogError,
)
from app.adapters.query_governance import (  # noqa: E402
    QueryGovernanceEngine,
    SEARCH_MODES,
)
from app.adapters.datahub_query_plan import plan_search_queries  # noqa: E402
from app.authorization import role_is_entitled  # noqa: E402
from app.ports.data_platform import (  # noqa: E402
    MetadataUnavailableError,
    NoEntitledAssetsError,
    NoMetricMatchError,
    UnsupportedSemanticError,
)
from evals.metric_retrieval import (  # noqa: E402
    MetricRetrievalError,
    MetricRetrievalObservation,
    MetricRetrievalProbe,
    build_metric_retrieval_probes,
    evaluate_metric_retrieval,
    load_metric_retrieval_gold,
)


PHASE2A_CONTRACT_VERSION = "answervice.metric_retrieval_phase2a.v2"


class _RejectSchemaInspection:
    """후보 retrieval Gate가 Trino schema를 조회하면 즉시 실패시키는 sentinel이다."""

    async def verify(self, _datasets: object) -> None:
        """후보 단계의 Trino 접근을 성공으로 위장하지 않는다."""

        raise MetricRetrievalError(
            "metric retrieval candidate search must not inspect Trino schema"
        )


async def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    """active release에서 probe를 만들고 실제 후보 API 관측과 threshold 판정을 반환한다."""

    if arguments.phase2a_gold_manifest is not None:
        return await _run_phase2a(arguments)

    catalog = DataHubCatalogClient.from_env()
    engine = QueryGovernanceEngine(
        catalog,
        _RejectSchemaInspection(),
        expected_context_release=arguments.expected_context_release,
        max_candidate_metrics=arguments.max_candidates,
        candidate_search_count=arguments.candidate_search_count,
        search_mode=arguments.search_mode,
    )
    context = {
        "role": arguments.role,
        "domains": arguments.domain,
        "parameters": {},
    }
    try:
        snapshot = await engine._loader.load()
        release = engine._active_release(snapshot)
        datasets = engine._datasets_for_release(snapshot, release)
        terms = engine._required_terms(snapshot, datasets)
        eligible_ids = _eligible_metric_ids(release, datasets, context)
        projected_assets = engine._project_assets(
            tuple(item for item in datasets if item.entitled(context)),
            release.joins,
            terms,
            context,
            candidate=True,
        )
        forbidden_ids = set(terms).difference(eligible_ids)
        probes = build_metric_retrieval_probes(
            {metric_id: term.as_dict() for metric_id, term in terms.items()},
            eligible_ids,
            support_phrases=_support_phrases(projected_assets),
            dimension_phrases=_dimension_phrases(release, datasets, context),
            forbidden_terms={
                metric_id: terms[metric_id].as_dict()
                for metric_id in sorted(forbidden_ids)
            },
            out_of_scope_query=f"unmatched_{release.canonical_checksum}",
        )
        observations: list[MetricRetrievalObservation] = []
        latency_ms: list[float] = []
        planned_datahub_requests = 0
        for probe in probes:
            planned_datahub_requests += _planned_datahub_requests(
                engine,
                snapshot,
                terms,
                probe.query,
                arguments.search_mode,
            )
            started = time.perf_counter()
            try:
                candidates = await engine.search_asset_candidates(probe.query, context)
                ranked_ids = _ranked_business_ids(candidates.assets)
                observations.append(
                    MetricRetrievalObservation(probe.query, ranked_ids)
                )
            except (
                MetadataUnavailableError,
                NoEntitledAssetsError,
                NoMetricMatchError,
                UnsupportedSemanticError,
            ) as error:
                observations.append(
                    MetricRetrievalObservation(
                        probe.query,
                        (),
                        type(error).__name__,
                    )
                )
            finally:
                latency_ms.append((time.perf_counter() - started) * 1000)
        await engine._drain_shadow_tasks()
        result = evaluate_metric_retrieval(
            probes,
            observations,
            top_k=arguments.top_k,
            max_candidates=arguments.max_candidates,
        )
    finally:
        await catalog.aclose()

    exact = result["catalog_exact_self_consistency"]
    definition = result["definition_overlap_retrieval"]
    negative = result["negative_closure"]
    passed = bool(
        exact["scorable"]
        and exact["top1_accuracy"] >= arguments.min_catalog_exact_top1
        and exact["retrieval_error_count"] == 0
        and definition["scorable"]
        and definition["top1_accuracy"] >= arguments.min_definition_top1
        and definition["recall_at_k"] >= arguments.min_definition_recall_at_k
        and definition["retrieval_error_count"] == 0
        and negative["closure_rate"] >= arguments.min_negative_closure
        and negative["contamination_rate"] <= arguments.max_negative_contamination
        and negative["infrastructure_error_count"] == 0
    )
    result.update(
        {
            "status": "PASSED" if passed else "FAILED",
            "context_release": release.catalog_version,
            "catalog_checksum": release.catalog_checksum,
            "canonical_checksum": release.canonical_checksum,
            "principal": {
                "role": arguments.role,
                "domains": sorted(arguments.domain),
            },
            "search_mode": arguments.search_mode,
            "warm_candidate_latency_ms": {
                "sample_count": len(latency_ms),
                "p50": _percentile(latency_ms, 0.50),
                "p95": _percentile(latency_ms, 0.95),
                "max": round(max(latency_ms), 3),
            },
            "planned_datahub_request_count": planned_datahub_requests,
            "planned_datahub_requests_per_probe": round(
                planned_datahub_requests / len(probes), 6
            ),
            "thresholds": {
                "min_catalog_exact_top1": arguments.min_catalog_exact_top1,
                "min_definition_top1": arguments.min_definition_top1,
                "min_definition_recall_at_k": arguments.min_definition_recall_at_k,
                "min_negative_closure": arguments.min_negative_closure,
                "max_negative_contamination": arguments.max_negative_contamination,
            },
        }
    )
    if not arguments.include_cases:
        result.pop("cases", None)
    return result


async def _run_phase2a(arguments: argparse.Namespace) -> dict[str, Any]:
    """동일 release에서 baseline·shadow production·DataHub 후보를 한 번에 비교한다."""

    gold = load_metric_retrieval_gold(arguments.phase2a_gold_manifest)
    catalog = DataHubCatalogClient.from_env()
    engines = {
        mode: QueryGovernanceEngine(
            catalog,
            _RejectSchemaInspection(),
            expected_context_release=arguments.expected_context_release,
            max_candidate_metrics=arguments.max_candidates,
            candidate_search_count=arguments.candidate_search_count,
            search_mode=mode,
        )
        for mode in ("lexical", "lexical_shadow", "datahub_lexical")
    }
    context = {
        "role": arguments.role,
        "domains": arguments.domain,
        "parameters": {},
    }
    try:
        prepared: dict[str, tuple[object, object, dict[str, object]]] = {}
        receipts: set[tuple[str, str, str]] = set()
        for mode, engine in engines.items():
            snapshot = await engine._loader.load()
            release = engine._active_release(snapshot)
            datasets = engine._datasets_for_release(snapshot, release)
            terms = engine._required_terms(snapshot, datasets)
            prepared[mode] = (snapshot, release, terms)
            receipts.add(
                (
                    release.catalog_version,
                    release.catalog_checksum,
                    release.canonical_checksum,
                )
            )
        if len(receipts) != 1:
            raise MetricRetrievalError("retrieval comparison observed mixed releases")

        baseline_snapshot, release, baseline_terms = prepared["lexical"]
        datasets = engines["lexical"]._datasets_for_release(
            baseline_snapshot,
            release,
        )
        eligible_ids = _eligible_metric_ids(release, datasets, context)
        projected_assets = engines["lexical"]._project_assets(
            tuple(item for item in datasets if item.entitled(context)),
            release.joins,
            baseline_terms,
            context,
            candidate=True,
        )
        forbidden_ids = set(baseline_terms).difference(eligible_ids)
        catalog_probes = build_metric_retrieval_probes(
            {
                metric_id: term.as_dict()
                for metric_id, term in baseline_terms.items()
            },
            eligible_ids,
            support_phrases=_support_phrases(projected_assets),
            dimension_phrases=_dimension_phrases(release, datasets, context),
            forbidden_terms={
                metric_id: baseline_terms[metric_id].as_dict()
                for metric_id in sorted(forbidden_ids)
            },
            out_of_scope_query=f"unmatched_{release.canonical_checksum}",
        )
        if any(
            set(probe.expected_metric_ids).difference(eligible_ids)
            for probe in gold.probes
        ):
            raise MetricRetrievalError(
                "retrieval Gold expects a metric outside the requested entitlement"
            )
        probes = (*catalog_probes, *gold.probes)
        if len({probe.normalized_query for probe in probes}) != len(probes):
            raise MetricRetrievalError(
                "catalog and independent Gold contain an overlapping query"
            )

        measurements: dict[str, dict[str, Any]] = {}
        raw_observations: dict[str, tuple[MetricRetrievalObservation, ...]] = {}
        latency_by_mode: dict[str, list[float]] = {}
        request_counts: dict[str, int] = {}
        for mode, engine in engines.items():
            snapshot, _prepared_release, terms = prepared[mode]
            observations, latency, requests = await _observe(
                engine,
                probes,
                context,
                snapshot,
                terms,
                mode,
            )
            raw_observations[mode] = observations
            latency_by_mode[mode] = latency
            request_counts[mode] = requests
            measurements[mode] = evaluate_metric_retrieval(
                probes,
                observations,
                top_k=arguments.top_k,
                max_candidates=arguments.max_candidates,
            )
    finally:
        for engine in engines.values():
            await engine.aclose()
        await catalog.aclose()

    production_diff_count = sum(
        baseline != shadow
        for baseline, shadow in zip(
            raw_observations["lexical"],
            raw_observations["lexical_shadow"],
            strict=True,
        )
    )
    eligible = set(eligible_ids)
    unauthorized_exposure_count = sum(
        metric_id not in eligible
        for observations in raw_observations.values()
        for observation in observations
        for metric_id in observation.ranked_metric_ids
    )
    candidate_infrastructure_error_count = sum(
        observation.error_type == "MetadataUnavailableError"
        for observation in raw_observations["datahub_lexical"]
    )
    candidate_probe_count = len(raw_observations["datahub_lexical"])
    candidate_failed_probe_rate = round(
        candidate_infrastructure_error_count / candidate_probe_count,
        6,
    )
    active_release_search_coverage = float(
        measurements["datahub_lexical"]["catalog_exact_self_consistency"][
            "recall_at_k"
        ]
    )
    candidate_latency = latency_by_mode["datahub_lexical"]
    candidate_p95 = _percentile(candidate_latency, 0.95)
    thresholds = gold.thresholds
    checks = {
        **_phase2a_quality_checks(measurements, arguments, thresholds),
        "production_non_regression": production_diff_count
        <= thresholds["max_production_diff_count"],
        "unauthorized_metadata_exposure": unauthorized_exposure_count
        <= thresholds["max_unauthorized_exposure_count"],
        "active_release_search_freshness": active_release_search_coverage
        >= thresholds["min_active_release_search_coverage"],
        "candidate_failure_bound": candidate_failed_probe_rate
        <= thresholds["max_candidate_failed_probe_rate"],
        "candidate_latency_bound": candidate_p95
        <= thresholds["max_candidate_warm_p95_ms"],
    }
    decision = _phase2a_decision(checks)
    passed = decision == "PROMOTE"
    for result in measurements.values():
        if not arguments.include_cases:
            result.pop("cases", None)
    return {
        "contract_version": PHASE2A_CONTRACT_VERSION,
        "status": "PASSED" if passed else "FAILED",
        "decision": decision,
        "decision_reasons": sorted(
            name for name, succeeded in checks.items() if not succeeded
        ),
        "gate": "2A",
        "context_release": release.catalog_version,
        "catalog_checksum": release.catalog_checksum,
        "canonical_checksum": release.canonical_checksum,
        "principal": {
            "role": arguments.role,
            "domains": sorted(arguments.domain),
        },
        "gold_manifest": {
            "dataset_id": gold.dataset_id,
            "sealed_at": gold.sealed_at,
            "content_sha256": gold.content_sha256,
            "probe_count": len(gold.probes),
        },
        "measurements": measurements,
        "warm_candidate_latency_ms": {
            mode: {
                "sample_count": len(values),
                "p50": _percentile(values, 0.50),
                "p95": _percentile(values, 0.95),
                "max": round(max(values), 3),
            }
            for mode, values in latency_by_mode.items()
        },
        "planned_datahub_request_count": request_counts,
        "candidate_search_count": arguments.candidate_search_count,
        "production_diff_count": production_diff_count,
        "unauthorized_exposure_count": unauthorized_exposure_count,
        "candidate_infrastructure_error_count": candidate_infrastructure_error_count,
        "search_reliability": {
            "freshness_basis": "active_release_catalog_exact_recall_at_k",
            "active_release_coverage": active_release_search_coverage,
            "candidate_probe_count": candidate_probe_count,
            "failed_probe_count": candidate_infrastructure_error_count,
            "failed_probe_rate": candidate_failed_probe_rate,
        },
        "thresholds": dict(thresholds),
        "checks": checks,
    }


def _phase2a_quality_checks(
    measurements: dict[str, dict[str, Any]],
    arguments: argparse.Namespace,
    thresholds: Mapping[str, float | int],
) -> dict[str, bool]:
    """baseline과 실제 후보 경로에 같은 catalog·heldout 품질 하한을 적용한다."""

    def catalog_contract(measurement: dict[str, Any]) -> bool:
        exact = measurement["catalog_exact_self_consistency"]
        definition = measurement["definition_overlap_retrieval"]
        negative = measurement["negative_closure"]
        return bool(
            exact["scorable"]
            and exact["top1_accuracy"] >= arguments.min_catalog_exact_top1
            and exact["retrieval_error_count"] == 0
            and definition["scorable"]
            and definition["top1_accuracy"] >= arguments.min_definition_top1
            and definition["recall_at_k"]
            >= arguments.min_definition_recall_at_k
            and definition["retrieval_error_count"] == 0
            and negative["closure_rate"] >= arguments.min_negative_closure
            and negative["contamination_rate"]
            <= arguments.max_negative_contamination
            and negative["infrastructure_error_count"] == 0
        )

    def heldout_quality(measurement: dict[str, Any]) -> bool:
        heldout = measurement["natural_language_paraphrase"]
        return bool(
            heldout["scorable"]
            and heldout["top1_accuracy"]
            >= thresholds["min_baseline_heldout_top1"]
            and heldout["recall_at_k"]
            >= thresholds["min_baseline_heldout_recall_at_k"]
            and heldout["mean_reciprocal_rank"]
            >= thresholds["min_baseline_heldout_mrr"]
            and heldout["retrieval_error_count"] == 0
            and heldout["negative_closure"]["scorable"]
            and heldout["negative_closure"]["closure_rate"] == 1.0
            and heldout["negative_closure"]["infrastructure_error_count"] == 0
        )

    baseline = measurements["lexical"]
    candidate = measurements["datahub_lexical"]
    return {
        "catalog_baseline_contract": catalog_contract(baseline),
        "baseline_heldout_quality": heldout_quality(baseline),
        "candidate_catalog_contract": catalog_contract(candidate),
        "candidate_heldout_quality": heldout_quality(candidate),
    }


def _phase2a_decision(checks: Mapping[str, bool]) -> str:
    """품질·보안 결함과 관측 불충분을 구분해 전환 결정을 반환한다."""

    required = {
        "catalog_baseline_contract",
        "baseline_heldout_quality",
        "candidate_catalog_contract",
        "candidate_heldout_quality",
        "production_non_regression",
        "unauthorized_metadata_exposure",
        "active_release_search_freshness",
        "candidate_failure_bound",
        "candidate_latency_bound",
    }
    if set(checks) != required or any(
        type(value) is not bool for value in checks.values()
    ):
        raise MetricRetrievalError("Phase 2A decision checks are invalid")
    failed = {name for name, succeeded in checks.items() if not succeeded}
    if not failed:
        return "PROMOTE"
    if failed.intersection(
        {"production_non_regression", "unauthorized_metadata_exposure"}
    ):
        return "REJECT"
    if failed.intersection(
        {
            "catalog_baseline_contract",
            "baseline_heldout_quality",
            "active_release_search_freshness",
            "candidate_failure_bound",
            "candidate_latency_bound",
        }
    ):
        return "HOLD"
    return "REJECT"


async def _observe(
    engine: QueryGovernanceEngine,
    probes: tuple[MetricRetrievalProbe, ...],
    context: dict[str, object],
    snapshot: object,
    terms: dict[str, object],
    mode: str,
) -> tuple[tuple[MetricRetrievalObservation, ...], list[float], int]:
    """한 mode를 순서 고정 probe로 관측하고 shadow task까지 bounded drain한다."""

    observations: list[MetricRetrievalObservation] = []
    latency_ms: list[float] = []
    planned_requests = 0
    for probe in probes:
        planned_requests += _planned_datahub_requests(
            engine,
            snapshot,
            terms,
            probe.query,
            mode,
        )
        started = time.perf_counter()
        try:
            candidates = await engine.search_asset_candidates(probe.query, context)
            observations.append(
                MetricRetrievalObservation(
                    probe.query,
                    _ranked_business_ids(candidates.assets),
                )
            )
        except (
            MetadataUnavailableError,
            NoEntitledAssetsError,
            NoMetricMatchError,
            UnsupportedSemanticError,
        ) as error:
            observations.append(
                MetricRetrievalObservation(probe.query, (), type(error).__name__)
            )
        finally:
            latency_ms.append((time.perf_counter() - started) * 1000)
        if mode == "lexical_shadow":
            await engine._drain_shadow_tasks()
    return tuple(observations), latency_ms, planned_requests


def _eligible_metric_ids(release: object, datasets: tuple[object, ...], context: dict[str, object]) -> tuple[str, ...]:
    """node·Metric role·PII 계약을 모두 만족하는 BUSINESS Metric만 probe 대상으로 고른다."""

    by_fqn = {str(item.fqn): item for item in datasets}
    role = str(context["role"])
    result = []
    for metric in release.metrics:
        if (
            metric.visibility == "BUSINESS"
            and metric.contains_pii is False
            and role_is_entitled(role, metric.allowed_roles)
            and set(metric.source_assets).issubset(by_fqn)
            and all(by_fqn[fqn].entitled(context) for fqn in metric.source_assets)
        ):
            result.append(metric.id)
    if not result:
        raise MetricRetrievalError(
            "active release has no BUSINESS Metric for the requested principal"
        )
    return tuple(sorted(result))


def _support_phrases(assets: list[dict[str, Any]]) -> tuple[str, ...]:
    """현재 principal에게 보이는 SUPPORT semantic 이름·별칭만 closure probe로 투영한다."""

    phrases: list[str] = []
    for asset in assets:
        for metric in asset.get("metrics", ()):
            if not isinstance(metric, dict) or metric.get("visibility") != "SUPPORT":
                continue
            semantic = metric.get("semantic")
            if not isinstance(semantic, dict):
                continue
            name = semantic.get("name")
            aliases = semantic.get("aliases")
            if isinstance(name, str) and name.strip():
                phrases.append(name.strip())
            if isinstance(aliases, (list, tuple)):
                phrases.extend(
                    item.strip()
                    for item in aliases
                    if isinstance(item, str) and item.strip()
                )
    return tuple(dict.fromkeys(phrases))


def _dimension_phrases(
    release: object,
    datasets: tuple[object, ...],
    context: dict[str, object],
) -> tuple[str, ...]:
    """권한 있는 asset의 Dimension 별칭만 지표 없는 closure probe로 투영한다."""

    entitled_fqns = {item.fqn for item in datasets if item.entitled(context)}
    phrases = [
        alias
        for dimension in release.dimensions
        if dimension.asset_fqn in entitled_fqns
        for alias in dimension.aliases
    ]
    return tuple(dict.fromkeys(phrases))


def _ranked_business_ids(assets: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    """후보 payload의 전역 양의 rank를 중복·공백 없이 BUSINESS Metric 순서로 복원한다."""

    rows: list[tuple[int, str]] = []
    for asset in assets:
        for metric in asset.get("metrics", ()):
            if (
                not isinstance(metric, dict)
                or metric.get("visibility", "BUSINESS") != "BUSINESS"
                or metric.get("candidate_selectable") is not True
            ):
                continue
            rank = metric.get("candidate_rank")
            metric_id = metric.get("id")
            if (
                isinstance(rank, bool)
                or not isinstance(rank, int)
                or rank < 1
                or not isinstance(metric_id, str)
                or not metric_id
            ):
                raise MetricRetrievalError("candidate rank payload is invalid")
            rows.append((rank, metric_id))
    ranks = [item[0] for item in rows]
    metric_ids = [item[1] for item in rows]
    if len(ranks) != len(set(ranks)) or len(metric_ids) != len(set(metric_ids)):
        raise MetricRetrievalError("candidate ranks are not unique")
    return tuple(metric_id for _rank, metric_id in sorted(rows))


def _planned_datahub_requests(
    engine: QueryGovernanceEngine,
    snapshot: object,
    terms: dict[str, object],
    query: str,
    search_mode: str,
) -> int:
    """평가 probe가 계획한 외부 검색 요청 수를 production planner와 같은 규칙으로 계산한다."""

    if search_mode == "lexical":
        return 0
    if search_mode == "hybrid":
        return 1
    hints = engine._governed_query_hints(snapshot, terms, query)
    return len(
        plan_search_queries(
            query,
            max_variants=engine._candidate_search_variants,
            governed_phrases=hints,
        )
    )


def _percentile(values: list[float], ratio: float) -> float:
    """bounded latency 표본의 선형 보간 percentile을 밀리초 셋째 자리로 반환한다."""

    if not values or not 0.0 <= ratio <= 1.0:
        raise MetricRetrievalError("latency percentile input is invalid")
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(
        ordered[lower] + (ordered[upper] - ordered[lower]) * fraction,
        3,
    )


def _ratio(value: str) -> float:
    """CLI threshold를 0~1의 유한 비율로 검증한다."""

    parsed = float(value)
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("threshold must be between 0 and 1")
    return parsed


def _positive_integer(value: str) -> int:
    """CLI bound를 bool 보정 없는 양의 정수로 검증한다."""

    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("bound must be positive")
    return parsed


def main() -> int:
    """환경 기반 read identity로 Gate를 실행하고 machine-readable JSON과 종료 코드를 반환한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", default="analyst")
    parser.add_argument("--domain", action="append", default=[])
    parser.add_argument(
        "--expected-context-release",
        default=os.getenv("ANALYTICS_CONTEXT_RELEASE") or None,
    )
    parser.add_argument(
        "--search-mode",
        choices=tuple(sorted(SEARCH_MODES)),
        default="lexical",
    )
    parser.add_argument(
        "--phase2a-gold-manifest",
        type=Path,
        default=None,
        help="sealed Korean Gold manifest; runs lexical/shadow/DataHub comparison",
    )
    parser.add_argument("--top-k", type=_positive_integer, default=5)
    parser.add_argument("--max-candidates", type=_positive_integer, default=24)
    parser.add_argument(
        "--candidate-search-count",
        type=_positive_integer,
        choices=range(1, 51),
        default=20,
    )
    parser.add_argument("--min-catalog-exact-top1", type=_ratio, default=1.0)
    parser.add_argument("--min-definition-top1", type=_ratio, default=1.0)
    parser.add_argument("--min-definition-recall-at-k", type=_ratio, default=1.0)
    parser.add_argument("--min-negative-closure", type=_ratio, default=1.0)
    parser.add_argument("--max-negative-contamination", type=_ratio, default=0.0)
    parser.add_argument("--include-cases", action="store_true")
    arguments = parser.parse_args()
    try:
        result = asyncio.run(_run(arguments))
    except (
        MetricRetrievalError,
        DataHubCatalogError,
        MetadataUnavailableError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(
            json.dumps(
                {"status": "INVALID", "error": str(error)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if result["status"] == "PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
