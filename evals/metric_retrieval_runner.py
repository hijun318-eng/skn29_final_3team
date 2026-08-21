"""실제 active DataHub release의 label·alias로 Metric 후보 검색 Gate를 실행한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.datahub_catalog import (  # noqa: E402
    DataHubCatalogClient,
    DataHubCatalogError,
)
from app.adapters.query_governance import QueryGovernanceEngine  # noqa: E402
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
    build_metric_retrieval_probes,
    evaluate_metric_retrieval,
)


class _RejectSchemaInspection:
    """후보 retrieval Gate가 Trino schema를 조회하면 즉시 실패시키는 sentinel이다."""

    async def verify(self, _datasets: object) -> None:
        """후보 단계의 Trino 접근을 성공으로 위장하지 않는다."""

        raise MetricRetrievalError(
            "metric retrieval candidate search must not inspect Trino schema"
        )


async def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    """active release에서 probe를 만들고 실제 후보 API 관측과 threshold 판정을 반환한다."""

    catalog = DataHubCatalogClient.from_env()
    engine = QueryGovernanceEngine(
        catalog,
        _RejectSchemaInspection(),
        expected_context_release=arguments.expected_context_release,
        max_candidate_metrics=arguments.max_candidates,
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
        probes = build_metric_retrieval_probes(
            {metric_id: term.as_dict() for metric_id, term in terms.items()},
            eligible_ids,
        )
        observations: list[MetricRetrievalObservation] = []
        for probe in probes:
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
        result = evaluate_metric_retrieval(
            probes,
            observations,
            top_k=arguments.top_k,
            max_candidates=arguments.max_candidates,
        )
    finally:
        await catalog.aclose()

    passed = (
        result["top1_accuracy"] >= arguments.min_top1_accuracy
        and result["recall_at_k"] >= arguments.min_recall_at_k
        and result["precision_at_k"] >= arguments.min_precision_at_k
        and result["retrieval_error_count"] == 0
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
            "thresholds": {
                "min_top1_accuracy": arguments.min_top1_accuracy,
                "min_recall_at_k": arguments.min_recall_at_k,
                "min_precision_at_k": arguments.min_precision_at_k,
            },
        }
    )
    if not arguments.include_cases:
        result.pop("cases", None)
    return result


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
    if (
        not rows
        or len(ranks) != len(set(ranks))
        or len(metric_ids) != len(set(metric_ids))
    ):
        raise MetricRetrievalError("candidate ranks are not unique")
    return tuple(metric_id for _rank, metric_id in sorted(rows))


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
        choices=("lexical", "hybrid"),
        default="lexical",
    )
    parser.add_argument("--top-k", type=_positive_integer, default=5)
    parser.add_argument("--max-candidates", type=_positive_integer, default=24)
    parser.add_argument("--min-top1-accuracy", type=_ratio, default=1.0)
    parser.add_argument("--min-recall-at-k", type=_ratio, default=1.0)
    parser.add_argument("--min-precision-at-k", type=_ratio, default=0.0)
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
