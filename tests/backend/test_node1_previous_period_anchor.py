"""Node1 요청의 typed 대화 컨텍스트 계약과 생성 규칙 검증.

질문 문장의 시간 해석은 Node1이 소유하지만, 직전 턴 기간은 Node1의 정보 집합에 없다.
직전 결과 형태도 현재 발화가 이를 유지하는지 교체하는지를 판정하는 최소 문맥이다. 이
테스트는 두 컨텍스트가 공개 계약을 통과하고 저장 슬롯에서 안전하게 생성되는지 확인한다.
"""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.contracts import ResolvedSlots  # noqa: E402
from app.services.context.model_time_context import (  # noqa: E402
    previous_period_anchor,
    previous_result_shape,
)
from src.ai.schema import ContractError, validate_payload  # noqa: E402
from tests.ai.test_contracts import NODE1_INTERPRETATION_CONTEXT  # noqa: E402

SEOUL = ZoneInfo("Asia/Seoul")
RESULT_SHAPE = {
    "analysis_operation": "breakdown",
    "analysis_time_bucket": None,
    "dimension_count": 1,
    "result_limit": None,
}


def _node1_request(**overrides: object) -> dict[str, object]:
    """계약을 만족하는 최소 node1_request를 만들고 지정한 키만 덮어쓴다."""
    request: dict[str, object] = {
        "question": "그 전 달은?",
        "role_hint": "analyst",
        "as_of": "2026-08-19T00:00:00+09:00",
        "timezone": "Asia/Seoul",
        "calendar_id": "gregorian",
        "allowed_routes": ["general", "template"],
        "business_terms": {"room_revenue": {"kind": "metric", "aliases": ["객실 매출"]}},
        "interpretation_context": NODE1_INTERPRETATION_CONTEXT,
    }
    request.update(overrides)
    return request


def test_contract_accepts_previous_period_anchor():
    """대화 앵커가 실린 요청이 node1_request 계약을 통과하는지 검증."""
    validate_payload(
        "node1_request",
        _node1_request(
            previous_period={
                "start": "2025-08-01T00:00:00+09:00",
                "end_exclusive": "2025-09-01T00:00:00+09:00",
            }
        ),
    )


def test_contract_still_accepts_request_without_anchor():
    """첫 턴처럼 앵커가 없는 요청도 계약을 통과해야 한다(앵커는 선택 항목)."""
    validate_payload("node1_request", _node1_request())


def test_contract_accepts_previous_result_shape():
    """직전 결과 형태가 자유 문장이 아닌 최소 typed 객체로만 전달되는지 검증."""

    validate_payload(
        "node1_request",
        _node1_request(previous_result_shape=dict(RESULT_SHAPE)),
    )


@pytest.mark.parametrize("target", ["period_candidates", "analysis_operation"])
def test_contract_accepts_one_bounded_interpretation_recheck(target):
    """서버가 요청하는 슬롯 재검토가 대상과 회차가 고정된 typed 객체인지 검증."""

    validate_payload(
        "node1_request",
        _node1_request(
            interpretation_recheck={
                "target": target,
                "attempt": 1,
            }
        ),
    )


@pytest.mark.parametrize(
    "recheck",
    [
        {"target": "period_candidates"},
        {"target": "metric_candidates", "attempt": 1},
        {"target": "period_candidates", "attempt": 2},
        {"target": "period_candidates", "attempt": 1, "force": True},
    ],
    ids=["missing_attempt", "unknown_target", "second_retry", "extra_directive"],
)
def test_contract_rejects_unbounded_or_unknown_interpretation_recheck(recheck):
    """모델 재검토가 반복되거나 다른 슬롯을 임의로 강제할 수 없도록 닫는다."""

    with pytest.raises(ContractError):
        validate_payload(
            "node1_request",
            _node1_request(interpretation_recheck=recheck),
        )


@pytest.mark.parametrize(
    "shape",
    [
        {
            "analysis_operation": "breakdown",
            "dimension_count": 1,
            "result_limit": None,
        },
        {**RESULT_SHAPE, "dimension_id": "hotel_code"},
        {**RESULT_SHAPE, "analysis_operation": "raw_sql"},
        {**RESULT_SHAPE, "dimension_count": 61},
    ],
    ids=["missing_time_bucket", "physical_dimension_leak", "unknown_operation", "too_many_dimensions"],
)
def test_contract_rejects_malformed_previous_result_shape(shape):
    """물리 식별자나 계약 밖 결과 형태가 Node1 요청에 섞이면 닫히는지 검증."""

    with pytest.raises(ContractError):
        validate_payload(
            "node1_request",
            _node1_request(previous_result_shape=shape),
        )


@pytest.mark.parametrize(
    "anchor",
    [
        {"start": "2025-08-01T00:00:00+09:00"},
        {"start": "2025-08-01T00:00:00+09:00", "end_exclusive": "2025-09-01T00:00:00+09:00", "label": "8월"},
        {"start": "not-a-timestamp", "end_exclusive": "2025-09-01T00:00:00+09:00"},
    ],
    ids=["missing_end", "extra_property", "unparsable_start"],
)
def test_contract_rejects_malformed_anchor(anchor):
    """앵커가 자유 형식으로 새지 않도록 계약이 잘못된 형태를 거부하는지 검증."""
    with pytest.raises(ContractError):
        validate_payload("node1_request", _node1_request(previous_period=anchor))


def test_anchor_is_built_from_stored_slots_and_lifted_to_context_timezone():
    """저장된 날짜 문자열이 컨텍스트 타임존을 가진 RFC 3339 앵커로 승격되는지 검증."""
    anchor = previous_period_anchor(
        ResolvedSlots(period_start="2025-08-01", period_end_exclusive="2025-09-01"),
        SEOUL,
    )

    assert anchor == {
        "start": "2025-08-01T00:00:00+09:00",
        "end_exclusive": "2025-09-01T00:00:00+09:00",
    }
    validate_payload("node1_request", _node1_request(previous_period=anchor))


def test_result_shape_is_built_without_metric_or_physical_dimension_values():
    """저장 슬롯에서는 형태 판정에 필요한 개수와 연산만 Node1 컨텍스트로 승격한다."""

    shape = previous_result_shape(
        ResolvedSlots(
            dimension_ids=("hotel_code",),
            analysis_operation="breakdown",
        )
    )

    assert shape == RESULT_SHAPE
    validate_payload("node1_request", _node1_request(previous_result_shape=shape))


@pytest.mark.parametrize(
    "slots",
    [
        None,
        ResolvedSlots(),
        SimpleNamespace(analysis_operation="raw_sql", dimension_ids=(), result_limit=None),
        SimpleNamespace(
            analysis_operation="breakdown",
            dimension_ids=("hotel_code", "hotel_code"),
            result_limit=None,
        ),
        SimpleNamespace(
            analysis_operation="aggregate",
            dimension_ids=(),
            result_limit=3,
        ),
    ],
    ids=["no_slots", "empty", "unknown_operation", "duplicate_dimensions", "invalid_limit"],
)
def test_unusable_slots_do_not_produce_a_result_shape(slots):
    """저장 상태가 결과 형태 계약을 어기면 일부 값을 모델에 전달하지 않는다."""

    assert previous_result_shape(slots) is None


@pytest.mark.parametrize(
    "slots",
    [
        None,
        ResolvedSlots(),
        ResolvedSlots(period_start="2025-08-01"),
        ResolvedSlots(period_start="2025-09-01", period_end_exclusive="2025-08-01"),
        ResolvedSlots(period_start="8월", period_end_exclusive="9월"),
    ],
    ids=["no_slots", "empty", "half_open_missing_end", "inverted", "unparsable"],
)
def test_unusable_slots_do_not_produce_an_anchor(slots):
    """앵커를 만들 수 없는 입력은 Node1에 잘못된 시간 컨텍스트를 주입하지 않아야 한다."""
    assert previous_period_anchor(slots, SEOUL) is None
