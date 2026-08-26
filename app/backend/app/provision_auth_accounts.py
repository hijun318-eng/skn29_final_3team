"""대화형 비밀번호 입력으로 DB 로그인 계정을 원자적으로 provision한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from getpass import getpass
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.contracts import Role


@dataclass(frozen=True)
class AccountDefinition:
    """운영자가 명시한 username·Role과 선택적 기존 subject를 표현한다."""

    username: str
    role: Role
    subject: UUID | None = None


def _parse_account(raw: str) -> AccountDefinition:
    parts = raw.split(":")
    if len(parts) not in {2, 3}:
        raise argparse.ArgumentTypeError("account must be USERNAME:ROLE[:SUBJECT]")
    username = parts[0].strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,64}", username):
        raise argparse.ArgumentTypeError("username is invalid")
    try:
        role = Role(parts[1].strip())
        subject = UUID(parts[2]) if len(parts) == 3 else None
    except ValueError as exc:
        raise argparse.ArgumentTypeError("role or subject is invalid") from exc
    return AccountDefinition(username=username, role=role, subject=subject)


def _database_url() -> str:
    raw = os.getenv("APP_DATABASE_URL", "").strip()
    if not raw:
        raise RuntimeError("APP_DATABASE_URL is required")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("APP_DATABASE_URL must use PostgreSQL")
    return url.set(drivername="postgresql+psycopg").render_as_string(
        hide_password=False
    )


def _read_verifier(username: str) -> tuple[str, str, int]:
    if not sys.stdin.isatty():
        raise RuntimeError("password provisioning requires an interactive terminal")
    password = getpass(f"Password for {username}: ")
    try:
        if len(password) < 12:
            raise RuntimeError("password must contain at least 12 characters")
        iterations = 210_000
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        ).hex()
        encoded_salt = urlsafe_b64encode(salt).decode("ascii").rstrip("=")
        return encoded_salt, digest, iterations
    finally:
        password = ""


def _provision(
    definitions: tuple[AccountDefinition, ...],
    verifiers: dict[str, tuple[str, str, int]],
    *,
    replace: bool,
) -> dict[str, object]:
    engine = create_engine(_database_url())
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "LOCK TABLE security.auth_accounts "
                    "IN SHARE ROW EXCLUSIVE MODE"
                )
            )
            existing = {
                row.username: UUID(str(row.subject))
                for row in connection.execute(
                    text("SELECT username, subject FROM security.auth_accounts FOR UPDATE")
                )
            }
            resolved_subjects: dict[str, UUID] = {}
            for definition in definitions:
                current_subject = existing.get(definition.username)
                if (
                    current_subject is not None
                    and definition.subject is not None
                    and current_subject != definition.subject
                ):
                    raise RuntimeError(
                        f"subject mismatch for existing account {definition.username}"
                    )
                subject = current_subject or definition.subject or uuid4()
                salt, digest, iterations = verifiers[definition.username]
                stored_subject = connection.execute(
                    text(
                        """
                        INSERT INTO security.auth_accounts (
                            username, password_salt, password_hash,
                            password_iterations, subject, role, active
                        ) VALUES (
                            :username, :salt, :digest, :iterations,
                            :subject, :role, true
                        )
                        ON CONFLICT (username) DO UPDATE SET
                            password_salt = EXCLUDED.password_salt,
                            password_hash = EXCLUDED.password_hash,
                            password_iterations = EXCLUDED.password_iterations,
                            role = EXCLUDED.role,
                            active = true,
                            updated_at = now()
                        RETURNING subject
                        """
                    ),
                    {
                        "username": definition.username,
                        "salt": salt,
                        "digest": digest,
                        "iterations": iterations,
                        "subject": subject,
                        "role": definition.role.value,
                    },
                ).scalar_one()
                resolved_subjects[definition.username] = UUID(str(stored_subject))

            if replace:
                for username in set(existing) - set(resolved_subjects):
                    connection.execute(
                        text("DELETE FROM security.auth_accounts WHERE username = :username"),
                        {"username": username},
                    )
                revoked = connection.execute(
                    text(
                        "UPDATE security.auth_sessions SET revoked_at = now() "
                        "WHERE revoked_at IS NULL"
                    )
                ).rowcount
            else:
                revoked = 0
                for subject in resolved_subjects.values():
                    revoked += connection.execute(
                        text(
                            "UPDATE security.auth_sessions SET revoked_at = now() "
                            "WHERE subject = :subject AND revoked_at IS NULL"
                        ),
                        {"subject": subject},
                    ).rowcount
            account_count = connection.execute(
                text("SELECT count(*) FROM security.auth_accounts")
            ).scalar_one()
            if replace and account_count != len(definitions):
                raise RuntimeError("replace did not converge to the requested account set")
    finally:
        engine.dispose()
    return {
        "status": "PROVISIONED",
        "account_count": int(account_count),
        "roles": [definition.role.value for definition in definitions],
        "revoked_sessions": int(revoked),
        "password_storage": "PBKDF2-SHA256",
    }


def main() -> int:
    """명시 계정을 upsert하고 ``--replace`` 시 그 외 계정과 모든 세션을 제거한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--account",
        action="append",
        required=True,
        type=_parse_account,
        help="USERNAME:ROLE[:SUBJECT]",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="delete accounts not listed and revoke every active session",
    )
    arguments = parser.parse_args()
    definitions = tuple(arguments.account)
    usernames = [item.username for item in definitions]
    subjects = [item.subject for item in definitions if item.subject is not None]
    if len(usernames) != len(set(usernames)) or len(subjects) != len(set(subjects)):
        parser.error("account usernames and explicit subjects must be unique")
    verifiers = {item.username: _read_verifier(item.username) for item in definitions}
    result = _provision(definitions, verifiers, replace=arguments.replace)
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
