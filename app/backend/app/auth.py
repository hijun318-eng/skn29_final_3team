from __future__ import annotations

import hashlib
import hmac
import json
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from functools import lru_cache
from uuid import UUID, uuid4

from app.contracts import Role
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


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


@dataclass(frozen=True)
class _AccountRecord:
    username: str
    password_salt: str
    password_hash: str
    password_iterations: int
    principal: Principal
    active: bool


_RECORD_FIELDS = {"token_sha256", "subject", "role", "not_before", "expires_at"}
_ACCOUNT_FIELDS = {
    "username", "password_salt", "password_hash", "password_iterations",
    "subject", "role", "active",
}
_TEST_TOKENS = {
    "runtime-test-token": Principal(UUID(int=1), Role.HOTEL_ANALYST),
    "runtime-report-admin-token": Principal(UUID(int=2), Role.REPORT_ADMIN),
    "runtime-data-admin-token": Principal(UUID(int=3), Role.DATA_ADMIN),
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


def _load_accounts(path: Path) -> tuple[_AccountRecord, ...]:
    try:
        if path.stat().st_size > 1_048_576:
            raise ValueError("account file is too large")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not payload:
            raise ValueError("account file must be a non-empty list")
        records: list[_AccountRecord] = []
        usernames: set[str] = set()
        for item in payload:
            if not isinstance(item, dict) or set(item) != _ACCOUNT_FIELDS:
                raise ValueError("account record fields are invalid")
            username = item["username"]
            salt = item["password_salt"]
            digest = item["password_hash"]
            iterations = item["password_iterations"]
            if (
                not isinstance(username, str) or not 3 <= len(username) <= 64
                or username != username.strip().lower() or username in usernames
                or not isinstance(salt, str) or len(salt) < 16
                or not isinstance(digest, str) or len(digest) != 64
                or not isinstance(iterations, int) or iterations < 200_000
                or not isinstance(item["active"], bool)
            ):
                raise ValueError("account record is invalid")
            bytes.fromhex(digest)
            urlsafe_b64decode(salt + "=" * (-len(salt) % 4))
            records.append(_AccountRecord(
                username=username,
                password_salt=salt,
                password_hash=digest,
                password_iterations=iterations,
                principal=Principal(UUID(str(item["subject"])), Role(str(item["role"]))),
                active=item["active"],
            ))
            usernames.add(username)
        return tuple(records)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _authentication_error(503) from exc


def _configured_principal_path() -> Path:
    configured_path = os.getenv("AUTH_PRINCIPALS_FILE", "").strip()
    if not configured_path:
        raise _authentication_error(503)
    return Path(configured_path)


def authenticate_credentials(username: str, password: str) -> Principal:
    normalized_username = username.strip().lower()
    if not normalized_username or not password:
        raise _authentication_error()
    records = _load_accounts(_configured_principal_path())
    matched = next((record for record in records if record.username == normalized_username), None)
    salt = urlsafe_b64decode((matched.password_salt if matched else "AAAAAAAAAAAAAAAAAAAAAA") + "==")
    iterations = matched.password_iterations if matched else 210_000
    supplied_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()
    expected_hash = matched.password_hash if matched else "0" * 64
    if matched is None or not matched.active or not hmac.compare_digest(expected_hash, supplied_hash):
        raise _authentication_error()
    return matched.principal


def _session_secret() -> bytes:
    secret = os.getenv("AUTH_SESSION_SECRET", "").strip()
    if len(secret) < 32:
        raise _authentication_error(503)
    return secret.encode("utf-8")


def issue_session_token(principal: Principal, *, now: datetime | None = None) -> str:
    issued_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ttl = min(86_400, max(900, int(os.getenv("AUTH_SESSION_TTL_SECONDS", "28800"))))
    payload = json.dumps({
        "sid": str(uuid4()),
        "sub": str(principal.subject),
        "role": principal.role.value,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(seconds=ttl)).timestamp()),
    }, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(_session_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"


def _session_principal(token: str, now: datetime) -> Principal:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(_session_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        actual_signature = urlsafe_b64decode(supplied_signature + "=" * (-len(supplied_signature) % 4))
        if not hmac.compare_digest(expected_signature, actual_signature):
            raise ValueError("invalid signature")
        payload = json.loads(urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if set(payload) != {"sid", "sub", "role", "iat", "exp"} or not payload["iat"] <= int(now.timestamp()) < payload["exp"]:
            raise ValueError("invalid session window")
        UUID(str(payload["sid"]))
        principal = Principal(UUID(str(payload["sub"])), Role(str(payload["role"])))
        _assert_session_active(token, principal, now)
        return principal
    except AuthenticationError:
        raise
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise _authentication_error() from exc


@lru_cache(maxsize=2)
def _session_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


def _session_store_url() -> str:
    return os.getenv("APP_RUNTIME_DATABASE_URL", "").strip()


def _session_window(token: str) -> tuple[datetime, datetime]:
    try:
        encoded = token.split(".", 1)[0]
        payload = json.loads(urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        return (
            datetime.fromtimestamp(int(payload["iat"]), timezone.utc),
            datetime.fromtimestamp(int(payload["exp"]), timezone.utc),
        )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise _authentication_error() from exc


def register_session(token: str, principal: Principal) -> None:
    database_url = _session_store_url()
    if not database_url:
        return
    issued_at, expires_at = _session_window(token)
    try:
        with _session_engine(database_url).begin() as connection:
            connection.execute(text("""
                INSERT INTO security.auth_sessions (
                    token_sha256, subject, role, issued_at, expires_at
                ) VALUES (
                    :token_sha256, :subject, :role, :issued_at, :expires_at
                )
            """), {
                "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                "subject": principal.subject,
                "role": principal.role.value,
                "issued_at": issued_at,
                "expires_at": expires_at,
            })
    except SQLAlchemyError as exc:
        raise _authentication_error(503) from exc


def revoke_session(token: str | None) -> None:
    database_url = _session_store_url()
    if not database_url or not token or token.count(".") != 1:
        return
    try:
        with _session_engine(database_url).begin() as connection:
            connection.execute(text("""
                UPDATE security.auth_sessions
                SET revoked_at = now()
                WHERE token_sha256 = :token_sha256 AND revoked_at IS NULL
            """), {"token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest()})
    except SQLAlchemyError as exc:
        raise _authentication_error(503) from exc


def _assert_session_active(token: str, principal: Principal, now: datetime) -> None:
    database_url = _session_store_url()
    if not database_url:
        return
    try:
        with _session_engine(database_url).connect() as connection:
            active = connection.execute(text("""
                SELECT 1
                FROM security.auth_sessions
                WHERE token_sha256 = :token_sha256
                  AND subject = :subject
                  AND role = :role
                  AND revoked_at IS NULL
                  AND issued_at <= :now
                  AND expires_at > :now
            """), {
                "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                "subject": principal.subject,
                "role": principal.role.value,
                "now": now,
            }).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise _authentication_error(503) from exc
    if active is None:
        raise _authentication_error()


def _release_principal(token: str, now: datetime) -> Principal:
    if token.count(".") == 1:
        return _session_principal(token, now)
    records = _load_principals(_configured_principal_path())
    supplied_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    matched = None
    for record in records:
        if hmac.compare_digest(record.token_sha256, supplied_digest):
            matched = record
    if matched is None or now < matched.not_before or now >= matched.expires_at:
        raise _authentication_error()
    return matched.principal


def _test_principal(token: str) -> Principal:
    supplied_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    for expected_token, principal in _TEST_TOKENS.items():
        expected_digest = hashlib.sha256(expected_token.encode("utf-8")).hexdigest()
        if hmac.compare_digest(expected_digest, supplied_digest):
            return principal
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
