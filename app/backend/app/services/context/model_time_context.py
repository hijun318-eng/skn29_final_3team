"""Node1 요청에 실리는 권위 시간 컨텍스트 조립 모듈.

[핵심 목적]
질문 문장의 시간 표현 해석은 Node1이 소유하지만, 직전 턴에서 확정된 기간은 Node1의
입력에 기본으로 존재하지 않는다. 이 모듈은 저장된 슬롯의 기간을 `node1_request` 계약이
요구하는 `previous_period` 앵커(RFC 3339 반개구간)로 승격해, "그 전 달"처럼 앵커가 직전
기간인 표현까지 Node1이 한 곳에서 해석할 수 있게 한다.

[경계]
여기서는 앵커의 형식 적합성만 판단한다. 앵커를 실제로 어떻게 적용할지는 Node1 prompt
계약이, 반환된 후보의 확정은 `app.services.conversation.time_algebra`가 소유한다.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def previous_period_anchor(
    resolved_slots: object,
    timezone: ZoneInfo,
) -> dict[str, str] | None:
    """직전 턴 기간을 Node1 요청의 `previous_period` 앵커로 변환합니다.

    저장된 슬롯은 타임존이 없는 날짜 문자열이므로 계약이 요구하는 RFC 3339 형태로
    올린다. 두 경계가 모두 존재하고 start < end_exclusive인 경우에만 앵커를 만들며,
    형식이 깨진 값은 Node1에 잘못된 시간 컨텍스트를 주입하지 않도록 ``None``으로 닫는다.

    Args:
        resolved_slots: 직전 턴에서 상속된 typed 슬롯(없으면 None)
        timezone: 요청 컨텍스트가 소유한 타임존

    Returns:
        `previous_period` 계약 객체, 또는 앵커를 만들 수 없으면 None
    """
    start_text = getattr(resolved_slots, "period_start", None)
    end_text = getattr(resolved_slots, "period_end_exclusive", None)
    if not start_text or not end_text:
        return None
    try:
        start = datetime.fromisoformat(str(start_text))
        end = datetime.fromisoformat(str(end_text))
    except (TypeError, ValueError):
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone)
    if start >= end:
        return None
    return {"start": start.isoformat(), "end_exclusive": end.isoformat()}
