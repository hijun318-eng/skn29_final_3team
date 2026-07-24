"""RBAC 데코레이터 모듈.

뷰 함수에 역할·범위 기반 접근 통제를 적용한다.

- @require_role(role_code): 세션의 역할이 지정 역할과 일치하는지 확인
- @require_scope(metric_groups): 세션의 scope_snapshot이 지 metric 그룹을 허용하는지 확인

데코레이터 실패 시 표준 에velope 형식의 JSON 응답을 반환한다.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, JsonResponse


def _get_role_code(request: HttpRequest) -> str | None:
    """세션에서 역할 코드를 추출한다."""
    return request.session.get("role_code")


def _get_scope_snapshot(request: HttpRequest) -> dict[str, Any] | None:
    """세션에서 scope_snapshot을 추출한다."""
    return request.session.get("scope_snapshot")


def _unauthenticated_response() -> JsonResponse:
    """401 미인증 응답."""
    return JsonResponse(
        {
            "data": None,
            "meta": {},
            "error": {
                "code": "NOT_AUTHENTICATED",
                "message": "로그인이 필요합니다.",
                "details": [],
            },
        },
        status=401,
    )


def _forbidden_response(detail: str = "") -> JsonResponse:
    """403 권한 없음 응답."""
    return JsonResponse(
        {
            "data": None,
            "meta": {},
            "error": {
                "code": "FORBIDDEN",
                "message": "접근 권한이 없습니다.",
                "details": [detail] if detail else [],
            },
        },
        status=403,
    )


def require_role(*allowed_role_codes: str) -> Callable:
    """뷰 함수에 역할 기반 접근 통제를 적용하는 데코레이터.

    Args:
        allowed_role_codes: 허용된 역할 코드 목록.
            예: @require_role("OPERATIONS_MANAGER")
            예: @require_role("OPERATIONS_MANAGER", "FACILITY_MANAGER")

    Usage:
        @require_role("OPERATIONS_MANAGER")
        def admin_view(request):
            ...
    """

    def decorator(view_func: Callable) -> Callable:
        @functools.wraps(view_func)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
            role_code = _get_role_code(request)
            if role_code is None:
                return _unauthenticated_response()
            if role_code not in allowed_role_codes:
                return _forbidden_response(
                    f"필요 역할: {', '.join(allowed_role_codes)}"
                )
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def require_scope(metric_groups: list[str] | None = None) -> Callable:
    """뷰 함수에 스코프 기반 접근 통제를 적용하는 데코레이터.

    Args:
        metric_groups: 필요한 metric_group 목록.
            지정된 metric_group이 scope_snapshot에 모두 포함되어야 한다.
            None이면 metric_group 검사를 건너뛴다.

    Usage:
        @require_scope(metric_groups=["BREAKFAST", "FNB_VOC"])
        def fnb_view(request):
            ...

        @require_scope()
        def any_view(request):
            ...
    """

    def decorator(view_func: Callable) -> Callable:
        @functools.wraps(view_func)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
            role_code = _get_role_code(request)
            if role_code is None:
                return _unauthenticated_response()

            scope_snapshot = _get_scope_snapshot(request)
            if scope_snapshot is None:
                return _forbidden_response("scope_snapshot이 없습니다.")

            if metric_groups:
                allowed = set(scope_snapshot.get("metric_groups", []))
                required = set(metric_groups)
                missing = required - allowed
                if missing:
                    return _forbidden_response(
                        f"필요 metric_groups: {', '.join(sorted(missing))}"
                    )

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
