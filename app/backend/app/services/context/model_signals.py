"""모델이 반환한 열거형 신호를 서버 허용 집합으로 좁히는 모듈.

[핵심 목적]
Node1은 대화 라우트와 표현 타입을 후보로 제시할 수 있지만, 실행 권한을 갖지 않는다.
이 모듈은 그 신호가 계약에 선언된 값인지만 판정해 하류로 넘긴다. 라우트 확정과 전제조건
검증은 `app.services.conversation.slot_resolver`가 소유한다.

[경계]
schema가 이미 enum을 강제하지만, 이 값이 라우팅 분기에 쓰이므로 코드에서도 한 번 더
좁힌다. 허용 밖 값은 예외가 아니라 "신호 없음"으로 낮춰 서버 기본 경로가 적용되게 한다.
"""

from __future__ import annotations

CONVERSATION_ROUTES = frozenset({"ANALYSIS", "PRESENTATION", "REPORT_ACTION"})
PRESENTATION_TYPES = frozenset(
    {
        "SUMMARY",
        "KPI",
        "TABLE",
        "BAR",
        "LINE",
        "PIE",
        "HORIZONTAL_BAR",
        "DONUT",
        "FULL",
    }
)


def enum_signal(value: object, allowed: frozenset[str]) -> str | None:
    """모델이 반환한 열거형 신호를 허용 집합 안에서만 통과시킵니다.

    Args:
        value: 모델이 반환한 원본 값
        allowed: 통과를 허용할 열거형 문자열 집합

    Returns:
        허용 집합에 속하는 문자열, 그 외에는 None
    """
    return value if isinstance(value, str) and value in allowed else None


def client_action_signals(payload: dict[str, object]) -> dict[str, str]:
    """클라이언트가 보낸 typed action을 계약 enum 안의 신호로만 정규화합니다.

    UI가 이미 아는 동작(차트 전환·보고서 담기)은 자연어 문장으로 바꿔 다시 해석시키지
    않고 그대로 전달한다. 다만 클라이언트 입력도 모델 출력과 똑같이 후보일 뿐이므로,
    허용 집합 밖 값은 신호 없음으로 낮추고 재사용 가능 여부는 상위 라우팅 계약이 다시
    확인한다.

    Args:
        payload: 대화 command 요청 payload

    Returns:
        허용된 신호만 담은 딕셔너리(없으면 빈 딕셔너리)
    """
    signals: dict[str, str] = {}
    route = enum_signal(payload.get("requested_route"), CONVERSATION_ROUTES)
    if route is not None:
        signals["requested_route"] = route
    presentation = enum_signal(payload.get("presentation_type"), PRESENTATION_TYPES)
    if presentation is not None:
        signals["presentation_type"] = presentation
    return signals
