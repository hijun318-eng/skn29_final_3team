"""외부 secret 파일의 계정·token digest를 엄격한 schema와 유효기간으로 읽어 인증 주체로 변환한다."""

from __future__ import annotations

import json
import os
from base64 import urlsafe_b64decode
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.contracts import Role


@dataclass(frozen=True)
class Principal:
    """검증된 계정 또는 token digest가 가리키는 UUID subject와 허용 ``Role``을 보존한다.

    인증 경계는 이 객체만 request context로 전달하며 username·password·token 원문은
    포함하지 않아 이후 권한 검사와 trace에서 credential이 노출되지 않게 한다.
    """
    subject: UUID
    role: Role


class AuthenticationError(ValueError):
    """인증 거부(401), 권한 거부(403), 인증 저장소 장애(503)를 안전한 메시지와 함께 전달한다."""
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
    "username",
    "password_salt",
    "password_hash",
    "password_iterations",
    "subject",
    "role",
    "active",
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
                not isinstance(username, str)
                or not 3 <= len(username) <= 64
                or username != username.strip().lower()
                or username in usernames
                or not isinstance(salt, str)
                or len(salt) < 16
                or not isinstance(digest, str)
                or len(digest) != 64
                or not isinstance(iterations, int)
                or iterations < 200_000
                or not isinstance(item["active"], bool)
            ):
                raise ValueError("account record is invalid")
            bytes.fromhex(digest)
            urlsafe_b64decode(salt + "=" * (-len(salt) % 4))
            records.append(
                _AccountRecord(
                    username=username,
                    password_salt=salt,
                    password_hash=digest,
                    password_iterations=iterations,
                    principal=Principal(
                        UUID(str(item["subject"])), Role(str(item["role"]))
                    ),
                    active=item["active"],
                )
            )
            usernames.add(username)
        return tuple(records)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _authentication_error(503) from exc


def _configured_principal_path() -> Path:
    configured_path = os.getenv("AUTH_PRINCIPALS_FILE", "").strip()
    if not configured_path:
        raise _authentication_error(503)
    return Path(configured_path)


def _principal_store_kind(path: Path) -> str:
    try:
        if path.stat().st_size > 1_048_576:
            raise ValueError("principal file is too large")
        raw = json.loads(path.read_text(encoding="utf-8"))
        first = raw[0] if isinstance(raw, list) and raw else None
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise _authentication_error(503) from error
    if not isinstance(first, dict):
        raise _authentication_error(503)
    if set(first) == _ACCOUNT_FIELDS:
        return "account"
    if set(first) == _RECORD_FIELDS:
        return "digest"
    raise _authentication_error(503)


def principal_store_ready(
    path: Path,
    *,
    now: datetime | None = None,
) -> bool:
    """principal 파일 전체를 운영 parser로 검증하고 현재 유효한 주체 존재 여부를 반환한다.

    계정 저장소는 ``active`` 계정을, token digest 저장소는 현재 UTC가 유효기간 안인
    record를 최소 하나 요구한다. 형식·중복·hash·UUID·role 오류는 인증 저장소 장애로
    전파하며 credential이나 digest 원문은 반환하거나 기록하지 않는다.
    """

    kind = _principal_store_kind(path)
    if kind == "account":
        return any(record.active for record in _load_accounts(path))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise _authentication_error(503)
    current = current.astimezone(timezone.utc)
    return any(
        record.not_before <= current < record.expires_at
        for record in _load_principals(path)
    )
