"""관리자 감사 trail의 서버 grouping·cursor·HTTP 공개 계약을 검증한다."""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone
from functools import wraps
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND))

from app.adapters.admin_account_repository import (  # noqa: E402
    AdminAccountRepository,
    AuditTrailNotFound,
    InvalidAuditTrailCursor,
    _decode_audit_cursor,
    _encode_audit_cursor,
)
from app.api.admin_router import system_manage_context  # noqa: E402
from app.contracts import CONTRACT_VERSION, RequestContext, Role  # noqa: E402
from app.database import get_database_session  # noqa: E402
from app.main import app  # noqa: E402


def _run_async(test):
    """추가 pytest plugin 없이 coroutine 테스트를 격리 event loop에서 실행한다."""

    @wraps(test)
    def wrapper(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))

    return wrapper


class _Session:
    """HTTP route 테스트에서 실제 DB transaction을 열지 않는 명시적 test double이다."""


def _context() -> RequestContext:
    """system.manage 권한과 고정 추적 값을 가진 관리자 요청 문맥을 만든다."""

    return RequestContext(
        user_id=UUID(int=1),
        role=Role.PLATFORM_ADMIN,
        as_of=date(2026, 8, 27),
        contract_version=CONTRACT_VERSION,
    )


async def _admin_context_override() -> RequestContext:
    """ASGI 테스트 요청에 인증 완료 관리자 문맥을 주입한다."""

    return _context()


async def _session_override():
    """ASGI 테스트 요청에 외부 DB 없는 명시적 세션 double을 주입한다."""

    yield _Session()


@pytest.fixture
def admin_dependencies():
    """관리자 route 의존성을 테스트 동안 교체하고 종료 시 원상 복구한다."""

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[system_manage_context] = _admin_context_override
    app.dependency_overrides[get_database_session] = _session_override
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_audit_cursor_round_trip_and_rejects_tampering() -> None:
    """keyset cursor가 timezone과 trail ID를 보존하고 임의 문자열을 거부하는지 확인한다."""

    started_at = datetime(2026, 8, 27, 1, 2, 3, tzinfo=timezone.utc)
    cursor = _encode_audit_cursor(started_at, "request_id:request-1")
    assert _decode_audit_cursor(cursor) == (started_at, "request_id:request-1")
    with pytest.raises(InvalidAuditTrailCursor):
        _decode_audit_cursor("not-a-valid-cursor")


@_run_async
async def test_list_audit_trails_returns_frontend_contract(admin_dependencies) -> None:
    """목록 route가 서버 grouping 결과와 next cursor를 data envelope로 반환하는지 확인한다."""

    now = datetime(2026, 8, 27, 1, tzinfo=timezone.utc)
    item = {
        "trail_id": "request_id:00000000-0000-0000-0000-000000000002",
        "headline": "ANALYSIS_SUCCEEDED",
        "started_at": now,
        "ended_at": now,
        "outcome": "SUCCEEDED",
        "event_count": 2,
        "actor": {
            "subject": UUID(int=1),
            "display_name": "admin",
            "role": "platform_admin",
        },
        "primary_object": {"type": "ANALYSIS_REQUEST", "id": "request-1"},
        "correlation": {
            "type": "request_id",
            "id": "00000000-0000-0000-0000-000000000002",
        },
    }
    with patch.object(
        AdminAccountRepository,
        "list_audit_trails",
        return_value=((item,), "next-page"),
    ) as repository_call:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://backend.test",
        ) as client:
            response = await client.get(
                "/admin/audit-trails",
                params={"limit": 30, "outcome": "SUCCEEDED", "from": "2026-08-01"},
            )

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["event_count"] == 2
    assert response.json()["data"]["next_cursor"] == "next-page"
    repository_call.assert_awaited_once()


@_run_async
async def test_missing_audit_trail_returns_404(admin_dependencies) -> None:
    """존재하지 않는 trail 상세가 빈 성공값이 아니라 명시적 404로 닫히는지 확인한다."""

    with patch.object(
        AdminAccountRepository,
        "get_audit_trail",
        side_effect=AuditTrailNotFound("missing"),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://backend.test",
        ) as client:
            response = await client.get("/admin/audit-trails/request_id:missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
