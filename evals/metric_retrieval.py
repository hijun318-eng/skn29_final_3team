"""Active catalog 용어로 생성한 Metric 후보 검색 관측을 결정론적으로 채점한다."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


METRIC_RETRIEVAL_VERSION = "answervice.metric_retrieval.v1"


class MetricRetrievalError(ValueError):
    """검색 probe나 관측이 bounded 평가 계약을 위반했음을 나타낸다."""


@dataclass(frozen=True)
class MetricRetrievalProbe:
    """하나의 catalog 용어와 그 용어를 공유하는 기대 BUSINESS Metric 집합이다."""

    query: str
    normalized_query: str
    expected_metric_ids: tuple[str, ...]


@dataclass(frozen=True)
class MetricRetrievalObservation:
    """한 probe에 대해 runtime 후보 검색이 반환한 rank 순 Metric과 typed 실패다."""

    query: str
    ranked_metric_ids: tuple[str, ...]
    error_type: str | None = None


def build_metric_retrieval_probes(
    terms: Mapping[str, Mapping[str, object]],
    eligible_metric_ids: Iterable[str],
) -> tuple[MetricRetrievalProbe, ...]:
    """승인 label·alias를 정규화해 동일 문구의 기대 Metric을 합친 probe를 만든다."""

    metric_ids = tuple(sorted(set(eligible_metric_ids)))
    if not metric_ids or any(not _identifier(item) for item in metric_ids):
        raise MetricRetrievalError("eligible metric ids must be non-empty identifiers")
    phrase_metrics: dict[str, set[str]] = {}
    display_queries: dict[str, str] = {}
    for metric_id in metric_ids:
        term = terms.get(metric_id)
        if not isinstance(term, Mapping):
            raise MetricRetrievalError("eligible metric is missing its catalog term")
        label = term.get("label")
        aliases = term.get("aliases")
        if (
            not isinstance(label, str)
            or not label.strip()
            or not isinstance(aliases, (list, tuple))
            or any(not isinstance(item, str) or not item.strip() for item in aliases)
        ):
            raise MetricRetrievalError("catalog metric label or aliases are invalid")
        phrases = tuple(dict.fromkeys((label.strip(), *(item.strip() for item in aliases))))
        for phrase in phrases:
            normalized = normalize_retrieval_query(phrase)
            phrase_metrics.setdefault(normalized, set()).add(metric_id)
            display_queries.setdefault(normalized, phrase)
    return tuple(
        MetricRetrievalProbe(
            query=display_queries[normalized],
            normalized_query=normalized,
            expected_metric_ids=tuple(sorted(expected_ids)),
        )
        for normalized, expected_ids in sorted(phrase_metrics.items())
    )


def evaluate_metric_retrieval(
    probes: Sequence[MetricRetrievalProbe],
    observations: Sequence[MetricRetrievalObservation],
    *,
    top_k: int,
    max_candidates: int,
) -> dict[str, Any]:
    """probe별 top-1·recall@K·precision@K·MRR과 typed retrieval 실패를 집계한다."""

    if (
        not probes
        or len(probes) != len(observations)
        or len({item.normalized_query for item in probes}) != len(probes)
        or isinstance(top_k, bool)
        or not isinstance(top_k, int)
        or top_k < 1
        or isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or max_candidates < 1
    ):
        raise MetricRetrievalError("retrieval evaluation bounds are invalid")

    cases: list[dict[str, Any]] = []
    total_expected = 0
    total_recalled = 0
    top1_hits = 0
    recall_total = 0.0
    precision_total = 0.0
    reciprocal_rank_total = 0.0
    retrieval_error_count = 0
    observed_metrics: set[str] = set()
    expected_metrics: set[str] = set()
    for probe, observation in zip(probes, observations, strict=True):
        if observation.query != probe.query:
            raise MetricRetrievalError("retrieval observation order differs from probes")
        if probe.normalized_query != normalize_retrieval_query(probe.query):
            raise MetricRetrievalError("retrieval probe normalization is invalid")
        ranked = observation.ranked_metric_ids
        if (
            len(ranked) > max_candidates
            or len(ranked) != len(set(ranked))
            or any(not _identifier(item) for item in ranked)
            or (
                observation.error_type is not None
                and (
                    not isinstance(observation.error_type, str)
                    or not observation.error_type
                    or ranked
                )
            )
        ):
            raise MetricRetrievalError("retrieval observation is invalid")
        expected = set(probe.expected_metric_ids)
        if (
            not expected
            or len(expected) != len(probe.expected_metric_ids)
            or any(not _identifier(item) for item in expected)
        ):
            raise MetricRetrievalError("retrieval probe expectation is invalid")
        top = ranked[:top_k]
        recalled = expected.intersection(top)
        first_rank = next(
            (index for index, metric_id in enumerate(ranked, start=1) if metric_id in expected),
            None,
        )
        top1_hit = bool(ranked and ranked[0] in expected)
        recall = len(recalled) / len(expected)
        precision = len(recalled) / len(top) if top else 0.0
        reciprocal_rank = 1.0 / first_rank if first_rank is not None else 0.0
        total_expected += len(expected)
        total_recalled += len(recalled)
        top1_hits += int(top1_hit)
        recall_total += recall
        precision_total += precision
        reciprocal_rank_total += reciprocal_rank
        retrieval_error_count += int(observation.error_type is not None)
        observed_metrics.update(ranked)
        expected_metrics.update(expected)
        cases.append(
            {
                "query": probe.query,
                "expected_metric_ids": sorted(expected),
                "ranked_metric_ids": list(ranked),
                "top1_hit": top1_hit,
                "recall_at_k": _score(recall),
                "precision_at_k": _score(precision),
                "reciprocal_rank": _score(reciprocal_rank),
                "error_type": observation.error_type,
            }
        )

    count = len(probes)
    return {
        "contract_version": METRIC_RETRIEVAL_VERSION,
        "probe_count": count,
        "expected_metric_count": len(expected_metrics),
        "observed_metric_count": len(observed_metrics),
        "top_k": top_k,
        "max_candidates": max_candidates,
        "top1_accuracy": _score(top1_hits / count),
        "recall_at_k": _score(recall_total / count),
        "micro_recall_at_k": _score(total_recalled / total_expected),
        "precision_at_k": _score(precision_total / count),
        "mean_reciprocal_rank": _score(reciprocal_rank_total / count),
        "top1_miss_count": count - top1_hits,
        "incomplete_recall_count": sum(
            item["recall_at_k"] < 1.0 for item in cases
        ),
        "retrieval_error_count": retrieval_error_count,
        "max_observed_candidate_count": max(
            len(item.ranked_metric_ids) for item in observations
        ),
        "cases": cases,
    }


def normalize_retrieval_query(value: str) -> str:
    """표시 문구를 바꾸지 않고 동등성 판정용 NFKC·casefold·공백 정규화를 수행한다."""

    if not isinstance(value, str):
        raise MetricRetrievalError("retrieval query must be text")
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not normalized or len(normalized) > 512:
        raise MetricRetrievalError("retrieval query is empty or too long")
    return normalized


def _identifier(value: object) -> bool:
    """Metric 식별자를 평가 파일에 안전한 bounded 문자열로 제한한다."""

    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= 128
        and value == value.strip()
    )


def _score(value: float) -> float:
    """환경별 부동소수 표현 차이를 없애기 위해 점수를 고정 정밀도로 반올림한다."""

    return round(value, 6)
