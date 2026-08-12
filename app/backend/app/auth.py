from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.contracts import Role


@dataclass(frozen=True)
class Principal:
    subject: UUID
    role: Role


class AuthenticationError(ValueError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class _PrincipalRecord:
    token_sha256: str
    principal: Principal
    not_before: datetime
    expires_at: datetime


_RECORD_FIELDS = {"token_sha256", "subject", "role", "not_before", "expires_at"}
_TEST_TOKENS = {
    "runtime-test-token": UUID(int=1),
    "runtime-report-admin-token": UUID(int=2),
    "runtime-data-admin-token": UUID(int=3),
}


def _authentication_error(status_code: int = 401) -> AuthenticationError:
    message = "인증 정보를 확인할 수 없습니다."
    if status_code == 503:
        message = "인증 서비스를 사용할 수 없습니다."
    return AuthenticationError(message, status_code)


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _load_principals(path: Path) -> tuple[_PrincipalRecord, ...]:
    try:
        if path.stat().st_size > 1_048_576:
            raise ValueError("principal file is too large")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not payload:
            raise ValueError("principal file must be a non-empty list")

        records: list[_PrincipalRecord] = []
        digests: set[str] = set()
        for item in payload:
            if not isinstance(item, dict) or set(item) != _RECORD_FIELDS:
                raise ValueError("principal record fields are invalid")
            digest = item["token_sha256"]
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or digest.lower() != digest
                or any(character not in "0123456789abcdef" for character in digest)
                or digest in digests
            ):
                raise ValueError("token digest is invalid or duplicated")
            record = _PrincipalRecord(
                token_sha256=digest,
                principal=Principal(UUID(str(item["subject"])), Role(str(item["role"]))),
                not_before=_parse_timestamp(item["not_before"]),
                expires_at=_parse_timestamp(item["expires_at"]),
            )
            if record.not_before >= record.expires_at:
                raise ValueError("principal validity window is invalid")
            digests.add(digest)
            records.append(record)
        return tuple(records)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _authentication_error(503) from exc


def _release_principal(token: str, now: datetime) -> Principal:
    configured_path = os.getenv("AUTH_PRINCIPALS_FILE", "").strip()
    if not configured_path:
        raise _authentication_error(503)
    records = _load_principals(Path(configured_path))
    supplied_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    matched = None
    for record in records:
        if hmac.compare_digest(record.token_sha256, supplied_digest):
            matched = record
    if matched is None or now < matched.not_before or now >= matched.expires_at:
        raise _authentication_error()
    return matched.principal


def _test_principal(token: str) -> Principal:
    from app.access_policy import test_seed_role

    supplied_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    for expected_token, subject in _TEST_TOKENS.items():
        expected_digest = hashlib.sha256(expected_token.encode("utf-8")).hexdigest()
        if hmac.compare_digest(expected_digest, supplied_digest):
            try:
                role = test_seed_role(subject)
            except RuntimeError as error:
                raise _authentication_error(503) from error
            if role is None:
                raise _authentication_error(503)
            return Principal(subject, role)
    raise _authentication_error()


def authenticate_token(token: str | None, *, now: datetime | None = None) -> Principal:
    if token is None or not token.strip():
        raise _authentication_error()
    mode = os.getenv("AUTH_MODE", "release").strip().lower()
    if mode == "test":
        return _test_principal(token)
    if mode != "release":
        raise _authentication_error(503)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    return _release_principal(token, current_time.astimezone(timezone.utc))
