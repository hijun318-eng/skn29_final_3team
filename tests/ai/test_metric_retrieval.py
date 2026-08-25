"""Catalog-derived Metric retrieval 구조·폐쇄 점수 계약을 검증한다."""

from __future__ import annotations

import json
from argparse import Namespace

import pytest

from evals.metric_retrieval import (
    NEGATIVE_DIMENSION,
    NEGATIVE_OUT_OF_SCOPE,
    NEGATIVE_SUPPORT,
    NEGATIVE_HELDOUT_KOREAN,
    POSITIVE_DEFINITION,
    POSITIVE_EXACT,
    POSITIVE_HELDOUT_KOREAN,
    MetricRetrievalError,
    MetricRetrievalObservation,
    MetricRetrievalProbe,
    build_metric_retrieval_probes,
    evaluate_metric_retrieval,
    load_metric_retrieval_gold,
    normalize_retrieval_query,
)
from evals.metric_retrieval_runner import _percentile, _phase2a_quality_checks


def _probe(
    kind: str,
    query: str,
    expected_metric_ids: tuple[str, ...] = (),
) -> MetricRetrievalProbe:
    return MetricRetrievalProbe(
        kind=kind,
        query=query,
        normalized_query=normalize_retrieval_query(query),
        expected_metric_ids=expected_metric_ids,
    )


def test_catalog_sources_build_separate_positive_and_negative_probes() -> None:
    """exact·definition·SUPPORT·차원·권한 밖·범위 밖 증거가 한 점수로 섞이지 않는다."""

    probes = build_metric_retrieval_probes(
        {
            "metric_alpha": {
                "label": "Approved Value",
                "aliases": ["Canonical Measure", "Shared Measure"],
                "definition": "승인된 활동에서 발생한 금액의 합계",
            },
            "metric_beta": {
                "label": "Approved Count",
                "aliases": ["shared   measure"],
                "definition": "완료된 업무 레코드의 고유 개수",
            },
        },
        ("metric_alpha", "metric_beta"),
        support_phrases=("Internal Amount",),
        dimension_phrases=("Business Region",),
        forbidden_terms={
            "restricted_metric": {
                "label": "Restricted Value",
                "aliases": [],
                "definition": "권한이 있는 사용자만 보는 제한 값",
            }
        },
        out_of_scope_query="unmatched_0123456789abcdef",
    )
    exact = {
        item.normalized_query: item
        for item in probes
        if item.kind == POSITIVE_EXACT
    }

    assert exact["shared measure"].expected_metric_ids == (
        "metric_alpha",
        "metric_beta",
    )
    assert any(item.kind == POSITIVE_DEFINITION for item in probes)
    assert {item.kind for item in probes}.issuperset(
        {
            NEGATIVE_SUPPORT,
            NEGATIVE_DIMENSION,
            NEGATIVE_OUT_OF_SCOPE,
            "negative_out_of_entitlement",
        }
    )


def test_retrieval_scores_positive_quality_and_negative_contamination_separately() -> None:
    probes = (
        _probe(POSITIVE_EXACT, "Alpha", ("metric_alpha",)),
        _probe(POSITIVE_DEFINITION, "approved activity value", ("metric_alpha",)),
        _probe(NEGATIVE_SUPPORT, "Internal Amount"),
        _probe(NEGATIVE_DIMENSION, "Business Region"),
    )
    observations = (
        MetricRetrievalObservation("Alpha", ("metric_alpha", "metric_beta")),
        MetricRetrievalObservation(
            "approved activity value", (), "NoMetricMatchError"
        ),
        MetricRetrievalObservation("Internal Amount", (), "NoMetricMatchError"),
        MetricRetrievalObservation("Business Region", ("metric_beta",)),
    )

    result = evaluate_metric_retrieval(
        probes,
        observations,
        top_k=2,
        max_candidates=4,
    )

    assert result["catalog_exact_self_consistency"]["top1_accuracy"] == 1.0
    assert result["definition_overlap_retrieval"]["top1_accuracy"] == 0.0
    assert result["definition_overlap_retrieval"]["retrieval_error_count"] == 1
    assert result["negative_closure"]["closure_rate"] == 0.5
    assert result["negative_closure"]["contamination_rate"] == 0.5
    assert result["negative_closure"]["infrastructure_error_count"] == 0
    assert result["natural_language_paraphrase"]["scorable"] is False


def test_negative_infrastructure_failure_is_not_counted_as_safe_closure() -> None:
    probes = (
        _probe(POSITIVE_EXACT, "Alpha", ("metric_alpha",)),
        _probe(NEGATIVE_OUT_OF_SCOPE, "unmatched_deadbeef"),
    )
    result = evaluate_metric_retrieval(
        probes,
        (
            MetricRetrievalObservation("Alpha", ("metric_alpha",)),
            MetricRetrievalObservation(
                "unmatched_deadbeef", (), "MetadataUnavailableError"
            ),
        ),
        top_k=1,
        max_candidates=2,
    )

    assert result["negative_closure"]["closure_rate"] == 0.0
    assert result["negative_closure"]["contamination_rate"] == 0.0
    assert result["negative_closure"]["infrastructure_error_count"] == 1


def test_retrieval_contract_rejects_duplicate_or_unbounded_candidates() -> None:
    probes = (
        _probe(POSITIVE_EXACT, "Alpha", ("metric_alpha",)),
        _probe(NEGATIVE_OUT_OF_SCOPE, "unmatched_deadbeef"),
    )
    with pytest.raises(MetricRetrievalError, match="observation is invalid"):
        evaluate_metric_retrieval(
            probes,
            (
                MetricRetrievalObservation(
                    "Alpha",
                    ("metric_alpha", "metric_alpha"),
                ),
                MetricRetrievalObservation(
                    "unmatched_deadbeef", (), "NoMetricMatchError"
                ),
            ),
            top_k=1,
            max_candidates=1,
        )


def test_candidate_latency_percentile_uses_bounded_linear_interpolation() -> None:
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.50) == 2.5
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 3.85
    with pytest.raises(MetricRetrievalError, match="percentile input"):
        _percentile([], 0.50)


def test_phase2a_gate_rejects_wrong_datahub_candidate_quality() -> None:
    """정상 응답·낮은 지연만으로 오답인 운영 후보 경로가 통과하지 못한다."""

    measurement = {
        "catalog_exact_self_consistency": {
            "scorable": True,
            "top1_accuracy": 1.0,
            "retrieval_error_count": 0,
        },
        "definition_overlap_retrieval": {
            "scorable": True,
            "top1_accuracy": 1.0,
            "recall_at_k": 1.0,
            "retrieval_error_count": 0,
        },
        "negative_closure": {
            "closure_rate": 1.0,
            "contamination_rate": 0.0,
            "infrastructure_error_count": 0,
        },
        "natural_language_paraphrase": {
            "scorable": True,
            "top1_accuracy": 1.0,
            "recall_at_k": 1.0,
            "mean_reciprocal_rank": 1.0,
            "retrieval_error_count": 0,
            "negative_closure": {
                "scorable": True,
                "closure_rate": 1.0,
                "infrastructure_error_count": 0,
            },
        },
    }
    degraded_candidate = json.loads(json.dumps(measurement))
    degraded_candidate["natural_language_paraphrase"]["top1_accuracy"] = 0.0
    checks = _phase2a_quality_checks(
        {
            "lexical": measurement,
            "datahub_lexical": degraded_candidate,
        },
        Namespace(
            min_catalog_exact_top1=1.0,
            min_definition_top1=1.0,
            min_definition_recall_at_k=1.0,
            min_negative_closure=1.0,
            max_negative_contamination=0.0,
        ),
        {
            "min_baseline_heldout_top1": 0.8,
            "min_baseline_heldout_recall_at_k": 0.9,
            "min_baseline_heldout_mrr": 0.85,
        },
    )

    assert checks == {
        "catalog_baseline_contract": True,
        "baseline_heldout_quality": True,
        "candidate_catalog_contract": True,
        "candidate_heldout_quality": False,
    }


def test_sealed_korean_gold_loads_and_scores_only_heldout_split() -> None:
    gold = load_metric_retrieval_gold(
        "evals/metric_retrieval_gold/answervice_ko_retrieval.v1.json"
    )
    assert gold.dataset_id == "answervice_ko_retrieval.v1"
    assert len(gold.probes) == 19
    assert {probe.split for probe in gold.probes} == {"calibration", "heldout"}

    probes = (
        MetricRetrievalProbe(
            POSITIVE_HELDOUT_KOREAN,
            "객실 수입을 알려줘",
            normalize_retrieval_query("객실 수입을 알려줘"),
            ("room_revenue",),
            "KO-C-T-001",
            "calibration",
        ),
        MetricRetrievalProbe(
            POSITIVE_HELDOUT_KOREAN,
            "식음료 수입을 알려줘",
            normalize_retrieval_query("식음료 수입을 알려줘"),
            ("fnb_revenue",),
            "KO-H-T-001",
            "heldout",
        ),
        MetricRetrievalProbe(
            NEGATIVE_HELDOUT_KOREAN,
            "탄소배출량",
            normalize_retrieval_query("탄소배출량"),
            (),
            "KO-H-T-002",
            "heldout",
        ),
    )
    result = evaluate_metric_retrieval(
        probes,
        (
            MetricRetrievalObservation("객실 수입을 알려줘", ("room_revenue",)),
            MetricRetrievalObservation("식음료 수입을 알려줘", ("fnb_revenue",)),
            MetricRetrievalObservation("탄소배출량", (), "NoMetricMatchError"),
        ),
        top_k=5,
        max_candidates=24,
    )
    natural = result["natural_language_paraphrase"]
    assert natural["probe_count"] == 1
    assert natural["top1_accuracy"] == 1.0
    assert natural["negative_closure"]["closure_rate"] == 1.0


def test_sealed_korean_gold_rejects_tampered_content(tmp_path) -> None:
    source = "evals/metric_retrieval_gold/answervice_ko_retrieval.v1.json"
    document = json.loads(open(source, encoding="utf-8").read())
    document["cases"][0]["query"] = "변조된 한국어 질의"
    target = tmp_path / "tampered.json"
    target.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(MetricRetrievalError, match="hash differs"):
        load_metric_retrieval_gold(target)
