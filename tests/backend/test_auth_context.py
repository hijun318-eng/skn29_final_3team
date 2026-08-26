"""DB 권위 계정, revocable session과 server-owned 분석 Context를 검증한다."""

from __future__ import annotations

import hashlib
import os
import sys
import unittest
from base64 import urlsafe_b64encode
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi.security import HTTPAuthorizationCredentials

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND))

from app.auth import (  # noqa: E402
    AuthenticationError,
    authenticate_token,
    create_authenticated_session,
    create_password_verifier,
    require_active_subject_with_capability,
)
from app.context import analysis_context  # noqa: E402
from app.contracts import CONTRACT_VERSION, Capability, Role  # noqa: E402
from tests.support.auth_dependencies import authenticate_injected_token  # noqa: E402


class _Result:
    def __init__(self, *, row=None, scalar=None) -> None:
        self._row = row
        self._scalar = scalar

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row

    def scalar_one_or_none(self):
        return self._scalar


class _Session:
    def __init__(self, *results: _Result) -> None:
        self.results = list(results)
        self.statements: list[str] = []

    async def execute(self, statement, _parameters=None):
        self.statements.append(str(statement))
        return self.results.pop(0)


def _scope(session: _Session):
    @asynccontextmanager
    async def fake_scope(_database_url=None):
        yield session

    return fake_scope


class AuthenticationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)
        self.subject = UUID("00000000-0000-0000-0000-000000000011")
        self.password = "analyst1234!"
        salt = b"0123456789abcdef0123456789abcdef"
        self.account = {
            "subject": self.subject,
            "role": "analyst",
            "password_salt": urlsafe_b64encode(salt).decode().rstrip("="),
            "password_hash": hashlib.pbkdf2_hmac(
                "sha256", self.password.encode(), salt, 210_000
            ).hex(),
            "password_iterations": 210_000,
            "active": True,
            "deleted_at": None,
        }
        self.environment = {
            "APP_RUNTIME_DATABASE_URL": "postgresql://runtime:secret@db/app",
            "AUTH_SESSION_SECRET": "s" * 32,
        }

    async def test_db_credentials_issue_and_validate_a_signed_session(self) -> None:
        login_session = _Session(_Result(row=self.account), _Result())
        with patch.dict(os.environ, self.environment, clear=False), patch(
            "app.auth.session_scope", _scope(login_session)
        ):
            principal, token = await create_authenticated_session(
                "ANALYST", self.password
            )

        active_session = _Session(_Result(scalar=1))
        with patch.dict(os.environ, self.environment, clear=False), patch(
            "app.auth.session_scope", _scope(active_session)
        ):
            authenticated = await authenticate_token(
                token, now=self.now + timedelta(minutes=1)
            )

        self.assertEqual(self.subject, authenticated.subject)
        self.assertEqual(Role.ANALYST, authenticated.role)
        self.assertIn("security.accounts", login_session.statements[0])
        self.assertIn("FOR SHARE", login_session.statements[0])
        self.assertIn("INSERT INTO security.auth_sessions", login_session.statements[1])
        self.assertIn("JOIN security.accounts", active_session.statements[0])

    async def test_wrong_inactive_and_missing_accounts_share_401(self) -> None:
        cases = (
            ({**self.account, "active": False}, self.password),
            (self.account, "wrong-password"),
            (None, self.password),
        )
        for row, password in cases:
            with self.subTest(row=bool(row), password_matches=password == self.password):
                with patch.dict(os.environ, self.environment, clear=False), patch(
                    "app.auth.session_scope", _scope(_Session(_Result(row=row)))
                ):
                    with self.assertRaises(AuthenticationError) as denied:
                        await create_authenticated_session("analyst", password)
                self.assertEqual(401, denied.exception.status_code)
                self.assertNotIn(password, denied.exception.message)

    async def test_invalid_database_configuration_is_typed_503(self) -> None:
        with patch.dict(
            os.environ,
            {
                "APP_RUNTIME_DATABASE_URL": "sqlite://",
                "AUTH_SESSION_SECRET": "s" * 32,
            },
            clear=False,
        ):
            with self.assertRaises(AuthenticationError) as unavailable:
                await create_authenticated_session("analyst", self.password)
        self.assertEqual(503, unavailable.exception.status_code)

    async def test_background_subject_uses_current_db_role_capability(self) -> None:
        admin = {"subject": self.subject, "role": "admin"}
        with patch.dict(os.environ, self.environment, clear=False), patch(
            "app.auth.session_scope", _scope(_Session(_Result(row=admin)))
        ):
            principal = await require_active_subject_with_capability(
                self.subject, Capability.MANAGE_SYSTEM, now=self.now
            )
        self.assertEqual(Role.ADMIN, principal.role)

    async def test_password_verifier_reuses_pbkdf2_contract_without_raw_password(self) -> None:
        salt, digest, iterations = await create_password_verifier(self.password)
        self.assertNotIn(self.password, salt)
        self.assertNotIn(self.password, digest)
        self.assertEqual(64, len(digest))
        self.assertEqual(210_000, iterations)

    async def test_injected_authenticator_exposes_only_two_roles(self) -> None:
        principal = await authenticate_injected_token("runtime-admin-token")
        self.assertEqual(UUID(int=2), principal.subject)
        self.assertEqual(Role.ADMIN, principal.role)
        with self.assertRaises(AuthenticationError):
            await authenticate_injected_token("runtime-report-admin-token")

    async def test_analysis_context_uses_server_owned_kst_date(self) -> None:
        request = SimpleNamespace(
            state=SimpleNamespace(request_id=UUID(int=9), trace_id="trace-9")
        )
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="runtime-test-token"
        )
        with patch("app.context._server_kst_date", return_value=date(2026, 8, 15)):
            context = await analysis_context(
                request,
                credentials,
                "trace-9",
                "Asia/Seoul",
                CONTRACT_VERSION,
                authenticate_injected_token,
            )

        self.assertEqual(date(2026, 8, 15), context.as_of)


if __name__ == "__main__":
    unittest.main()
