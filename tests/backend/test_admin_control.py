"""두 Role 관리자 계정 경계, session 폐기와 마지막 관리자 보호를 검증한다."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from base64 import urlsafe_b64encode
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
import httpx
from fastapi import HTTPException
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app" / "backend"))

from app.adapters.admin_account_repository import (  # noqa: E402
    AdminAccountConflict,
    AdminAccountRepository,
    LastActiveAdminConflict,
)
from app.admin_contracts import CreateAccountRequest, UpdateAccountRequest  # noqa: E402
from app.api.admin_router import system_manage_context  # noqa: E402
from app.auth import create_authenticated_session  # noqa: E402
from app.contracts import CONTRACT_VERSION, RequestContext, Role  # noqa: E402
from app.database import get_database_session  # noqa: E402
from app.main import app  # noqa: E402


class _Result:
    def __init__(self, *, row=None, scalars=()) -> None:
        self._row = row
        self._scalars = tuple(scalars)

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row

    def one(self):
        return self._row

    def scalars(self):
        return self._scalars


class _Session:
    def __init__(self, *results: _Result) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, dict | None]] = []

    async def execute(self, statement, parameters=None):
        self.calls.append((str(statement), parameters))
        if "pg_advisory_xact_lock" in str(statement):
            return _Result()
        return self._results.pop(0) if self._results else _Result()

    @asynccontextmanager
    async def begin_nested(self):
        yield


def _context(role: Role) -> RequestContext:
    return RequestContext(
        user_id=UUID(int=1),
        role=role,
        as_of=date(2026, 8, 26),
        contract_version=CONTRACT_VERSION,
    )


def _account(subject: UUID, role: str = "admin") -> dict:
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    return {
        "subject": subject,
        "username": role,
        "role": role,
        "active": True,
        "created_at": now,
        "updated_at": now,
        "deactivated_at": None,
        "deleted_at": None,
    }


def test_system_manage_dependency_rejects_analyst_and_accepts_admin() -> None:
    with pytest.raises(HTTPException) as denied:
        system_manage_context(_context(Role.ANALYST))
    assert denied.value.status_code == 403
    assert system_manage_context(_context(Role.ADMIN)).role is Role.ADMIN


def test_admin_contract_rejects_legacy_roles_and_masks_password_repr() -> None:
    request = CreateAccountRequest(
        username="new-user", password="new-password", role="admin"
    )
    assert "new-password" not in repr(request)
    for role in ("report_admin", "data_admin", "platform_admin"):
        with pytest.raises(ValidationError):
            CreateAccountRequest(
                username="new-user", password="new-password", role=role
            )
    with pytest.raises(ValidationError):
        UpdateAccountRequest()
    with pytest.raises(ValidationError):
        CreateAccountRequest(
            username="new-user", password="short-pass", role="analyst"
        )


@pytest.mark.asyncio
async def test_last_active_admin_cannot_be_demoted() -> None:
    subject = UUID(int=2)
    session = _Session(
        _Result(row=_account(subject)),
        _Result(scalars=(subject,)),
    )
    with pytest.raises(LastActiveAdminConflict):
        await AdminAccountRepository(session).update_account(
            subject,
            changes={"role": Role.ANALYST},
            actor=_context(Role.ADMIN),
        )
    statements = [statement for statement, _ in session.calls]
    assert "pg_advisory_xact_lock" in statements[0]
    assert any("FOR UPDATE" in statement for statement in statements[1:])


@pytest.mark.asyncio
async def test_deactivation_sets_timestamp_and_revokes_sessions() -> None:
    subject = UUID(int=3)
    current = _account(subject, "analyst")
    deactivated = {
        **current,
        "active": False,
        "deactivated_at": datetime(2026, 8, 26, 1, tzinfo=timezone.utc),
    }
    session = _Session(_Result(row=current), _Result(row=deactivated))
    account = await AdminAccountRepository(session).update_account(
        subject,
        changes={"active": False},
        actor=_context(Role.ADMIN),
    )
    assert account["deactivated_at"] is not None
    statements = "\n".join(statement for statement, _ in session.calls)
    assert "deactivated_at = CASE" in statements
    assert "UPDATE security.auth_sessions" in statements


@pytest.mark.asyncio
async def test_connection_check_audit_contains_only_public_statuses() -> None:
    session = _Session()
    await AdminAccountRepository(session).record_connection_check(
        actor=_context(Role.ADMIN),
        connections=(
            {
                "id": "pms",
                "status": "ready",
                "url": "https://must-not-be-audited.invalid",
                "credential": "must-not-be-audited",
            },
        ),
    )

    statement, parameters = session.calls[-1]
    assert "CONNECTION_CHECK" in statement
    assert "CONNECTION_SET" in statement
    rendered = str(parameters)
    assert '"pms": "ready"' in rendered
    assert "must-not-be-audited" not in rendered


@pytest.mark.asyncio
async def test_last_admin_conflict_survives_actual_http_error_envelope() -> None:
    async def admin_context_override() -> RequestContext:
        return _context(Role.ADMIN)

    async def session_override():
        yield _Session()

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[system_manage_context] = admin_context_override
    app.dependency_overrides[get_database_session] = session_override
    try:
        with patch.object(
            AdminAccountRepository,
            "delete_account",
            side_effect=LastActiveAdminConflict("protected"),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://backend.test",
            ) as client:
                response = await client.delete(f"/admin/accounts/{UUID(int=2)}")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "LAST_ADMIN_REQUIRED"
    assert "detail" not in body


@pytest.mark.asyncio
async def test_password_reset_revokes_sessions_and_audits_without_verifier() -> None:
    subject = UUID(int=2)
    session = _Session(_Result(row=_account(subject)))
    with patch(
        "app.adapters.admin_account_repository.create_password_verifier",
        return_value=("encoded-salt", "0" * 64, 210_000),
    ):
        await AdminAccountRepository(session).reset_password(
            subject,
            password="new-password",
            actor=_context(Role.ADMIN),
        )

    statements = "\n".join(statement for statement, _ in session.calls)
    assert "UPDATE security.auth_sessions" in statements
    assert "INSERT INTO governance.audit_events" in statements
    audit_parameters = session.calls[-1][1] or {}
    assert "new-password" not in str(audit_parameters)
    assert "encoded-salt" not in str(audit_parameters)
    assert "password_hash" not in str(audit_parameters)


@pytest.mark.asyncio
async def test_login_insert_and_password_reset_are_serialized_by_account_lock() -> None:
    """reset은 로그인 FOR SHARE transaction 뒤에 lock을 얻어 방금 발급한 session도 폐기한다."""

    subject = UUID(int=2)
    password = "administrator-password"
    salt = b"0123456789abcdef0123456789abcdef"
    credential_row = {
        "subject": subject,
        "role": "admin",
        "password_salt": urlsafe_b64encode(salt).decode().rstrip("="),
        "password_hash": hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, 210_000
        ).hex(),
        "password_iterations": 210_000,
        "active": True,
        "deleted_at": None,
    }
    row_lock = asyncio.Lock()
    login_locked = asyncio.Event()
    allow_session_insert = asyncio.Event()
    reset_locked = asyncio.Event()
    events: list[str] = []

    class LoginSession:
        async def execute(self, statement, _parameters=None):
            rendered = str(statement)
            if "FOR SHARE" in rendered:
                await row_lock.acquire()
                login_locked.set()
                events.append("login_locked")
                return _Result(row=credential_row)
            if "INSERT INTO security.auth_sessions" in rendered:
                await allow_session_insert.wait()
                events.append("session_inserted")
            return _Result()

    class ResetSession:
        async def execute(self, statement, _parameters=None):
            rendered = str(statement)
            if "FOR UPDATE" in rendered:
                await row_lock.acquire()
                reset_locked.set()
                events.append("reset_locked")
                return _Result(row=_account(subject))
            if "UPDATE security.auth_sessions" in rendered:
                events.append("sessions_revoked")
            return _Result()

    @asynccontextmanager
    async def login_scope(_database_url=None):
        try:
            yield LoginSession()
        finally:
            if row_lock.locked():
                row_lock.release()

    async def reset_password():
        try:
            with patch(
                "app.adapters.admin_account_repository.create_password_verifier",
                return_value=("new-salt", "f" * 64, 210_000),
            ):
                await AdminAccountRepository(ResetSession()).reset_password(
                    subject,
                    password="replacement-password",
                    actor=_context(Role.ADMIN),
                )
        finally:
            if row_lock.locked():
                row_lock.release()

    environment = {
        "APP_RUNTIME_DATABASE_URL": "postgresql://runtime:secret@db/app",
        "AUTH_SESSION_SECRET": "s" * 32,
    }
    with patch.dict(os.environ, environment, clear=False), patch(
        "app.auth.session_scope", login_scope
    ):
        login_task = asyncio.create_task(
            create_authenticated_session("admin", password)
        )
        await login_locked.wait()
        reset_task = asyncio.create_task(reset_password())
        await asyncio.sleep(0)
        assert not reset_locked.is_set()
        allow_session_insert.set()
        await login_task
        await reset_task

    assert events.index("session_inserted") < events.index("reset_locked")
    assert events.index("reset_locked") < events.index("sessions_revoked")
