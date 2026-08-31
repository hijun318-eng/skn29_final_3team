"""사용자 계정 Role 공개 계약과 legacy 인증 차단을 독립적으로 검증한다."""

from __future__ import annotations

import asyncio
from argparse import ArgumentTypeError
from base64 import urlsafe_b64encode
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.adapters.admin_account_repository import (  # noqa: E402
    AdminAccountConflict,
    AdminAccountRepository,
)
from app.admin_contracts import AccountData, CreateAccountRequest  # noqa: E402
from app.api.admin_router import system_manage_context  # noqa: E402
from app.auth import (  # noqa: E402
    _AccountCredential,
    _assert_session_active,
    _authenticate_credentials_in_session,
    authenticate_credentials,
)
from app.auth_principal_store import AuthenticationError, Principal  # noqa: E402
from app.contracts import CONTRACT_VERSION, RequestContext, Role  # noqa: E402
from app.database import get_database_session  # noqa: E402
from app.main import app  # noqa: E402
from app.provision_auth_accounts import (  # noqa: E402
    AccountDefinition,
    _parse_account,
    _provision,
    _require_safe_existing_role,
)
from app.user_account_roles import (  # noqa: E402
    internal_user_account_role,
    public_user_account_role,
)


def _account_row(role: Role, *, deleted_at: datetime | None = None) -> dict[str, object]:
    salt = b"0123456789abcdef"
    return {
        "password_salt": urlsafe_b64encode(salt).decode().rstrip("="),
        "password_hash": "a" * 64,
        "password_iterations": 210_000,
        "subject": UUID(int=17),
        "role": role.value,
        "active": True,
        "deleted_at": deleted_at,
    }


class _MappingResult:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row

    def mappings(self) -> "_MappingResult":
        return self

    def one_or_none(self) -> dict[str, object] | None:
        return self.row


class _CredentialSession:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row

    async def execute(self, _statement, _parameters=None) -> _MappingResult:
        return _MappingResult(self.row)


def test_public_account_role_mapping_has_no_legacy_alias() -> None:
    assert public_user_account_role(Role.ANALYST) == "analyst"
    assert public_user_account_role(Role.PLATFORM_ADMIN) == "admin"
    assert internal_user_account_role("analyst") is Role.ANALYST
    assert internal_user_account_role("admin") is Role.PLATFORM_ADMIN
    for role in (Role.REPORT_ADMIN, Role.DATA_ADMIN):
        with pytest.raises(ValueError):
            public_user_account_role(role)
    assert _parse_account("operator:admin").role is Role.PLATFORM_ADMIN
    for role in ("platform_admin", "report_admin", "data_admin"):
        with pytest.raises(ArgumentTypeError):
            _parse_account(f"operator:{role}")
    for role in (Role.REPORT_ADMIN, Role.DATA_ADMIN):
        with pytest.raises(RuntimeError, match="requires reviewed migration"):
            _require_safe_existing_role("legacy", role)


def test_legacy_account_credentials_are_rejected_after_hash_verification() -> None:
    async def scenario() -> None:
        for role in (Role.REPORT_ADMIN, Role.DATA_ADMIN):
            row = _account_row(role)
            credential = _AccountCredential(
                password_salt=str(row["password_salt"]),
                password_hash=str(row["password_hash"]),
                password_iterations=int(row["password_iterations"]),
                principal=Principal(UUID(int=17), role),
                active=True,
            )
            with (
                patch("app.auth._load_account", AsyncMock(return_value=credential)),
                patch("app.auth._derive_password_hash", return_value="a" * 64) as derive,
            ):
                with pytest.raises(AuthenticationError) as denied:
                    await authenticate_credentials("legacy", "correct-password")
            assert denied.value.status_code == 401
            derive.assert_called_once()

            with patch(
                "app.auth._derive_password_hash", return_value="a" * 64
            ) as session_derive:
                with pytest.raises(AuthenticationError) as session_denied:
                    await _authenticate_credentials_in_session(
                        _CredentialSession(row), "legacy", "correct-password"
                    )
            assert session_denied.value.status_code == 401
            session_derive.assert_called_once()

    asyncio.run(scenario())


def test_legacy_signed_session_is_rejected_before_database_access() -> None:
    async def scenario() -> None:
        with patch("app.auth.session_scope") as store:
            with pytest.raises(AuthenticationError) as denied:
                await _assert_session_active(
                    "signed.session",
                    Principal(UUID(int=17), Role.REPORT_ADMIN),
                    datetime(2026, 8, 31, tzinfo=timezone.utc),
                )
        assert denied.value.status_code == 401
        store.assert_not_called()

    asyncio.run(scenario())


def test_supported_session_rechecks_current_account_role_and_state() -> None:
    class _ActiveResult:
        def scalar_one_or_none(self) -> int:
            return 1

    class _Session:
        statement = ""

        async def execute(self, statement, _parameters=None) -> _ActiveResult:
            self.statement = str(statement)
            return _ActiveResult()

    session = _Session()

    @asynccontextmanager
    async def scope(_database_url: str):
        yield session

    async def scenario() -> None:
        with (
            patch.dict(
                os.environ,
                {"APP_RUNTIME_DATABASE_URL": "postgresql://runtime:secret@db/app"},
                clear=False,
            ),
            patch("app.auth.session_scope", scope),
        ):
            await _assert_session_active(
                "signed.session",
                Principal(UUID(int=17), Role.ANALYST),
                datetime(2026, 8, 31, tzinfo=timezone.utc),
            )

    asyncio.run(scenario())
    normalized = " ".join(session.statement.split())
    assert "JOIN security.auth_accounts AS accounts" in normalized
    assert "accounts.role = sessions.role" in normalized
    assert "accounts.active" in normalized
    assert "accounts.deleted_at IS NULL" in normalized
    assert "accounts.role IN ('analyst', 'platform_admin')" in normalized


def test_admin_http_maps_public_admin_to_internal_role_and_back() -> None:
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)
    stored_account = {
        "subject": UUID(int=18),
        "username": "admin-user",
        "role": "platform_admin",
        "active": True,
        "created_at": now,
        "updated_at": now,
        "deactivated_at": None,
        "deleted_at": None,
    }

    async def admin_context() -> RequestContext:
        return RequestContext(
            user_id=UUID(int=1),
            role=Role.PLATFORM_ADMIN,
            contract_version=CONTRACT_VERSION,
        )

    async def database_session():
        yield object()

    async def scenario() -> None:
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[system_manage_context] = admin_context
        app.dependency_overrides[get_database_session] = database_session
        try:
            with patch.object(
                AdminAccountRepository,
                "create_account",
                AsyncMock(return_value=stored_account),
            ) as create_account:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://backend.test",
                ) as client:
                    response = await client.post(
                        "/admin/accounts",
                        json={
                            "username": "admin-user",
                            "password": "temporary-password",
                            "role": "admin",
                        },
                    )
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)

        assert response.status_code == 201
        assert response.json()["data"]["role"] == "admin"
        assert create_account.await_args.kwargs["role"] is Role.PLATFORM_ADMIN

    asyncio.run(scenario())


def test_legacy_account_rows_are_not_public_models() -> None:
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)
    base = {
        "subject": UUID(int=19),
        "username": "legacy",
        "active": False,
        "created_at": now,
        "updated_at": now,
        "deactivated_at": now,
        "deleted_at": None,
    }
    assert AccountData.model_validate({**base, "role": "platform_admin"}).role == "admin"
    for role in ("report_admin", "data_admin"):
        with pytest.raises(ValidationError):
            AccountData.model_validate({**base, "role": role})

    schema = CreateAccountRequest.model_json_schema()["properties"]["role"]
    assert set(schema["enum"]) == {"analyst", "admin"}


def test_legacy_accounts_are_filtered_from_admin_list_queries() -> None:
    class _CountResult:
        def scalar_one(self) -> int:
            return 0

    class _RowsResult:
        def mappings(self) -> tuple[()]:
            return ()

    class _Session:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement, _parameters=None):
            self.statements.append(str(statement))
            return _CountResult() if len(self.statements) == 1 else _RowsResult()

    async def scenario() -> None:
        session = _Session()
        rows, total = await AdminAccountRepository(session).list_accounts(
            page=1, page_size=50, search=""
        )
        assert rows == ()
        assert total == 0
        assert len(session.statements) == 2
        for statement in session.statements:
            assert "role IN ('analyst', 'platform_admin')" in statement

    asyncio.run(scenario())


def test_legacy_account_cannot_be_reactivated_through_direct_patch() -> None:
    class _LockedResult:
        def mappings(self) -> "_LockedResult":
            return self

        def one_or_none(self) -> dict[str, object]:
            now = datetime(2026, 8, 31, tzinfo=timezone.utc)
            return {
                "subject": UUID(int=20),
                "username": "legacy",
                "role": "report_admin",
                "active": False,
                "created_at": now,
                "updated_at": now,
                "deactivated_at": now,
                "deleted_at": None,
            }

    class _Session:
        async def execute(self, statement, _parameters=None):
            if "pg_advisory_xact_lock" in str(statement):
                return object()
            return _LockedResult()

    async def scenario() -> None:
        with pytest.raises(AdminAccountConflict):
            await AdminAccountRepository(_Session()).update_account(
                UUID(int=20),
                changes={"active": True},
                actor=RequestContext(
                    user_id=UUID(int=1),
                    role=Role.PLATFORM_ADMIN,
                    contract_version=CONTRACT_VERSION,
                ),
            )

    asyncio.run(scenario())


def test_provisioning_does_not_promote_same_username_legacy_account() -> None:
    class _ExistingRows:
        def __iter__(self):
            return iter(
                (
                    SimpleNamespace(
                        username="legacy",
                        subject=UUID(int=21),
                        role="report_admin",
                    ),
                )
            )

    class _Connection:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def execute(self, statement, _parameters=None):
            rendered = str(statement)
            self.statements.append(rendered)
            if "SELECT username, subject, role" in rendered:
                return _ExistingRows()
            return object()

    class _Transaction:
        def __init__(self, connection: _Connection) -> None:
            self.connection = connection

        def __enter__(self) -> _Connection:
            return self.connection

        def __exit__(self, _type, _value, _traceback) -> bool:
            return False

    class _Engine:
        def __init__(self) -> None:
            self.connection = _Connection()
            self.disposed = False

        def begin(self) -> _Transaction:
            return _Transaction(self.connection)

        def dispose(self) -> None:
            self.disposed = True

    engine = _Engine()
    with (
        patch("app.provision_auth_accounts._database_url", return_value="postgresql://db/app"),
        patch("app.provision_auth_accounts.create_engine", return_value=engine),
    ):
        with pytest.raises(RuntimeError, match="requires reviewed migration"):
            _provision(
                (AccountDefinition("legacy", Role.PLATFORM_ADMIN),),
                {},
                replace=False,
            )

    assert engine.disposed
    assert any(
        "SELECT username, subject, role" in statement
        for statement in engine.connection.statements
    )
    assert all(
        "INSERT INTO security.auth_accounts" not in statement
        for statement in engine.connection.statements
    )
