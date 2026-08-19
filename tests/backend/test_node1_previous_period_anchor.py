"""Node1 요청의 대화 앵커(`previous_period`) 계약과 생성 규칙 검증.

질문 문장의 시간 해석은 Node1이 소유하지만, 직전 턴 기간은 Node1의 정보 집합에 없다.
이 테스트는 그 앵커가 (1) 계약상 허용된 형태로 존재하고 (2) 저장된 슬롯에서 실제로
생성되며 (3) 형식이 깨진 값은 앵커로 승격되지 않음을 확인한다.
"""

from __future__ import annotations

from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.contracts import ResolvedSlots  # noqa: E402
from app.services.context.model_time_context import previous_period_anchor  # noqa: E402
from src.ai.schema import ContractError, validate_payload  # noqa: E402

SEOUL = ZoneInfo("Asia/Seoul")


def _node1_request(**overrides: object) -> dict[str, object]:
    """계약을 만족하는 최소 node1_request를 만들고 지정한 키만 덮어쓴다."""
    request: dict[str, object] = {
        "question": "그 전 달은?",
        "role_hint": "hotel_analyst",
        "as_of": "2026-08-19T00:00:00+09:00",
        "timezone": "Asia/Seoul",
        "calendar_id": "gregorian",
        "allowed_routes": ["general", "template"],
        "business_terms": {"room_revenue": {"kind": "metric", "aliases": ["객실 매출"]}},
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
