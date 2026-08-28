"""Metric 검토안이 기존 공개 기능을 조용히 제거하지 못하는 전환 gate를 검증한다."""

from __future__ import annotations

import asyncio
import sys
from argparse import Namespace
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(DATAHUB), str(ROOT / "tests" / "data")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from metadata_contract_primitives import SemanticMetadataError  # noqa: E402
from metric_review_contract import validate_metric_review  # noqa: E402
from metric_review_transition import (  # noqa: E402
    DEPRECATION_REVIEW_STATUS,
    READY_STATUS,
    plan_metric_review_transition,
)
from test_metric_governance_v2 import _v2_bundle  # noqa: E402
from test_metric_review_contract import _candidate, _column, _evidence  # noqa: E402
import check_metric_review_transition as transition_check  # noqa: E402


def _candidate_with_account_count() -> dict[str, object]:
    """현재 baseline의 추가 BUSINESS Metric까지 명시적으로 검토한 임의 후보를 만든다."""

    candidate = _candidate()
    account_count = _column("account_count", "events")
    account_count.update(
        {
            "name": "Account Count",
            "visibility": "BUSINESS",
            "definition": "Distinct approved accounts in the selected arbitrary scope.",
            "aliases": ["account count alias"],
        }
    )
    candidate["business_metric_target_count"] = 2
    candidate["metrics"].append(account_count)
    return candidate


def test_transition_blocks_implicit_removal_of_a_live_business_metric() -> None:
    """후보에 없는 기존 BUSINESS Metric은 승인된 폐기로 간주하지 않는다."""

    candidate = _candidate()
    validation = validate_metric_review(candidate, _evidence())

    result = plan_metric_review_transition(candidate, validation, _v2_bundle())

    assert result["status"] == DEPRECATION_REVIEW_STATUS
    assert result["retained_business_metric_ids"] == ["amount_per_event"]
    assert result["retirement_candidate_ids"] == ["account_count"]
    assert result["publishable"] is False


def test_transition_is_ready_only_when_all_live_business_metrics_are_reviewed() -> None:
    """기존 공개 ID가 모두 BUSINESS 후보에 남아 있을 때만 다음 정책 결정을 허용한다."""

    candidate = _candidate_with_account_count()
    validation = validate_metric_review(candidate, _evidence())

    result = plan_metric_review_transition(candidate, validation, _v2_bundle())

    assert result["status"] == READY_STATUS
    assert result["retained_business_metric_ids"] == [
        "account_count",
        "amount_per_event",
    ]
    assert result["retirement_candidate_ids"] == []
    assert result["approval_status"] == "NOT_APPROVED"


def test_transition_reports_business_to_support_as_a_visibility_regression() -> None:
    """동일 ID를 내부 SUPPORT로 숨기는 변경도 공개 기능 폐기 후보로 표시한다."""

    candidate = _candidate_with_account_count()
    ratio = next(
        item for item in candidate["metrics"] if item["id"] == "amount_per_event"
    )
    ratio["visibility"] = "SUPPORT"
    candidate["business_metric_target_count"] = 1
    validation = validate_metric_review(candidate, _evidence())

    result = plan_metric_review_transition(candidate, validation, _v2_bundle())

    assert result["status"] == DEPRECATION_REVIEW_STATUS
    assert result["visibility_change_candidate_ids"] == ["amount_per_event"]
    assert "amount_per_event" in result["retirement_candidate_ids"]


def test_transition_rejects_a_validation_receipt_for_different_content() -> None:
    """후보 수정 뒤 과거 VALID 결과를 재사용해 change gate를 우회하지 못하게 한다."""

    candidate = _candidate()
    validation = deepcopy(validate_metric_review(candidate, _evidence()))
    validation["candidate_sha256"] = "0" * 64

    with pytest.raises(SemanticMetadataError, match="does not match"):
        plan_metric_review_transition(candidate, validation, _v2_bundle())


def test_live_transition_uses_active_manifest_when_ungoverned_candidates_exist(
    monkeypatch,
) -> None:
    """후속 base-ingested asset이 있어도 검토 baseline은 active manifest로 고정한다."""

    candidate = _candidate_with_account_count()
    baseline = _v2_bundle()
    calls = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    async def active(scopes, trino, datahub):
        calls.append((scopes, trino, datahub))
        return baseline

    monkeypatch.setattr(transition_check, "build_draft", lambda *_args: _evidence())
    monkeypatch.setattr(
        transition_check,
        "load_release_scopes_with_serving",
        lambda *_args, **_kwargs: (
            SimpleNamespace(catalog="serving", schema="sample"),
        ),
    )
    monkeypatch.setattr(transition_check, "TrinoMetadataClient", FakeClient)
    monkeypatch.setattr(transition_check, "DataHubDiscoveryClient", FakeClient)
    monkeypatch.setattr(transition_check, "build_active_release_bundle", active)
    monkeypatch.setattr(
        transition_check.DataHubConnectionSettings,
        "from_env",
        lambda: SimpleNamespace(
            base_url="https://datahub.test",
            token="read-token",
            ca_file=Path("datahub-ca.pem"),
        ),
    )
    monkeypatch.setenv("TRINO_DATAHUB_PASSWORD", "test-password")

    validation, observed, result = asyncio.run(
        transition_check.load_live_review_context(
            candidate,
            Namespace(
                sql_directory=Path("unused"),
                recipe_dir=Path("unused"),
                serving_schema="sample",
                trino_server="https://trino.test",
                trino_user="metadata-reader",
                trino_ca_file=Path("trino-ca.pem"),
                timeout=5.0,
            ),
        )
    )

    assert validation["status"] == "VALID_REVIEW_DRAFT"
    assert observed is baseline
    assert result["status"] == READY_STATUS
    assert len(calls) == 1
