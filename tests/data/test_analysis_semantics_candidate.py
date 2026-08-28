"""회원 event-time과 투숙 time-role 후보가 질문별 예외 없이 검토되는지 확인한다."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
if str(DATAHUB) not in sys.path:
    sys.path.insert(0, str(DATAHUB))

from metric_review_contract import validate_metric_review  # noqa: E402
from runtime_governance_draft import build_draft  # noqa: E402


CANDIDATE = (
    ROOT / "evals" / "semantic_review" / "answervice_analysis_semantics.v2.json"
)
SQL_DIRECTORY = (
    ROOT
    / "infrastructure"
    / "database"
    / "serving_candidates"
    / "walkerhill_analysis_semantics_v1"
)


def _candidate() -> dict:
    return json.loads(CANDIDATE.read_text(encoding="utf-8"))


def test_candidate_is_review_only_and_checksum_bound_to_all_metric_sources() -> None:
    candidate = _candidate()
    evidence = build_draft(
        SQL_DIRECTORY,
        candidate["serving_schema"],
        candidate["release_id"],
    )

    result = validate_metric_review(candidate, evidence)

    assert result == {
        "status": "VALID_REVIEW_DRAFT",
        "contract_version": "answervice.metric_review.v2",
        "candidate_sha256": result["candidate_sha256"],
        "source_sql_sha256": "d93f2b27ad1cfcfc85dc3c7b4d6c9bd6f30cc87a6871698c97fc9e4c569ce652",
        "business_metric_count": 13,
        "support_metric_count": 4,
        "metric_count": 17,
        "asset_addition_count": 2,
        "dimension_addition_count": 1,
        "approval_status": "NOT_APPROVED",
        "publishable": False,
    }
    assert {view.fqn for view in evidence.views} == {
        "serving.analytics_v4_3.hotel_operations_daily",
        "serving.analytics_v4_3.member_revenue_daily",
        "serving.analytics_v4_3.room_stay_fact",
        "serving.analytics_v4_3.voc_review_detail",
    }


def test_candidate_uses_independent_reusable_metrics_and_exposes_no_member_id() -> None:
    candidate = _candidate()
    metrics = {item["id"]: item for item in candidate["metrics"]}
    evidence = build_draft(
        SQL_DIRECTORY,
        candidate["serving_schema"],
        candidate["release_id"],
    )
    views = {view.fqn: {field.name for field in view.fields} for view in evidence.views}

    assert {
        "member_room_revenue",
        "member_fnb_revenue",
        "checkout_room_revenue",
    } <= set(metrics)
    assert metrics["member_room_revenue"]["source"]["column"] == "room_revenue_krw"
    assert metrics["member_fnb_revenue"]["source"]["column"] == "fnb_revenue_krw"
    assert metrics["checkout_room_revenue"]["time"]["field"] == "checkout_date"
    assert not any(
        "room" in metric_id and "fnb" in metric_id for metric_id in metrics
    )
    assert views["serving.analytics_v4_3.member_revenue_daily"] == {
        "business_date",
        "hotel_code",
        "tier_code",
        "tier_name",
        "room_revenue_krw",
        "fnb_revenue_krw",
    }
    assert not {
        "guest_id",
        "member_no",
        "pos_customer_ref",
    } & views["serving.analytics_v4_3.member_revenue_daily"]
    assert {
        item["domain_urn"] for item in candidate["asset_additions"]
    } == {"urn:li:domain:answervice_serving"}

    membership = candidate["dimension_additions"]
    assert membership == [
        {
            "id": "membership_tier",
            "aliases": ["회원 등급", "멤버십 등급", "membership tier"],
            "definition": "매출 이벤트 시점의 CRM 유효기간 이력으로 확정한 멤버십 등급이다.",
            "asset_fqn": "serving.analytics_v4_3.member_revenue_daily",
            "column": "tier_code",
        }
    ]
