from __future__ import annotations

import argparse
import copy

import pytest

from evals.p0_gold import canonical_sha256
from infrastructure.acceptance import phase10_p0_product_eval as product_eval


def _semantic() -> dict[str, object]:
    return {
        "metrics": [
            {
                "id": "room_revenue",
                "result_field": "room_revenue_krw",
                "time": {
                    "semantics": "BUSINESS_DATE",
                    "interval": "[start,end)",
                },
            },
            {
                "id": "fnb_revenue",
                "result_field": "fnb_revenue_krw",
                "time": {
                    "semantics": "BUSINESS_DATE",
                    "interval": "[start,end)",
                },
            },
        ]
    }


def _analysis_turn() -> dict[str, object]:
    return {
        "turn_id": "turn-1",
        "route": "ANALYSIS",
        "terminal_status": "SUCCEEDED",
        "reason_code": None,
        "source_turn_ids": [],
        "resolved_slots": {
            "business_terms": ["객실 매출"],
            "metric_id": "room_revenue",
            "metric_ids": ["room_revenue"],
            "dimension_fields": [
                {
                    "asset_fqn": "serving.analytics_v4_3.hotel_operations_daily",
                    "column": "hotel_code",
                }
            ],
            "time_range": {
                "start": "2025-08-01",
                "end_exclusive": "2025-09-01",
                "source_text": "2025년 8월",
            },
            "comparison_time_range": None,
            "target_chart_type": "SUMMARY",
            "change_set": [
                {"field": "metric_id", "operation": "PRESERVE", "value": "room_revenue"},
                {
                    "field": "dimension_fields",
                    "operation": "ADD_VALUE",
                    "value": {"column": "hotel_code"},
                },
            ],
            "analysis_plan_observation": {
                "query_strategy": "VIEW_REUSE",
                "source_assets": ["serving.analytics_v4_3.hotel_operations_daily"],
                "join_ids": [],
                "time_bucket": "month",
                "analysis_plan_sha256": "a" * 64,
            },
        },
        "data_snapshot_json": {
            "columns": ["hotel_code", "room_revenue_krw"],
            "rows": [{"hotel_code": "GRAND", "room_revenue_krw": "12.00"}],
        },
    }


def test_normalizes_actual_analysis_turn_without_gold_expected_values() -> None:
    output = product_eval.normalize_product_output([_analysis_turn()], _semantic())

    assert output == {
        "route": "ANALYSIS",
        "resolved_request": {
            "business_terms": ["객실 매출"],
            "metric_ids": ["room_revenue"],
            "dimensions": ["hotel_code"],
            "period": {"start": "2025-08-01", "end_exclusive": "2025-09-01"},
            "time_rule": "BUSINESS_DATE:[start,end)",
            "grain": "month_hotel",
            "chart_type": "SUMMARY",
            "operations": ["ADD_VALUE:dimensions"],
        },
        "query_strategy": "VIEW_REUSE",
        "assets": ["serving.analytics_v4_3.hotel_operations_daily"],
        "join_ids": [],
        "allow_or_block": "ALLOW",
        "error_code": None,
        "result": {
            "columns": ["hotel_code", "room_revenue"],
            "rows": [["GRAND", 12]],
        },
    }


def test_normalizes_scalar_and_preserves_non_numeric_strings() -> None:
    assert product_eval.normalize_result(
        {"columns": ["room_revenue_krw"], "rows": [{"room_revenue_krw": "12.00"}]},
        {"room_revenue_krw": "room_revenue"},
        ["room_revenue"],
    ) == 12
    assert product_eval.normalize_result(
        {"columns": ["business_date"], "rows": [{"business_date": "2025-08-01"}]},
        {},
        ["room_revenue"],
    ) == {"columns": ["business_date"], "rows": [["2025-08-01"]]}


def test_presentation_inherits_only_observed_source_plan_for_grain() -> None:
    analysis = _analysis_turn()
    presentation = copy.deepcopy(analysis)
    presentation.update(
        {
            "turn_id": "turn-2",
            "route": "PRESENTATION",
            "source_turn_ids": ["turn-1"],
        }
    )
    presentation["resolved_slots"]["target_chart_type"] = "TABLE"
    presentation["resolved_slots"]["analysis_plan_observation"] = None
    presentation["resolved_slots"]["change_set"] = [
        {"field": "target_chart_type", "operation": "SET", "value": "TABLE"}
    ]

    output = product_eval.normalize_product_output(
        [analysis, presentation],
        _semantic(),
    )

    assert output["route"] == "PRESENTATION"
    assert output["query_strategy"] is None
    assert output["assets"] == []
    assert output["resolved_request"]["grain"] == "month_hotel"
    assert output["resolved_request"]["operations"] == ["SET:chart_type"]


def test_product_http_failure_is_an_honest_blocked_observation() -> None:
    output = product_eval.normalize_product_output(
        [],
        _semantic(),
        product_error_code="HTTP_503",
    )

    assert output["allow_or_block"] == "BLOCK"
    assert output["error_code"] == "HTTP_503"
    assert output["route"] is None
    assert output["result"] is None
    assert output["resolved_request"] == product_eval._empty_resolved()


def test_release_lease_rejects_tampering() -> None:
    payload = {
        "schema_version": product_eval.LEASE_VERSION,
        "target_project": product_eval.TARGET_PROJECT,
    }
    document = dict(payload)
    document["receipt_sha256"] = canonical_sha256(payload)

    product_eval.validate_lease(document, payload)

    tampered = copy.deepcopy(document)
    tampered["target_project"] = "answervice"
    with pytest.raises(product_eval.Phase10P0ProductEvalError, match="lease"):
        product_eval.validate_lease(tampered, payload)


def test_product_evaluation_receipt_cannot_claim_pass_without_full_score() -> None:
    scoring = {
        "manifest_sha256": "a" * 64,
        "repeat": 2,
        "total": 55,
        "passed": 54,
        "deterministic": 55,
        "accuracy": 0.981818,
        "category_accuracy": {},
        "p50_ms": 1,
        "p95_ms": 2,
        "results": [],
    }
    receipt = product_eval._checked_document(
        {
            "schema_version": product_eval.RECEIPT_VERSION,
            "status": "BLOCKED",
            "target_project": product_eval.TARGET_PROJECT,
            "target_server": product_eval.TARGET_SERVER,
            "content_notice": product_eval.SYNTHETIC_NOTICE,
            "active_generation": 34,
            "product_release_id": "product-v1",
            "semantic_release_id": "semantic-v1",
            "projection_sha256": "b" * 64,
            "seal_receipt_sha256": "c" * 64,
            "gold_manifest_sha256": "d" * 64,
            "case_count": 55,
            "repeat": 2,
            "observation_count": 110,
            "observations_file": ".tmp/phase10-p0-product-observations.jsonl",
            "observations_sha256": "e" * 64,
            "model_invocation_count_by_node": {},
            "scoring": scoring,
            "historical_evidence_mixed": False,
            "skipped_evidence_count": 0,
            "evaluated_at": "2026-08-23T00:00:00+00:00",
        }
    )

    product_eval.validate_evaluation_receipt(
        receipt,
        observations_sha256="e" * 64,
        active_generation=34,
        product_release_id="product-v1",
        semantic_release_id="semantic-v1",
        seal_receipt_sha256="c" * 64,
    )

    tampered = copy.deepcopy(receipt)
    tampered["status"] = "PASSED"
    tampered["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "receipt_sha256"}
    )
    with pytest.raises(product_eval.Phase10P0ProductEvalError, match="receipt"):
        product_eval.validate_evaluation_receipt(tampered)


def test_boundary_requires_exact_isolated_product_and_two_repeats() -> None:
    args = argparse.Namespace(
        target_project=product_eval.TARGET_PROJECT,
        target_server=product_eval.TARGET_SERVER,
        database_url=(
            "postgresql+psycopg://phase10_runtime@127.0.0.1:55440/"
            "phase10_p0_same_release_acceptance"
        ),
        env_file=product_eval.ENV_FILE,
        repeat=2,
        timeout=180.0,
    )

    url = product_eval.validate_boundary(args)

    assert url.database == product_eval.TARGET_DATABASE
    args.repeat = 1
    with pytest.raises(product_eval.Phase10P0ProductEvalError, match="two repeats"):
        product_eval.validate_boundary(args)
