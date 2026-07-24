"""SensePlace session 로그인/로그아웃 뷰.

데모 자격 3종을 지원한다:
- staff.ops / demo1234 → OPERATIONS_MANAGER
- staff.fac / demo1234 → FACILITY_MANAGER
- ext.review / demo1234 → EXTERNAL_REVIEWER

로그인 실패 5회 시 423 Locked 응답을 반환한다.
"""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth import login, logout
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from senseplace.auth.login_lockout import check_locked, record_failure, clear_failures
from senseplace.rbac.scope import build_scope_snapshot

# ---------------------------------------------------------------------------
# 데모 자격증명 저장소
# 프로젝트 초기 단계이므로 데모용 하드코딩.
# 실제 운영 시 Django User 모델 또는 외부 인증으로 대체한다.
# ---------------------------------------------------------------------------
_DEMO_CREDENTIALS: dict[str, dict[str, Any]] = {
    "staff.ops": {
        "password": "demo1234",
        "role_code": "OPERATIONS_MANAGER",
        "user_id": "ops-001",
        "display_name": "운영관리자",
    },
    "staff.fac": {
        "password": "demo1234",
        "role_code": "FACILITY_MANAGER",
        "user_id": "fac-001",
        "display_name": "시설관리자",
    },
    "ext.review": {
        "password": "demo1234",
        "role_code": "EXTERNAL_REVIEWER",
        "user_id": "rev-001",
        "display_name": "외부관계자",
    },
}


def _client_ip(request: HttpRequest) -> str:
    """요청에서 클라이언트 IP를 추출한다."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "0.0.0.0")


@csrf_exempt
@require_POST
def login_view(request: HttpRequest) -> JsonResponse:
    """세션 기반 로그인.

    Request body (JSON):
        {"username": "staff.ops", "password": "demo1234"}

    Returns:
        200: 로그인 성공, 세션에 사용자 정보 저장
        400: 필수 필드 누락
        401: 자격 증명 오류
        423: 로그인 시도 초과 (잠금)
    """
    ip = _client_ip(request)

    # 잠금 상태 확인
    if check_locked(ip):
        return JsonResponse(
            {
                "data": None,
                "meta": {},
                "error": {
                    "code": "LOCKED",
                    "message": "로그인 시도가 초과되었습니다. 잠시 후 다시 시도하세요.",
                    "details": [],
                },
            },
            status=423,
        )

    # 요청 파싱
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        body = {}

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        return JsonResponse(
            {
                "data": None,
                "meta": {},
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "username과 password를 입력하세요.",
                    "details": [],
                },
            },
            status=400,
        )

    # 자격 증명 확인
    credential = _DEMO_CREDENTIALS.get(username)
    if credential is None or credential["password"] != password:
        record_failure(ip)
        return JsonResponse(
            {
                "data": None,
                "meta": {},
                "error": {
                    "code": "AUTH_FAILED",
                    "message": "아이디 또는 비밀번호가 올바르지 않습니다.",
                    "details": [],
                },
            },
            status=401,
        )

    # 로그인 성공 — 실패 기록 초기화
    clear_failures(ip)

    # 세션에 사용자 정보 저장
    request.session["user_id"] = credential["user_id"]
    request.session["username"] = username
    request.session["role_code"] = credential["role_code"]
    request.session["display_name"] = credential["display_name"]
    request.session["scope_snapshot"] = build_scope_snapshot(
        credential["role_code"]
    )

    return JsonResponse(
        {
            "data": {
                "user_id": credential["user_id"],
                "username": username,
                "role_code": credential["role_code"],
                "display_name": credential["display_name"],
                "scope_snapshot": request.session["scope_snapshot"],
            },
            "meta": {},
            "error": None,
        },
        status=200,
    )


@csrf_exempt
@require_POST
def logout_view(request: HttpRequest) -> JsonResponse:
    """세션 로그아웃.

    Returns:
        200: 로그아웃 완료
    """
    request.session.flush()
    return JsonResponse(
        {
            "data": {"message": "로그아웃되었습니다."},
            "meta": {},
            "error": None,
        },
        status=200,
    )


@require_GET
def me_view(request: HttpRequest) -> JsonResponse:
    """현재 로그인된 사용자 정보 조회.

    Returns:
        200: 사용자 정보 (role_code, scope_snapshot 포함)
        401: 비로그인 상태
    """
    user_id = request.session.get("user_id")
    if not user_id:
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

    return JsonResponse(
        {
            "data": {
                "user_id": user_id,
                "username": request.session.get("username"),
                "role_code": request.session.get("role_code"),
                "display_name": request.session.get("display_name"),
                "scope_snapshot": request.session.get("scope_snapshot"),
            },
            "meta": {},
            "error": None,
        },
        status=200,
    )
