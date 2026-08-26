"""App PostgreSQL 계정 검증, PBKDF2 verifier와 revocable HMAC 세션을 소유한다.

사람 계정의 권위 입력은 ``security.accounts`` 한 곳이며 파일 principal이나 합성 계정으로
DB 장애를 우회하지 않는다. 원문 비밀번호·세션 token은 반환용 경계 밖에 저장하지 않는다.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from secrets import token_bytes
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_principal_store import (
    AuthenticationError,
    Principal,
    authentication_error,
)
from app.authorization import has_capability
from app.contracts import Capability, Role
from app.database import DatabaseConfigurationError, session_scope


PASSWORD_ITERATIONS = 210_000
_DUMMY_SALT = bytes(32)


def _derive_password_hash(password: str, salt: bytes, iterations: int) -> str:
    """PBKDF2-SHA256 verifier를 생성하며 입력 원문을 저장하거나 기록하지 않는다."""

    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    ).hex()


async def create_password_verifier(password: str) -> tuple[str, str, int]:
    """관리 계정 저장용 random salt와 PBKDF2 verifier를 event loop 밖에서 생성한다."""

    if not 12 <= len(password) <= 128:
        raise ValueError("새 비밀번호는 12~128자여야 합니다.")
    salt = token_bytes(32)
    digest = await asyncio.to_thread(
        _derive_password_hash, password, salt, PASSWORD_ITERATIONS
    )
    encoded_salt = urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    return encoded_salt, digest, PASSWORD_ITERATIONS


async def _authenticate_credentials(
    session: AsyncSession, username: str, password: str
) -> Principal:
    """잠긴 DB 계정 verifier와 입력 비밀번호를 constant-time으로 검증한다.

    미존재·비활성·삭제 계정도 같은 PBKDF2 비용과 공개 오류를 사용한다. DB 조회 실패나
    손상된 verifier 계약은 인증 실패로 가장하지 않고 503으로 fail closed한다. 계정 row의
    ``FOR SHARE`` lock은 호출 transaction이 session을 등록할 때까지 reset·권한 변경과
    직렬화되며, username 미존재에는 잠글 row가 없지만 새 계정 생성과 구 credential 경합이 없다.
    """

    normalized_username = username.strip().lower()
    if not normalized_username or not password:
        raise authentication_error()
    result = await session.execute(
        text(
            """
            SELECT subject, role, password_salt, password_hash,
                   password_iterations, active, deleted_at
            FROM security.accounts
            WHERE username = :username
            FOR SHARE
            """
        ),
        {"username": normalized_username},
    )
    record = result.mappings().one_or_none()

    try:
        encoded_salt = str(record["password_salt"]) if record is not None else ""
        salt = (
            urlsafe_b64decode(encoded_salt + "=" * (-len(encoded_salt) % 4))
            if record is not None
            else _DUMMY_SALT
        )
        iterations = (
            int(record["password_iterations"])
            if record is not None
            else PASSWORD_ITERATIONS
        )
        expected_hash = str(record["password_hash"]) if record is not None else "0" * 64
    except (TypeError, ValueError) as exc:
        raise authentication_error(503) from exc

    supplied_hash = await asyncio.to_thread(
        _derive_password_hash, password, salt, iterations
    )
    if (
        record is None
        or not bool(record["active"])
        or record["deleted_at"] is not None
        or not hmac.compare_digest(expected_hash, supplied_hash)
    ):
        raise authentication_error()
    try:
        return Principal(UUID(str(record["subject"])), Role(str(record["role"])))
    except ValueError as exc:
        raise authentication_error(503) from exc


def _session_secret() -> bytes:
    secret = os.getenv("AUTH_SESSION_SECRET", "").strip()
    if len(secret) < 32:
        raise authentication_error(503)
    return secret.encode("utf-8")


def issue_session_token(principal: Principal, *, now: datetime | None = None) -> str:
    """주체·역할·고유 세션 ID·제한된 유효기간을 담은 HMAC 서명 token을 발급한다."""

    issued_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ttl = min(86_400, max(900, int(os.getenv("AUTH_SESSION_TTL_SECONDS", "86400"))))
    payload = json.dumps(
        {
            "sid": str(uuid4()),
            "sub": str(principal.subject),
            "role": principal.role.value,
            "iat": int(issued_at.timestamp()),
            "exp": int((issued_at + timedelta(seconds=ttl)).timestamp()),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(
        _session_secret(), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"


def _required_session_store_url() -> str:
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "").strip()
    if database_url:
        return database_url
    raise authentication_error(503)


def _session_window(token: str) -> tuple[datetime, datetime]:
    try:
        encoded = token.split(".", 1)[0]
        payload = json.loads(urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        return (
            datetime.fromtimestamp(int(payload["iat"]), timezone.utc),
            datetime.fromtimestamp(int(payload["exp"]), timezone.utc),
        )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise authentication_error() from exc


async def _insert_session(
    session: AsyncSession, token: str, principal: Principal
) -> None:
    """호출자가 잠근 계정과 같은 transaction에 session digest를 등록한다."""

    issued_at, expires_at = _session_window(token)
    await session.execute(
        text(
            """
            INSERT INTO security.auth_sessions (
                token_sha256, subject, role, issued_at, expires_at
            ) VALUES (
                :token_sha256, :subject, :role, :issued_at, :expires_at
            )
            """
        ),
        {
            "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "subject": principal.subject,
            "role": principal.role.value,
            "issued_at": issued_at,
            "expires_at": expires_at,
        },
    )


async def create_authenticated_session(
    username: str, password: str
) -> tuple[Principal, str]:
    """credential 검증과 revocable session 등록을 계정 row lock의 한 transaction으로 완료한다.

    비밀번호 reset·Role·active 변경은 같은 row의 ``FOR UPDATE``를 사용하므로, 로그인보다
    먼저 끝나면 새 verifier로 검증되고 로그인 뒤에 실행되면 방금 삽입한 session까지 폐기한다.
    """

    try:
        async with session_scope(_required_session_store_url()) as session:
            principal = await _authenticate_credentials(session, username, password)
            token = issue_session_token(principal)
            await _insert_session(session, token, principal)
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise authentication_error(503) from exc
    return principal, token


async def revoke_session(token: str | None) -> None:
    """현재 token의 SHA-256 행을 원자적으로 폐기하고 저장소 장애를 전달한다."""

    if not token or token.count(".") != 1:
        return
    try:
        async with session_scope(_required_session_store_url()) as session:
            await session.execute(
                text(
                    """
                    UPDATE security.auth_sessions
                    SET revoked_at = now()
                    WHERE token_sha256 = :token_sha256 AND revoked_at IS NULL
                    """
                ),
                {"token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest()},
            )
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise authentication_error(503) from exc


async def _assert_session_active(
    token: str, principal: Principal, now: datetime
) -> None:
    try:
        async with session_scope(_required_session_store_url()) as session:
            result = await session.execute(
                text(
                    """
                    SELECT 1
                    FROM security.auth_sessions AS auth_session
                    JOIN security.accounts AS account
                      ON account.subject = auth_session.subject
                     AND account.role = auth_session.role
                     AND account.active
                     AND account.deleted_at IS NULL
                    WHERE auth_session.token_sha256 = :token_sha256
                      AND auth_session.subject = :subject
                      AND auth_session.role = :role
                      AND auth_session.revoked_at IS NULL
                      AND auth_session.issued_at <= :now
                      AND auth_session.expires_at > :now
                    """
                ),
                {
                    "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                    "subject": principal.subject,
                    "role": principal.role.value,
                    "now": now,
                },
            )
            active = result.scalar_one_or_none()
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise authentication_error(503) from exc
    if active is None:
        raise authentication_error()


async def _session_principal(token: str, now: datetime) -> Principal:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(
            _session_secret(), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        actual_signature = urlsafe_b64decode(
            supplied_signature + "=" * (-len(supplied_signature) % 4)
        )
        if not hmac.compare_digest(expected_signature, actual_signature):
            raise ValueError("invalid signature")
        payload = json.loads(
            urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        )
        if (
            set(payload) != {"sid", "sub", "role", "iat", "exp"}
            or not payload["iat"] <= int(now.timestamp()) < payload["exp"]
        ):
            raise ValueError("invalid session window")
        UUID(str(payload["sid"]))
        principal = Principal(UUID(str(payload["sub"])), Role(str(payload["role"])))
        await _assert_session_active(token, principal, now)
        return principal
    except AuthenticationError:
        raise
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise authentication_error() from exc


async def authenticate_token(
    token: str | None, *, now: datetime | None = None
) -> Principal:
    """서명·만료·DB revocation과 현재 계정 상태를 통과한 세션 principal만 반환한다."""

    if token is None or not token.strip() or token.count(".") != 1:
        raise authentication_error()
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    return await _session_principal(token, current_time.astimezone(timezone.utc))


async def _active_account_principal(subject: UUID) -> Principal:
    try:
        async with session_scope(_required_session_store_url()) as session:
            result = await session.execute(
                text(
                    """
                    SELECT subject, role
                    FROM security.accounts
                    WHERE subject = :subject AND active AND deleted_at IS NULL
                    """
                ),
                {"subject": subject},
            )
            record = result.mappings().one_or_none()
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise authentication_error(503) from exc
    if record is None:
        raise authentication_error(403)
    try:
        return Principal(UUID(str(record["subject"])), Role(str(record["role"])))
    except ValueError as exc:
        raise authentication_error(503) from exc


async def require_active_subject(
    subject: UUID,
    role: Role,
    *,
    now: datetime | None = None,
) -> Principal:
    """Background 실행 전에 DB 계정이 같은 Role로 활성 상태인지 재확인한다."""

    del now
    principal = await _active_account_principal(subject)
    if principal.role is not role:
        raise authentication_error(403)
    return principal


async def require_active_subject_with_capability(
    subject: UUID,
    capability: Capability,
    *,
    now: datetime | None = None,
) -> Principal:
    """Background 실행 전에 DB 계정의 현재 Role이 필요한 Capability를 유지하는지 확인한다."""

    del now
    principal = await _active_account_principal(subject)
    if not has_capability(principal.role, capability):
        raise authentication_error(403)
    return principal
