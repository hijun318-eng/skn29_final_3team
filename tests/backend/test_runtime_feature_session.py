"""인증 session이 기능 flag가 아닌 실제 role별 runtime readiness만 노출하는지 검증한다."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import Response
from starlette.requests import Request


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.router import authenticated_session, login
from app.auth_principal_store import Principal
from app.context import ContextValidationError
from app.contracts import LoginRequest, RequestContext, Role, RuntimeFeature


def _request() -> Request:
    """테스트 HTTP 요청에 middleware가 소유하는 요청·추적 식별자를 결속한다."""

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/auth/session",
            "raw_path": b"/auth/session",
            "query_string": b"",
            "headers": [],
            "client": ("test-client", 50000),
            "server": ("test-server", 80),
        }
    )
    request.state.request_id = uuid4()
    request.state.trace_id = f"trace-{uuid4().hex}"
    return request


def test_anonymous_session_does_not_probe_optional_runtimes() -> None:
    async def scenario() -> None:
        availability = AsyncMock()
        request = _request()

        with patch("app.api.router.available_runtime_features", availability):
            result = await authenticated_session(request, None)

        assert result.data.status == "anonymous"
        assert result.data.enabled_features == ()
        availability.assert_not_awaited()

    asyncio.run(scenario())


def test_authenticated_session_uses_actual_role_aware_availability() -> None:
    async def scenario() -> None:
        request = _request()
        context = RequestContext(
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
            user_id=uuid4(),
            role=Role.ANALYST,
        )
        availability = AsyncMock(
            return_value=(RuntimeFeature.INTERNAL_GUIDELINE,)
        )

        with patch("app.api.router.available_runtime_features", availability):
            result = await authenticated_session(request, context)

        assert result.data.enabled_features == (RuntimeFeature.INTERNAL_GUIDELINE,)
        assert result.data.role == "analyst"
        availability.assert_awaited_once_with(Role.ANALYST)

    asyncio.run(scenario())


def test_legacy_user_role_is_rejected_before_runtime_probe() -> None:
    async def scenario() -> None:
        request = _request()
        context = RequestContext(
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
            user_id=uuid4(),
            role=Role.REPORT_ADMIN,
        )
        availability = AsyncMock()

        with patch("app.api.router.available_runtime_features", availability):
            try:
                await authenticated_session(request, context)
            except ContextValidationError as error:
                assert error.status_code == 401
            else:
                raise AssertionError("legacy 사용자 Role 세션이 허용되었습니다.")

        availability.assert_not_awaited()

    asyncio.run(scenario())


def test_login_uses_authenticated_principal_role_availability() -> None:
    async def scenario() -> None:
        request = _request()
        response = Response()
        principal = Principal(subject=uuid4(), role=Role.PLATFORM_ADMIN)
        availability = AsyncMock(return_value=(RuntimeFeature.ML_PREDICTION,))
        create_session = AsyncMock(return_value=(principal, "opaque-session-token"))

        with (
            patch("app.api.router.create_authenticated_session", create_session),
            patch("app.api.router.available_runtime_features", availability),
        ):
            result = await login(
                LoginRequest(username="platform.admin", password="valid-password"),
                request,
                response,
            )

        assert result.data.enabled_features == (RuntimeFeature.ML_PREDICTION,)
        assert result.data.role == "admin"
        availability.assert_awaited_once_with(Role.PLATFORM_ADMIN)

    asyncio.run(scenario())


def test_auth_router_has_no_flag_only_feature_source() -> None:
    """인증 응답이 flag-only helper로 회귀하지 않도록 source 경계를 고정한다."""

    source = (BACKEND / "app" / "api" / "router.py").read_text(encoding="utf-8")

    assert "enabled_runtime_features" not in source
    assert source.count("await available_runtime_features(") == 2
