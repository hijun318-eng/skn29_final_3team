"""Node1 요청에 실리는 권위 대화 컨텍스트 조립 모듈.

[핵심 목적]
질문 문장의 시간 표현 해석은 Node1이 소유하지만, 직전 턴에서 확정된 기간은 Node1의
입력에 기본으로 존재하지 않는다. 이 모듈은 저장된 슬롯의 기간과 결과 형태를
`node1_request`의 `previous_period` 및 `previous_result_shape` 계약으로 승격해, 시간과
결과 형태의 후속 변경을 Node1이 한 곳에서 해석할 수 있게 한다.

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


def previous_result_shape(
    resolved_slots: object,
) -> dict[str, object] | None:
    """직전 확정 연산을 최소 권한의 Node1 결과 형태 컨텍스트로 변환한다.

    Metric ID, 필터 값, 물리 컬럼명은 모델에 다시 주입하지 않는다. 결과 형태 변경 판정에
    필요한 연산, 차원 개수, 순위 한도만 전달하며 저장 상태가 계약을 위반하면 ``None``으로
    닫는다.
    """

    operation = getattr(resolved_slots, "analysis_operation", None)
    operations = {
        "aggregate",
        "breakdown",
        "time_trend",
        "top_n",
        "bottom_n",
        "period_comparison",
    }
    if operation not in operations:
        return None
    raw_dimensions = getattr(resolved_slots, "dimension_ids", ()) or ()
    if not isinstance(raw_dimensions, (list, tuple)):
        return None
    dimensions = tuple(
        item for item in raw_dimensions if isinstance(item, str) and item
    )
    if (
        len(dimensions) != len(raw_dimensions)
        or len(dimensions) != len(set(dimensions))
        or len(dimensions) > 60
    ):
        return None
    result_limit = getattr(resolved_slots, "result_limit", None)
    if result_limit is not None and (
        operation not in {"top_n", "bottom_n"}
        or isinstance(result_limit, bool)
        or not isinstance(result_limit, int)
        or not 1 <= result_limit <= 100
    ):
        return None
    return {
        "analysis_operation": operation,
        "dimension_count": len(dimensions),
        "result_limit": result_limit,
    }
