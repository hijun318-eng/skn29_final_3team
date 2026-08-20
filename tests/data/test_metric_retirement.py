"""Metric retirement가 release 전체 정합성과 dependency closure를 보존하는지 검증한다."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(DATAHUB), str(ROOT / "tests" / "data")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from metadata_contract import validate_bundle  # noqa: E402
from metadata_contract_primitives import SemanticMetadataError  # noqa: E402
from metric_retirement import (  # noqa: E402
    APPROVED_DECISION_STATUS,
    AUTHORIZATION_BASIS,
    RETIREMENT_DECISION_VERSION,
    build_retired_release,
    metric_retirement_check,
)
from src.data.governance_contract import catalog_hash  # noqa: E402
from test_datahub_metadata_publication import arbitrary_ratio_bundle  # noqa: E402
from test_metric_governance_v2 import _v2_bundle  # noqa: E402


def _decision(bundle: dict, *metric_ids: str) -> dict:
    terms = {item["id"]: item for item in bundle["metric_terms"]}
    return {
        "contract_version": RETIREMENT_DECISION_VERSION,
        "decision_id": "fixture-retirement-1",
        "decision_status": APPROVED_DECISION_STATUS,
        "authorization_basis": AUTHORIZATION_BASIS,
        "authorized_by": "fixture_project_owner",
        "recorded_at": "2026-08-20T00:00:00+09:00",
        "reason": "An explicit product-scope decision removed obsolete fixture metrics.",
        "previous_catalog_version": bundle["catalog_version"],
        "previous_catalog_sha256": catalog_hash(bundle),
        "target_catalog_version": f"{bundle['catalog_version']}-retired.1",
        "retirements": [
            {"metric_id": metric_id, "term_urn": terms[metric_id]["urn"]}
            for metric_id in sorted(metric_ids)
        ],
    }


def test_independent_business_metric_is_removed_as_a_new_valid_release() -> None:
    baseline = _v2_bundle()
    validate_bundle(baseline)
    decision = _decision(baseline, "account_count")

    target = build_retired_release(baseline, decision)
    check = metric_retirement_check(baseline, decision)

    validate_bundle(target)
    assert target["schema_context"] == baseline["schema_context"]
    assert {item["id"] for item in target["metric_rules"]} == {
        "amount_total",
        "event_count",
        "amount_per_event",
    }
    assert {item["id"] for item in target["metric_terms"]} == {
        "amount_per_event"
    }
    assert check["status"] == "CHECKED"
    assert check["previous_catalog_sha256"] == catalog_hash(baseline)
    assert check["target_catalog_sha256"] == catalog_hash(target)
    assert check["baseline_metric_count"] == 4
    assert check["target_metric_count"] == 3
    assert check["ready_to_publish"] is True


def test_retained_ratio_cannot_reference_a_retired_operand() -> None:
    baseline = arbitrary_ratio_bundle()
    validate_bundle(baseline)

    with pytest.raises(SemanticMetadataError, match="removed operand"):
        build_retired_release(baseline, _decision(baseline, "amount_total"))


def test_decision_must_match_exact_live_baseline_identity() -> None:
    baseline = _v2_bundle()
    decision = _decision(baseline, "account_count")
    decision["previous_catalog_sha256"] = "0" * 64

    with pytest.raises(SemanticMetadataError, match="live baseline"):
        build_retired_release(baseline, decision)


def test_unapproved_or_mismatched_term_decision_fails_closed() -> None:
    baseline = _v2_bundle()
    unapproved = _decision(baseline, "account_count")
    unapproved["decision_status"] = "REVIEW_REQUIRED"
    with pytest.raises(SemanticMetadataError, match="not approved"):
        build_retired_release(baseline, unapproved)

    mismatched = _decision(baseline, "account_count")
    mismatched["retirements"][0]["term_urn"] = (
        "urn:li:glossaryTerm:amount_per_event"
    )
    with pytest.raises(SemanticMetadataError, match="identities differ"):
        build_retired_release(baseline, mismatched)


def test_decision_content_and_retirement_order_are_canonical() -> None:
    baseline = arbitrary_ratio_bundle()
    decision = _decision(baseline, "event_count", "amount_total")
    reversed_decision = deepcopy(decision)
    reversed_decision["retirements"].reverse()

    with pytest.raises(SemanticMetadataError, match="metric id order"):
        build_retired_release(baseline, reversed_decision)
