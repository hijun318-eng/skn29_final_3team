"""bootstrap CLI가 secret을 출력하지 않고 DB subject·session·감사 계약을 지키는지 검증한다."""

from __future__ import annotations

import io
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app" / "backend"))

from scripts import provision_accounts  # noqa: E402


def _payload() -> dict:
    return {
        "database_url": "postgresql://migration:db-secret@db/app",
        "require_subject_match": False,
        "accounts": [
            {
                "subject": str(UUID(int=1)),
                "username": "analyst",
                "password": "analyst-password",
                "role": "analyst",
            },
            {
                "subject": str(UUID(int=2)),
                "username": "admin",
                "password": "administrator-password",
                "role": "admin",
            },
        ],
    }


def test_read_request_accepts_exact_two_roles_and_rejects_legacy_role() -> None:
    with patch("sys.stdin", io.StringIO(json.dumps(_payload()))):
        database_url, require_subject_match, accounts = provision_accounts._read_request()
    assert database_url.endswith("@db/app")
    assert require_subject_match is False
    assert {item["role"] for item in accounts} == {"analyst", "admin"}

    payload = _payload()
    payload["accounts"][1]["role"] = "platform_admin"
    with patch("sys.stdin", io.StringIO(json.dumps(payload))), pytest.raises(ValueError):
        provision_accounts._read_request()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("username", "관리자"),
        ("password", "elevenchars"),
        ("password", "x" * 129),
    ),
)
def test_read_request_rejects_non_ascii_username_and_password_outside_12_to_128(
    field: str,
    value: str,
) -> None:
    payload = _payload()
    payload["accounts"][1][field] = value
    with patch("sys.stdin", io.StringIO(json.dumps(payload))), pytest.raises(
        ValueError
    ):
        provision_accounts._read_request()


def test_main_outputs_only_safe_completion_metadata(capsys) -> None:
    async def no_op(_database_url, _accounts, *, require_subject_match):
        assert require_subject_match is False
        return None

    raw = json.dumps(_payload())
    with patch("sys.stdin", io.StringIO(raw)), patch.object(
        provision_accounts, "_provision", no_op
    ):
        assert provision_accounts.main() == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "processed" in combined
    assert "analyst-password" not in combined
    assert "administrator-password" not in combined
    assert "db-secret" not in combined


class _Result:
    def __init__(self, scalar=None) -> None:
        self._scalar = scalar

    def scalar_one(self):
        return self._scalar


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None]] = []
        self._upsert_subjects = [UUID(int=11), UUID(int=22)]

    async def execute(self, statement, parameters=None):
        rendered = str(statement)
        self.calls.append((rendered, parameters))
        if "INSERT INTO security.accounts" in rendered:
            return _Result(self._upsert_subjects.pop(0))
        return _Result()


@pytest.mark.asyncio
async def test_provision_preserves_existing_subject_and_revokes_sessions_with_audit() -> None:
    session = _Session()

    @asynccontextmanager
    async def scope(_database_url):
        yield session

    accounts = tuple(dict(item) for item in _payload()["accounts"])
    with patch.object(provision_accounts, "session_scope", scope), patch.object(
        provision_accounts,
        "create_password_verifier",
        AsyncMock(side_effect=[("salt-a", "a" * 64, 210_000), ("salt-b", "b" * 64, 210_000)]),
    ):
        await provision_accounts._provision(
            "postgresql://db/app", accounts, require_subject_match=False
        )

    statements = "\n".join(statement for statement, _ in session.calls)
    assert statements.count("ON CONFLICT (username) DO UPDATE") == 2
    assert "EXCLUDED.subject" not in statements
    assert statements.count("UPDATE security.auth_sessions") == 2
    assert statements.count("INSERT INTO governance.audit_events") == 2
    for statement, parameters in session.calls:
        if "INSERT INTO governance.audit_events" in statement:
            serialized = str(parameters)
            assert "password" not in serialized
            assert "salt-a" not in serialized
            assert "salt-b" not in serialized


@pytest.mark.asyncio
async def test_legacy_provision_rejects_an_existing_username_with_another_subject() -> None:
    """명시 legacy UUID와 DB username의 기존 UUID가 다르면 transaction을 실패시킨다."""

    session = _Session()

    @asynccontextmanager
    async def scope(_database_url):
        yield session

    accounts = tuple(dict(item) for item in _payload()["accounts"])
    with patch.object(provision_accounts, "session_scope", scope), patch.object(
        provision_accounts,
        "create_password_verifier",
        AsyncMock(
            side_effect=[
                ("salt-a", "a" * 64, 210_000),
                ("salt-b", "b" * 64, 210_000),
            ]
        ),
    ), pytest.raises(RuntimeError, match="subject"):
        await provision_accounts._provision(
            "postgresql://db/app", accounts, require_subject_match=True
        )

    statements = "\n".join(statement for statement, _ in session.calls)
    assert "UPDATE security.auth_sessions" not in statements
    assert "INSERT INTO governance.audit_events" not in statements
