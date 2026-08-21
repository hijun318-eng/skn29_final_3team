"""Catalog-generated Metric retrieval probe와 점수 계약을 검증한다."""

from __future__ import annotations

import pytest

from evals.metric_retrieval import (
    MetricRetrievalError,
    MetricRetrievalObservation,
    build_metric_retrieval_probes,
    evaluate_metric_retrieval,
)


def test_catalog_labels_and_aliases_group_shared_phrases_without_question_fixtures() -> None:
    """같은 정규화 alias는 별도 예시 질문이 아니라 모든 기대 Metric의 ambiguity probe가 된다."""

    probes = build_metric_retrieval_probes(
        {
            "metric_alpha": {
                "label": "Approved Value",
                "aliases": ["Canonical Measure", "Shared Measure"],
            },
            "metric_beta": {
                "label": "Approved Count",
                "aliases": ["shared   measure"],
            },
        },
        ("metric_alpha", "metric_beta"),
    )
    by_query = {item.normalized_query: item for item in probes}

    assert by_query["shared measure"].expected_metric_ids == (
        "metric_alpha",
        "metric_beta",
    )
    assert {item.query for item in probes} == {
        "Approved Value",
        "Canonical Measure",
        "Shared Measure",
        "Approved Count",
    }


def test_retrieval_scores_ranked_candidates_and_typed_failures() -> None:
    """top-1, macro/micro recall, precision, MRR과 upstream typed 실패를 서로 섞지 않는다."""

    probes = build_metric_retrieval_probes(
        {
            "metric_alpha": {"label": "Alpha", "aliases": []},
            "metric_beta": {"label": "Beta", "aliases": []},
        },
        ("metric_alpha", "metric_beta"),
    )
    observations = (
        MetricRetrievalObservation("Alpha", ("metric_alpha", "metric_beta")),
        MetricRetrievalObservation("Beta", (), "NoMetricMatchError"),
    )

    result = evaluate_metric_retrieval(
        probes,
        observations,
        top_k=2,
        max_candidates=4,
    )

    assert result["top1_accuracy"] == 0.5
    assert result["recall_at_k"] == 0.5
    assert result["micro_recall_at_k"] == 0.5
    assert result["precision_at_k"] == 0.25
    assert result["mean_reciprocal_rank"] == 0.5
    assert result["retrieval_error_count"] == 1
    assert result["incomplete_recall_count"] == 1


def test_retrieval_contract_rejects_duplicate_or_unbounded_candidates() -> None:
    """중복 rank 결과나 후보 상한 초과를 좋은 점수로 축소하지 않고 계약 오류로 닫는다."""

    probes = build_metric_retrieval_probes(
        {"metric_alpha": {"label": "Alpha", "aliases": []}},
        ("metric_alpha",),
    )
    with pytest.raises(MetricRetrievalError, match="observation is invalid"):
        evaluate_metric_retrieval(
            probes,
            (
                MetricRetrievalObservation(
                    "Alpha",
                    ("metric_alpha", "metric_alpha"),
                ),
            ),
            top_k=1,
            max_candidates=1,
        )
