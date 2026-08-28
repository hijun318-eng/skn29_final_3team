"""V4.3 P0 Gold draft와 generic 반복 평가 계약의 fail-closed 동작을 검증한다."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from evals.p0_gold import P0GoldError, canonical_sha256, validate_manifest
from evals.p0_gold_runner import _case_path
from evals.p0_gold_scoring import evaluate_observations


ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "evals" / "p0_gold"
MANIFEST_PATH = GOLD / "answervice_v4_3.p0.draft.v1.manifest.json"
CASE_PATH = GOLD / "answervice_v4_3.p0.draft.v1.jsonl"
V2_MANIFEST_PATH = GOLD / "answervice_v4_3.p0.candidate.v2.manifest.json"
V2_CASE_PATH = GOLD / "answervice_v4_3.p0.candidate.v2.jsonl"
CANDIDATE_PATH = (
    ROOT / "evals" / "semantic_review" / "answervice_d2_metrics.v1.json"
)


def _json(path: Path) -> object:
    """테스트 fixture JSON을 UTF-8로 읽는다."""

    return json.loads(path.read_text(encoding="utf-8"))


def _cases() -> list[dict]:
    """빈 줄이 없는 실제 draft JSONL을 case 목록으로 읽는다."""

    return [json.loads(line) for line in CASE_PATH.read_text(encoding="utf-8").splitlines()]


def _summary(manifest=None, cases=None, candidate=None):
    """실제 파일 SHA를 사용해 contract validator를 호출한다."""

    payload = CASE_PATH.read_bytes()
    return validate_manifest(
        manifest if manifest is not None else _json(MANIFEST_PATH),
        cases if cases is not None else _cases(),
        candidate if candidate is not None else _json(CANDIDATE_PATH),
        observed_case_content_sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_real_v43_gold_bundle_is_valid_but_not_scorable() -> None:
    """30/15/10과 D2 대표 질문은 갖추되 미승인 상태를 성공 수치로 만들지 않는다."""

    result = _summary()

    assert result["status"] == "VALID_DRAFT"
    assert result["case_counts"] == {
        "MULTI_TURN": 10,
        "SAFETY": 15,
        "STRUCTURED": 30,
    }
    assert result["representative_question_count"] == 20
    assert result["blocked_case_count"] == 5
    assert result["review_counts"] == {"BLOCKED": 5, "REVIEW_REQUIRED": 50}
    assert result["scorable"] is False


def test_corrected_v2_candidate_is_approved_but_requires_release_binding() -> None:
    """교정 v2는 승인됐지만 external same-release seal 전에는 채점하지 않는다."""

    payload = V2_CASE_PATH.read_bytes()
    cases = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    result = validate_manifest(
        _json(V2_MANIFEST_PATH),
        cases,
        _json(CANDIDATE_PATH),
        observed_case_content_sha256=hashlib.sha256(payload).hexdigest(),
    )

    assert result["status"] == "VALID_DRAFT"
    assert result["case_counts"] == {
        "MULTI_TURN": 10,
        "SAFETY": 15,
        "STRUCTURED": 30,
    }
    assert result["blocked_case_count"] == 0
    assert result["unsealed_result_count"] == 0
    assert result["review_counts"] == {"APPROVED": 55}
    assert result["scorable"] is False


def test_semantic_candidate_change_invalidates_gold_binding() -> None:
    """Metric 정의가 한 글자라도 바뀌면 기존 Gold draft를 재사용하지 않는다."""

    candidate = copy.deepcopy(_json(CANDIDATE_PATH))
    candidate["metrics"][0]["definition"] += " changed"

    with pytest.raises(P0GoldError, match="not bound"):
        _summary(candidate=candidate)


def test_required_scenario_coverage_cannot_be_removed() -> None:
    """문서의 필수 slice를 case 수만 채운 채 누락하는 것을 차단한다."""

    cases = _cases()
    for case in cases:
        case["scenario_tags"] = [
            tag for tag in case["scenario_tags"] if tag != "EVENT_TIME"
        ]

    with pytest.raises(P0GoldError, match="missing tags"):
        _summary(cases=cases)


def test_blocked_semantic_gap_cannot_be_disguised_as_approved() -> None:
    """blocker가 남은 case에 reviewer만 붙여 승인으로 위장하지 못하게 한다."""

    cases = _cases()
    blocked = next(case for case in cases if case["review_status"] == "BLOCKED")
    blocked["review_status"] = "APPROVED"
    blocked["reviewer"] = "urn:li:corpGroup:reviewer"
    blocked["reviewed_at"] = "2026-08-19T18:00:00+09:00"

    with pytest.raises(P0GoldError, match="only blocked"):
        _summary(cases=cases)


def test_draft_observations_are_never_scored() -> None:
    """실행 관측이 있더라도 semantic/Gold가 봉인되기 전에는 정확도를 계산하지 않는다."""

    with pytest.raises(P0GoldError, match="cannot be scored"):
        evaluate_observations(_cases(), _summary(), [], repeat=1)


def test_case_file_path_cannot_escape_manifest_directory(tmp_path: Path) -> None:
    """manifest의 상대 경로가 상위 디렉터리 파일을 읽지 못하게 한다."""

    manifest = tmp_path / "bundle" / "manifest.json"
    manifest.parent.mkdir()

    with pytest.raises(P0GoldError, match="sibling filename"):
        _case_path(manifest, {"case_file": "../outside.jsonl"})


def test_case_file_path_cannot_select_a_nested_bundle(tmp_path: Path) -> None:
    """검토 manifest가 같은 디렉터리의 다른 하위 bundle을 암묵적으로 선택하지 못하게 한다."""

    manifest = tmp_path / "bundle" / "manifest.json"
    manifest.parent.mkdir()

    with pytest.raises(P0GoldError, match="sibling filename"):
        _case_path(manifest, {"case_file": "nested/cases.jsonl"})


def test_sealed_observation_scoring_is_repeat_aware() -> None:
    """정규화 결과 두 회가 모두 Gold와 같을 때만 통과·재현성을 함께 인정한다."""

    case = _scoring_case()
    output = _matching_output(case)
    observations = [
        {"case_id": case["case_id"], "attempt": 1, "latency_ms": 10, "output": output},
        {"case_id": case["case_id"], "attempt": 2, "latency_ms": 20, "output": output},
    ]

    result = evaluate_observations(
        [case],
        {"scorable": True, "manifest_sha256": "a" * 64},
        observations,
        repeat=2,
    )

    assert result["accuracy"] == 1.0
    assert result["deterministic"] == 1
    assert result["p50_ms"] == 15
    assert result["p95_ms"] == 20


def test_observation_requires_every_repeat_exactly_once() -> None:
    """repeat 누락이나 중복으로 선택적인 성공 case만 제출하지 못하게 한다."""

    case = _scoring_case()
    observation = {
        "case_id": case["case_id"],
        "attempt": 1,
        "latency_ms": 10,
        "output": _matching_output(case),
    }

    with pytest.raises(P0GoldError, match="exactly one observation"):
        evaluate_observations(
            [case],
            {"scorable": True, "manifest_sha256": "a" * 64},
            [observation],
            repeat=2,
        )


def _scoring_case() -> dict:
    """scoring 로직만 격리해 검증할 최소 봉인 case를 만든다."""

    resolved = {
        "business_terms": ["객실 매출"],
        "metric_ids": ["room_revenue"],
        "dimensions": [],
        "period": {"start": "2025-08-01", "end_exclusive": "2025-09-01"},
        "grain": "month",
        "time_rule": "BUSINESS_DATE:[start,end)",
        "operations": [],
        "chart_type": "SUMMARY",
    }
    result = {"rows": [{"month": "2025-08", "value": 1}]}
    return {
        "case_id": "P0-S-999",
        "category": "STRUCTURED",
        "expected_route": "ANALYSIS",
        "expected_resolved_request": resolved,
        "expected_query_strategy": "VIEW_REUSE",
        "expected_assets": ["serving.analytics_v4_3.hotel_operations_daily"],
        "expected_join_ids": [],
        "allow_or_block": "ALLOW",
        "expected_error_code": None,
        "expected_result": {
            "kind": "HASH",
            "sha256": canonical_sha256(result),
            "value": None,
            "absolute_tolerance": None,
        },
        "_result_fixture": result,
    }


def _matching_output(case: dict) -> dict:
    """case 기대값을 observation 정규화 schema로 투영한다."""

    return {
        "route": case["expected_route"],
        "resolved_request": case["expected_resolved_request"],
        "query_strategy": case["expected_query_strategy"],
        "assets": case["expected_assets"],
        "join_ids": case["expected_join_ids"],
        "allow_or_block": case["allow_or_block"],
        "error_code": case["expected_error_code"],
        "result": case["_result_fixture"],
    }
