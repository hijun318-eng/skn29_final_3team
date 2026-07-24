"""표준 응답 envelope 빌더.

AIC v2.0 §2의 {data, meta, error} 형식을 Django JsonResponse로 생성한다.
src/common/contracts.py의 ErrorCode 상수를 사용한다.

References:
    - docs/markdown/ai_docs/03_api_ai_integration_contract.md §2, §13
    - src/common/contracts.py
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from django.http import JsonResponse

from common.contracts import ErrorCode


def _now_iso() -> str:
    """ISO-8601 UTC 시각 문자열."""
    return datetime.now(timezone.utc).isoformat()


def _new_request_id() -> str:
    """요청 고유 식별자 UUID."""
    return str(uuid.uuid4())


def envelope_ok(
    data: Any,
    *,
    status: int = 200,
    meta_extra: dict[str, Any] | None = None,
    page: int | None = None,
    limit: int | None = None,
    total: int | None = None,
) -> JsonResponse:
    """성공 응답 envelope 생성.

    Args:
        data: 응답 본문
        status: HTTP 상태 코드
        meta_extra: meta에 추가할 커스텀 필드
        page: 현재 페이지 번호
        limit: 페이지당 항목 수
        total: 전체 항목 수
    """
    meta: dict[str, Any] = {
        "request_id": _new_request_id(),
        "timestamp": _now_iso(),
    }
    if page is not None:
        meta["page"] = page
    if limit is not None:
        meta["limit"] = limit
    if total is not None:
        meta["total"] = total
    if meta_extra:
        meta.update(meta_extra)

    return JsonResponse(
        {"data": data, "meta": meta, "error": None},
        status=status,
    )


def envelope_error(
    code: str,
    message: str,
    *,
    status: int = 400,
    details: list[dict[str, Any]] | None = None,
) -> JsonResponse:
    """오류 응답 envelope 생성.

    Args:
        code: ErrorCode 상수 값
        message: 사용자에게 노출되는 오류 메시지
        status: HTTP 상태 코드
        details: 필드별 오류 상세
    """
    meta: dict[str, Any] = {
        "request_id": _new_request_id(),
        "timestamp": _now_iso(),
    }

    error_payload: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details:
        error_payload["details"] = details

    return JsonResponse(
        {"data": None, "meta": meta, "error": error_payload},
        status=status,
    )


def error_validation(message: str = "요청값을 확인하세요.") -> JsonResponse:
    """400 VALIDATION_ERROR."""
    return envelope_error(
        ErrorCode.E_VALIDATION, message, status=400,
    )


def error_authentication(message: str = "로그인이 필요합니다.") -> JsonResponse:
    """401 AUTHENTICATION_REQUIRED."""
    return envelope_error(
        ErrorCode.E_AUTH, message, status=401,
    )


def error_forbidden(message: str = "접근 권한이 없습니다.") -> JsonResponse:
    """403 FORBIDDEN_SCOPE."""
    return envelope_error(
        ErrorCode.E_SCOPE, message, status=403,
    )


def error_not_found(message: str = "요청한 리소스를 찾을 수 없습니다.") -> JsonResponse:
    """404 NOT_FOUND."""
    return envelope_error(
        ErrorCode.E_NOTFOUND, message, status=404,
    )


def error_conflict(message: str = "버전 충돌이 발생했습니다.") -> JsonResponse:
    """409 VERSION_CONFLICT."""
    return envelope_error(
        ErrorCode.E_CONFLICT, message, status=409,
    )


def error_upstream(message: str = "상위 서비스 응답 시간이 초과되었습니다.") -> JsonResponse:
    """504 UPSTREAM_TIMEOUT."""
    return envelope_error(
        ErrorCode.E_UPSTREAM, message, status=504,
    )


def error_internal(message: str = "내부 서버 오류가 발생했습니다.") -> JsonResponse:
    """500 INTERNAL_ERROR."""
    return envelope_error(
        ErrorCode.E_INTERNAL, message, status=500,
    )
