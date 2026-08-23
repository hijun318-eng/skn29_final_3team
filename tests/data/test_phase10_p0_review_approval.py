"""Phase 10의 명시적 semantic·Gold 승인 범위를 fail-closed 검증한다."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from evals.p0_gold import canonical_sha256
from infrastructure.acceptance import phase10_p0_review_approval as approval


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _cases():
    return [
        json.loads(line)
        for line in approval.GOLD_CASE_PATH.read_text(encoding="utf-8").splitlines()
    ]


def _preapproval():
    """현재 승인 artifact에서 도구 입력의 immutable preapproval 표현을 복원한다."""

    semantic = _json(approval.SEMANTIC_PATH)
    semantic.pop("reviewer", None)
    semantic.pop("reviewed_at", None)
    semantic["review_status"] = "REVIEW_REQUIRED"
    for metric in semantic["metrics"]:
        metric["review_status"] = "REVIEW_REQUIRED"
    cases = _cases()
    for case in cases:
        case.update(
            {
                "review_status": "REVIEW_REQUIRED",
                "reviewer": None,
                "reviewed_at": None,
            }
        )
    manifest = _json(approval.GOLD_MANIFEST_PATH)
    manifest.update(
        {
            "semantic_candidate_sha256": approval.ORIGINAL_SEMANTIC_SHA256,
            "case_content_sha256": approval.ORIGINAL_CASE_SHA256,
        }
    )
    manifest["provenance"]["notes"] = (
        "Corrected v2 candidate with independent read-only Trino result oracles; "
        "final reviewer approval and release binding remain required."
    )
    return semantic, manifest, cases


def test_exact_candidates_become_approved_but_not_release_sealed() -> None:
    """사람 승인은 내용 상태만 바꾸고 아직 모르는 product ID를 source에 쓰지 않는다."""

    source_semantic, source_manifest, source_cases = _preapproval()
    semantic, manifest, cases = approval.approve_documents(
        source_semantic,
        source_manifest,
        source_cases,
        reviewed_at="2026-08-23T12:34:56+09:00",
    )

    assert semantic["review_status"] == "APPROVED"
    assert semantic["reviewer"] == approval.REVIEWER
    assert {item["review_status"] for item in semantic["metrics"]} == {"APPROVED"}
    assert {case["review_status"] for case in cases} == {"APPROVED"}
    assert {case["reviewer"] for case in cases} == {approval.REVIEWER}
    assert manifest["status"] == "DRAFT"
    assert manifest["semantic_release_id"] is None
    assert manifest["product_release_id"] is None
    assert manifest["semantic_candidate_sha256"] == canonical_sha256(semantic)


def test_candidate_content_change_cannot_be_hidden_by_the_approval() -> None:
    """승인 전 정의나 결과 assertion이 바뀌면 승인 도구가 즉시 거부한다."""

    semantic, manifest, cases = _preapproval()
    semantic["metrics"][0]["definition"] += " changed"
    with pytest.raises(approval.Phase10ReviewApprovalError, match="semantic"):
        approval.approve_documents(
            semantic,
            manifest,
            cases,
            reviewed_at="2026-08-23T12:34:56+09:00",
        )

    semantic, manifest, cases = _preapproval()
    changed = deepcopy(cases)
    changed[0]["expected_result"]["value"] += 1
    with pytest.raises(approval.Phase10ReviewApprovalError, match="Gold"):
        approval.approve_documents(
            semantic,
            manifest,
            changed,
            reviewed_at="2026-08-23T12:34:56+09:00",
        )
