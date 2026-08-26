"""stdin으로 받은 두 bootstrap 계정을 App DB에 직접 provision한다.

비밀번호·DB URL은 argv, process environment, stdout으로 전달하지 않는다. PBKDF2 구현은
``app.auth.create_password_verifier`` 하나만 사용하며 기존 username의 subject는 변경하지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from string import ascii_lowercase, digits
from uuid import UUID

from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parents[1]
sys.path[:0] = [str(BACKEND), str(REPOSITORY)]

from app.auth import create_password_verifier
from app.database import session_scope


def _read_request() -> tuple[str, bool, tuple[dict[str, str], ...]]:
    """64 KiB 이하 strict JSON을 DB URL·subject 대조 모드·두 계정으로 검증한다."""

    raw = sys.stdin.read(65_537)
    if len(raw) > 65_536:
        raise ValueError("provision input is too large")
    payload = json.loads(raw)
    if not isinstance(payload, Mapping) or set(payload) != {
        "database_url",
        "require_subject_match",
        "accounts",
    }:
        raise ValueError("provision input fields are invalid")
    database_url = payload["database_url"]
    require_subject_match = payload["require_subject_match"]
    accounts = payload["accounts"]
    if not isinstance(database_url, str) or not database_url.strip():
        raise ValueError("database_url is invalid")
    if not isinstance(require_subject_match, bool):
        raise ValueError("require_subject_match is invalid")
    if not isinstance(accounts, list) or len(accounts) != 2:
        raise ValueError("exactly two bootstrap accounts are required")

    normalized: list[dict[str, str]] = []
    for item in accounts:
        if not isinstance(item, Mapping) or set(item) != {
            "subject",
            "username",
            "password",
            "role",
        }:
            raise ValueError("account fields are invalid")
        username = item["username"]
        password = item["password"]
        role = item["role"]
        subject = item["subject"]
        if (
            not isinstance(username, str)
            or username != username.strip().lower()
            or not 3 <= len(username) <= 64
            or not all(
                character in ascii_lowercase + digits + "._-" for character in username
            )
            or not isinstance(password, str)
            or not 12 <= len(password) <= 128
            or role not in {"analyst", "admin"}
        ):
            raise ValueError("account value is invalid")
        UUID(str(subject))
        normalized.append(
            {
                "subject": str(subject),
                "username": username,
                "password": password,
                "role": str(role),
            }
        )
    if {item["role"] for item in normalized} != {"analyst", "admin"}:
        raise ValueError("bootstrap roles must be analyst and admin")
    if len({item["username"] for item in normalized}) != 2:
        raise ValueError("bootstrap usernames must be unique")
    if len({item["subject"] for item in normalized}) != 2:
        raise ValueError("bootstrap subjects must be unique")
    return database_url.strip(), require_subject_match, tuple(normalized)


async def _provision(
    database_url: str,
    accounts: tuple[dict[str, str], ...],
    *,
    require_subject_match: bool,
) -> None:
    """username subject를 보존하며 legacy 이관이면 입력 UUID와 exact 대조해 upsert한다."""

    prepared: list[dict[str, object]] = []
    for account in accounts:
        salt, digest, iterations = await create_password_verifier(account["password"])
        prepared.append(
            {
                "subject": UUID(account["subject"]),
                "username": account["username"],
                "password_salt": salt,
                "password_hash": digest,
                "password_iterations": iterations,
                "role": account["role"],
            }
        )

    async with session_scope(database_url) as session:
        persisted_subjects: dict[str, UUID] = {}
        for account in prepared:
            result = await session.execute(
                text(
                    """
                    INSERT INTO security.accounts (
                        subject, username, password_salt, password_hash,
                        password_iterations, role, active
                    ) VALUES (
                        :subject, :username, :password_salt, :password_hash,
                        :password_iterations, :role, true
                    )
                    ON CONFLICT (username) DO UPDATE SET
                        password_salt = EXCLUDED.password_salt,
                        password_hash = EXCLUDED.password_hash,
                        password_iterations = EXCLUDED.password_iterations,
                        role = EXCLUDED.role,
                        active = true,
                        deactivated_at = NULL,
                        deleted_at = NULL,
                        updated_at = now()
                    RETURNING subject
                    """
                ),
                account,
            )
            persisted_subject = UUID(str(result.scalar_one()))
            if require_subject_match and persisted_subject != account["subject"]:
                raise RuntimeError("legacy account subject does not match persisted account")
            persisted_subjects[str(account["role"])] = persisted_subject

        for account in prepared:
            subject = persisted_subjects[str(account["role"])]
            await session.execute(
                text(
                    """
                    UPDATE security.auth_sessions
                    SET revoked_at = now()
                    WHERE subject = :subject AND revoked_at IS NULL
                    """
                ),
                {"subject": subject},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO governance.audit_events (
                        actor_user_id, actor_role, action_code,
                        object_type, object_id, details_json_redacted
                    ) VALUES (
                        :actor_user_id, 'admin', 'AUTH_ACCOUNT_BOOTSTRAPPED',
                        'AUTH_ACCOUNT', :object_id,
                        CAST(:details AS jsonb)
                    )
                    """
                ),
                {
                    "actor_user_id": persisted_subjects["admin"],
                    "object_id": str(subject),
                    "details": json.dumps(
                        {
                            "result": "SUCCESS",
                            "source": "explicit_bootstrap",
                            "username": account["username"],
                            "role": account["role"],
                        },
                        sort_keys=True,
                    ),
                },
            )


def main() -> int:
    """provision 성공 여부만 stdout·exit code로 반환하고 예외·credential은 숨긴다."""

    try:
        database_url, require_subject_match, accounts = _read_request()
        asyncio.run(
            _provision(
                database_url,
                accounts,
                require_subject_match=require_subject_match,
            )
        )
    except Exception:
        print("account provisioning failed", file=sys.stderr)
        return 1
    print('{"status":"ok","processed":2}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
