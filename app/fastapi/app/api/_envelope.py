"""API 응답 envelope 유틸리티.

AIC v2.0 §2의 {data, meta, error} envelope를 생성하는 헬퍼 함수.
모든 내부 API 엔드포인트가 이 모듈을 통해 일관된 응답 형식을 보장한다.

References:
    - docs/markdown/ai_docs/03_api_ai_integration_contract.md §2
    - src/common/contracts.py (APIResponse, ResponseMeta, ErrorDetail)
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from src.common.contracts import APIResponse, ErrorDetail, ResponseMeta

# 요청 시작 시간 추적용 (요청별 duration_ms 계산)
_REQUEST_START: dict[str, float] = {}


def new_request_id() -> str:
    """UUID v4 요청 식별자를 생성한다."""
    return str(uuid.uuid4())


def start_timer(request_id: str) -> None:
    """요청 처리 시작 시각을 기록한다."""
    _REQUEST_START[request_id] = time.monotonic()


def elapsed_ms(request_id: str) -> float:
    """요청 처리 소요 시간(밀리초)을 반환한다."""
    start = _REQUEST_START.pop(request_id, time.monotonic())
    return round((time.monotonic() - start) * 1000, 2)


def ok(data: Any, request_id: str | None = None) -> dict[str, Any]:
    """성공 envelope를 생성한다.

    Args:
        data: 응답 본문
        request_id: 요청 고유 식별자. None이면 자동 생성.

    Returns:
        {data, meta, error} 딕셔너리
    """
    rid = request_id or new_request_id()
    meta = ResponseMeta(
        request_id=rid,
        timestamp=datetime.now(timezone.utc).isoformat(),
        duration_ms=elapsed_ms(rid),
    )
    return APIResponse(data=data, meta=meta, error=None).model_dump()


def error(
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
    status_code: int = 400,
) -> tuple[dict[str, Any], int]:
    """오류 envelope를 생성한다.

    Args:
        code: ErrorCode 상수값
        message: 사용자 메시지
        details: 필드별 오류 상세
        request_id: 요청 고유 식별자
        status_code: HTTP 상태 코드

    Returns:
        ({data, meta, error} 딕셔너리, HTTP 상태 코드) 튜플
    """
    rid = request_id or new_request_id()
    meta = ResponseMeta(
        request_id=rid,
        timestamp=datetime.now(timezone.utc).isoformat(),
        duration_ms=elapsed_ms(rid),
    )
    body = APIResponse(
        data=None,
        meta=meta,
        error=ErrorDetail(code=code, message=message, detail=details),
    ).model_dump()
    return body, status_code
