"""승인 전 metric 검토 계약이 임의 도메인에서도 fail-closed하는지 검증한다."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
if str(DATAHUB) not in sys.path:
    sys.path.insert(0, str(DATAHUB))

from metadata_contract_primitives import SemanticMetadataError  # noqa: E402
from metric_review_contract import validate_metric_review  # noqa: E402
from runtime_governance_draft import (  # noqa: E402
    FieldEvidence,
    GovernanceDraft,
    ViewEvidence,
    build_draft,
)


def _evidence() -> GovernanceDraft:
    fields = tuple(
        FieldEvidence(name, name, name, (), "PASS_THROUGH", ())
        for name in ("observed_on", "segment", "amount", "events")
    )
    return GovernanceDraft(
        release_version="sample-release-v1",
        serving_schema="serving.sample",
        source_sha256="a" * 64,
        views=(
            ViewEvidence(
                fqn="serving.sample.daily_observations",
                description="Arbitrary observations.",
                source_file="20_observations.sql",
                source_relations=("source.sample.observations",),
                grain_candidates=("observed_on", "segment"),
                fields=fields,
            ),
        ),
    )


def _scope() -> dict[str, object]:
    return {
        "grain": {
            "kind": "segment_day",
            "keys": ["observed_on", "segment"],
            "dimensions": ["segment"],
        },
        "time": {
            "field": "observed_on",
            "semantics": "OBSERVATION_DATE",
            "timezone": "UTC",
            "interval": "[start,end)",
            "bucket": "day",
            "timezone_mode": "preserve",
        },
        "join": {"required": False, "allowed_edge_ids": []},
        "permission": {
            "roles": ["analyst"],
            "contains_pii": False,
            "synthetic": False,
        },
        "query_strategies": ["VIEW_REUSE"],
    }


def _column(metric_id: str, column: str) -> dict[str, object]:
    return {
        "id": metric_id,
        "name": metric_id.replace("_", " ").title(),
        "visibility": "SUPPORT",
        "review_status": "REVIEW_REQUIRED",
        "definition": f"Arbitrary definition for {metric_id}.",
        "formula": {"kind": "COLUMN", "aggregation": "sum", "reduction": "sum"},
        "source": {
            "kind": "COLUMN",
            "asset_fqn": "serving.sample.daily_observations",
            "column": column,
        },
        "aliases": [f"{metric_id} alias"],
        "unit": "unit",
        "result_field": metric_id,
        **deepcopy(_scope()),
    }


def _candidate() -> dict[str, object]:
    amount = _column("total_amount", "amount")
    events = _column("event_count", "events")
    ratio = {
        "id": "amount_per_event",
        "name": "Amount Per Event",
        "visibility": "BUSINESS",
        "review_status": "REVIEW_REQUIRED",
        "definition": "Total amount divided by event count for an arbitrary sample.",
        "formula": {
            "kind": "RATIO",
            "numerator_metric_id": "total_amount",
            "denominator_metric_id": "event_count",
            "zero_policy": "null_on_zero_denominator",
        },
        "source": {
            "kind": "METRIC_OPERANDS",
            "metric_ids": ["total_amount", "event_count"],
        },
        "aliases": ["amount per event alias"],
        "unit": "unit_per_event",
        "result_field": "amount_per_event",
        **deepcopy(_scope()),
    }
    return {
        "contract_version": "answervice.metric_review.v1",
        "review_status": "REVIEW_REQUIRED",
        "release_id": "sample-release-v1",
        "serving_schema": "serving.sample",
        "source_sql_sha256": "a" * 64,
        "business_metric_target_count": 1,
        "allowed_roles": ["analyst"],
        "review_owner_candidate_urn": "urn:li:corpGroup:sample_stewards",
        "metrics": [amount, events, ratio],
    }


def test_generic_review_candidate_is_valid_but_never_publishable():
    result = validate_metric_review(_candidate(), _evidence())

    assert result["status"] == "VALID_REVIEW_DRAFT"
    assert result["business_metric_count"] == 1
    assert result["support_metric_count"] == 2
    assert result["approval_status"] == "NOT_APPROVED"
    assert result["publishable"] is False


def test_v2_review_binds_asset_and_dimension_additions_to_sql_evidence():
    """신규 semantic scope는 SQL view·field 근거가 있을 때만 검토안에 들어간다."""

    candidate = _candidate()
    candidate.update(
        {
            "contract_version": "answervice.metric_review.v2",
            "asset_additions": [
                {
                    "fqn": "serving.sample.daily_observations",
                    "domain_urn": "urn:li:domain:sample",
                    "grain": {
                        "kind": "periodic",
                        "keys": ["observed_on", "segment"],
                    },
                }
            ],
            "dimension_additions": [
                {
                    "id": "sample_segment",
                    "aliases": ["sample segment", "표본 구분"],
                    "definition": "Arbitrary segment captured on the observation row.",
                    "asset_fqn": "serving.sample.daily_observations",
                    "column": "segment",
                }
            ],
        }
    )

    result = validate_metric_review(candidate, _evidence())

    assert result["contract_version"] == "answervice.metric_review.v2"
    assert result["asset_addition_count"] == 1
    assert result["dimension_addition_count"] == 1

    candidate["dimension_additions"][0]["column"] = "not_in_sql"
    with pytest.raises(SemanticMetadataError, match="SQL release fields"):
        validate_metric_review(candidate, _evidence())


def test_governed_owner_can_seal_an_approved_review():
    """승인 상태는 owner·timezone timestamp와 모든 Metric 상태가 함께 바뀔 때만 유효하다."""

    candidate = _candidate()
    candidate.update(
        {
            "review_status": "APPROVED",
            "reviewer": "urn:li:corpGroup:sample_stewards",
            "reviewed_at": "2026-08-23T12:34:56+09:00",
        }
    )
    for metric in candidate["metrics"]:
        metric["review_status"] = "APPROVED"

    result = validate_metric_review(candidate, _evidence())

    assert result["status"] == "VALID_APPROVED_REVIEW"
    assert result["approval_status"] == "APPROVED"
    assert result["publishable"] is True


def test_approved_review_rejects_a_different_reviewer_or_partial_metric_state():
    """승인자 위조와 일부 Metric만 승인된 혼합 상태를 fail-closed한다."""

    candidate = _candidate()
    candidate.update(
        {
            "review_status": "APPROVED",
            "reviewer": "urn:li:corpGroup:another_group",
            "reviewed_at": "2026-08-23T12:34:56+09:00",
        }
    )
    for metric in candidate["metrics"]:
        metric["review_status"] = "APPROVED"
    with pytest.raises(SemanticMetadataError, match="governed owner"):
        validate_metric_review(candidate, _evidence())

    candidate["reviewer"] = "urn:li:corpGroup:sample_stewards"
    candidate["metrics"][0]["review_status"] = "REVIEW_REQUIRED"
    with pytest.raises(SemanticMetadataError, match="review-level"):
        validate_metric_review(candidate, _evidence())


def test_review_rejects_release_drift_and_ratio_scope_drift():
    candidate = _candidate()
    candidate["source_sql_sha256"] = "b" * 64
    with pytest.raises(SemanticMetadataError, match="SQL release evidence"):
        validate_metric_review(candidate, _evidence())

    candidate = _candidate()
    candidate["metrics"][2]["time"]["timezone"] = "Asia/Seoul"
    with pytest.raises(SemanticMetadataError, match="one physical calculation scope"):
        validate_metric_review(candidate, _evidence())


def test_review_rejects_unregistered_authentication_roles():
    candidate = _candidate()
    candidate["allowed_roles"] = ["unregistered_role"]
    for metric in candidate["metrics"]:
        metric["permission"]["roles"] = ["unregistered_role"]

    with pytest.raises(SemanticMetadataError, match="unsupported authentication role"):
        validate_metric_review(candidate, _evidence())


def test_d2_review_candidate_matches_the_pinned_release_sql():
    release_sql = (
        ROOT
        / "infrastructure"
        / "database"
        / "releases"
        / "walkerhill_v4_3_20260815_derived_1"
        / "01_V4.3_생성_및_서빙_SQL"
        / "06_trino_serving"
    )
    evidence = build_draft(
        release_sql,
        "serving.analytics_v4_3",
        "walkerhill-v4.3-sql-20260815-derived.1",
    )
    candidate_path = (
        ROOT / "evals" / "semantic_review" / "answervice_d2_metrics.v1.json"
    )
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))

    result = validate_metric_review(candidate, evidence)

    assert result["business_metric_count"] == 10
    assert result["support_metric_count"] == 4
    assert result["status"] == "VALID_APPROVED_REVIEW"
    assert result["approval_status"] == "APPROVED"
    assert result["publishable"] is True

    occupancy = next(
        item for item in candidate["metrics"] if item["id"] == "occupancy_rate"
    )
    assert "투숙률" in occupancy["aliases"]
    total_revenue = next(
        item
        for item in candidate["metrics"]
        if item["id"] == "total_operating_revenue_krw"
    )
    assert {"호텔 매출", "호텔 전체 매출", "호텔 총매출"} <= set(
        total_revenue["aliases"]
    )
