from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from base64 import urlsafe_b64encode
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
    authenticate_credentials,
    authenticate_token,
    issue_session_token,
)
from app.context import ContextValidationError, analysis_context  # noqa: E402
from app.contracts import CONTRACT_VERSION, ErrorCode, Role  # noqa: E402
from tests.support.auth_dependencies import authenticate_injected_token  # noqa: E402


class AuthenticationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 11, 5, 0, tzinfo=timezone.utc)
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "principals.json"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def record(self, token: str = "release-token", **overrides: object) -> dict[str, object]:
        record: dict[str, object] = {
            "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "subject": "00000000-0000-0000-0000-000000000011",
            "role": "hotel_analyst",
            "not_before": (self.now - timedelta(minutes=1)).isoformat(),
            "expires_at": (self.now + timedelta(minutes=1)).isoformat(),
        }
        record.update(overrides)
        return record

    def write(self, records: object) -> None:
        self.path.write_text(json.dumps(records), encoding="utf-8")

    def release_environment(self) -> dict[str, str]:
        return {"AUTH_PRINCIPALS_FILE": str(self.path)}

    def account(self, username: str = "analyst", password: str = "analyst1234!") -> dict[str, object]:
        salt = b"0123456789abcdef"
        return {
            "username": username,
            "password_salt": urlsafe_b64encode(salt).decode().rstrip("="),
            "password_hash": hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000).hex(),
            "password_iterations": 210_000,
            "subject": "00000000-0000-0000-0000-000000000011",
            "role": "hotel_analyst",
            "active": True,
        }

    async def test_credentials_issue_a_signed_expiring_session(self) -> None:
        self.write([self.account()])
        environment = self.release_environment() | {"AUTH_SESSION_SECRET": "s" * 32}
        with patch.dict(os.environ, environment, clear=False):
            principal = authenticate_credentials("ANALYST", "analyst1234!")
            token = issue_session_token(principal, now=self.now)
            with self.assertRaises(AuthenticationError) as missing_store:
                await authenticate_token(token, now=self.now + timedelta(minutes=1))
            with self.assertRaises(AuthenticationError):
                await authenticate_token(token, now=self.now + timedelta(hours=9))
        self.assertEqual(503, missing_store.exception.status_code)

    def test_login_rejects_unknown_wrong_and_inactive_accounts(self) -> None:
        for name, username, password, active in (
            ("unknown", "missing", "analyst1234!", True),
            ("wrong", "analyst", "wrong-password", True),
            ("inactive", "analyst", "analyst1234!", False),
        ):
            with self.subTest(name=name):
                self.write([{**self.account(), "active": active}])
                with patch.dict(os.environ, self.release_environment(), clear=False):
                    with self.assertRaises(AuthenticationError) as denied:
                        authenticate_credentials(username, password)
                self.assertEqual(401, denied.exception.status_code)

    async def test_release_uses_digest_owned_subject_and_role(self) -> None:
        self.write([self.record()])
        with patch.dict(os.environ, self.release_environment(), clear=False):
            principal = await authenticate_token("release-token", now=self.now)
        self.assertEqual(UUID("00000000-0000-0000-0000-000000000011"), principal.subject)
        self.assertEqual(Role.HOTEL_ANALYST, principal.role)

    async def test_missing_unknown_expired_and_future_tokens_fail_with_401(self) -> None:
        cases = {
            "missing": (None, self.record()),
            "empty": (" ", self.record()),
            "unknown": ("unknown", self.record()),
            "expired": ("release-token", self.record(expires_at=self.now.isoformat())),
            "future": ("release-token", self.record(not_before=(self.now + timedelta(seconds=1)).isoformat())),
        }
        for name, (token, record) in cases.items():
            with self.subTest(name=name):
                self.write([record])
                with patch.dict(os.environ, self.release_environment(), clear=False):
                    with self.assertRaises(AuthenticationError) as denied:
                        await authenticate_token(token, now=self.now)
                self.assertEqual(401, denied.exception.status_code)
                self.assertNotIn("release-token", denied.exception.message)

    async def test_invalid_principal_files_fail_closed_with_503(self) -> None:
        valid = self.record()
        cases = {
            "empty": [],
            "duplicate": [valid, valid],
            "invalid_uuid": [self.record(subject="not-a-uuid")],
            "invalid_role": [self.record(role="owner")],
            "raw_token_field": [{**self.record(), "token": "release-token"}],
            "naive_time": [self.record(not_before="2026-08-11T04:59:00")],
        }
        for name, payload in cases.items():
            with self.subTest(name=name):
                self.write(payload)
                with patch.dict(os.environ, self.release_environment(), clear=False):
                    with self.assertRaises(AuthenticationError) as unavailable:
                        await authenticate_token("release-token", now=self.now)
                self.assertEqual(503, unavailable.exception.status_code)
                self.assertNotIn("release-token", unavailable.exception.message)

        self.path.unlink()
        with patch.dict(os.environ, self.release_environment(), clear=False):
            with self.assertRaises(AuthenticationError) as unreadable:
                await authenticate_token("release-token", now=self.now)
        self.assertEqual(503, unreadable.exception.status_code)

    async def test_injected_test_authenticator_accepts_only_support_principals(self) -> None:
        principal = await authenticate_injected_token("runtime-report-admin-token")
        self.assertEqual(UUID(int=2), principal.subject)
        self.assertEqual(Role.REPORT_ADMIN, principal.role)
        with self.assertRaises(AuthenticationError) as denied:
            await authenticate_injected_token("arbitrary-token")
        self.assertEqual(401, denied.exception.status_code)

    async def test_default_release_mode_never_falls_back_to_test_principal(self) -> None:
        environment = os.environ.copy()
        environment.pop("AUTH_PRINCIPALS_FILE", None)
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(AuthenticationError) as unavailable:
                await authenticate_token("runtime-test-token", now=self.now)
        self.assertEqual(503, unavailable.exception.status_code)

    async def test_unavailable_release_mapping_is_normalized_without_secret_details(self) -> None:
        environment = os.environ.copy()
        environment.pop("AUTH_PRINCIPALS_FILE", None)
        request = SimpleNamespace(state=SimpleNamespace(request_id=UUID(int=9)))
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="runtime-test-token"
        )
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(ContextValidationError) as unavailable:
                await analysis_context(
                    request,
                    credentials,
                    "trace-9",
                    "Asia/Seoul",
                    CONTRACT_VERSION,
                    authenticate_token,
                )
        self.assertEqual(503, unavailable.exception.status_code)
        self.assertEqual(ErrorCode.DEPENDENCY_UNAVAILABLE, unavailable.exception.code)
        self.assertNotIn("runtime-test-token", unavailable.exception.message)

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
