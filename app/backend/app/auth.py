"""운영 계정 검증, HMAC 세션 발급, DB revocation과 background 주체 재확인을 구현한다."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_bytes
from uuid import UUID, uuid4

from app.auth_principal_store import (
    AuthenticationError,
    Principal,
    _authentication_error,
    _configured_principal_path,
    _load_principals,
)
from app.database import DatabaseConfigurationError, session_scope
from app.authorization import has_capability
from app.contracts import Capability, Role
from app.user_account_roles import is_internal_user_account_role
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


PASSWORD_ITERATIONS = 210_000


@dataclass(frozen=True)
class _AccountCredential:
    """DB에서 읽은 단일 로그인 verifier와 현재 principal을 묶는다."""

    password_salt: str
    password_hash: str
    password_iterations: int
    principal: Principal
    active: bool


def _account_credential(row: Mapping[str, object]) -> _AccountCredential:
    try:
        values = row  # SQLAlchemy RowMapping과 test mapping은 같은 key 계약을 사용한다.
        salt = str(values["password_salt"])
        digest = str(values["password_hash"])
        iterations = int(values["password_iterations"])
        active = values["active"]
        decoded_salt = urlsafe_b64decode(salt + "=" * (-len(salt) % 4))
        bytes.fromhex(digest)
        if (
            len(decoded_salt) < 16
            or len(digest) != 64
            or iterations < 200_000
            or not isinstance(active, bool)
        ):
            raise ValueError("invalid account verifier")
        return _AccountCredential(
            password_salt=salt,
            password_hash=digest,
            password_iterations=iterations,
            principal=Principal(UUID(str(values["subject"])), Role(str(values["role"]))),
            active=active,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _authentication_error(503) from exc


async def _load_account(username: str) -> _AccountCredential | None:
    try:
        async with session_scope(_required_session_store_url()) as session:
            result = await session.execute(
                text(
                    """
                    SELECT password_salt, password_hash, password_iterations,
                           subject, role, active
                    FROM security.auth_accounts
                    WHERE username = :username AND deleted_at IS NULL
                    """
                ),
                {"username": username},
            )
            row = result.mappings().one_or_none()
    except AuthenticationError:
        raise
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise _authentication_error(503) from exc
    return _account_credential(row) if row is not None else None


async def _load_active_principal(subject: UUID) -> Principal | None:
    try:
        async with session_scope(_required_session_store_url()) as session:
            result = await session.execute(
                text(
                    """
                    SELECT subject, role
                    FROM security.auth_accounts
                    WHERE subject = :subject
                      AND active
                      AND deleted_at IS NULL
                      AND role IN ('analyst', 'platform_admin')
                    """
                ),
                {"subject": subject},
            )
            row = result.mappings().one_or_none()
    except AuthenticationError:
        raise
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise _authentication_error(503) from exc
    if row is None:
        return None
    try:
        return Principal(UUID(str(row["subject"])), Role(str(row["role"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise _authentication_error(503) from exc


async def auth_account_store_ready(database_url: str) -> bool:
    """runtime DB에 활성 로그인 계정이 하나 이상 존재하는지 실제 SELECT로 확인한다."""

    try:
        async with session_scope(database_url) as session:
            result = await session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM security.auth_accounts "
                    "WHERE active AND deleted_at IS NULL "
                    "AND role IN ('analyst', 'platform_admin'))"
                )
            )
            return bool(result.scalar_one())
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise _authentication_error(503) from exc


def _derive_password_hash(password: str, salt: bytes, iterations: int) -> str:
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


async def _authenticate_credentials_in_session(
    session: AsyncSession, username: str, password: str
) -> Principal:
    """계정 row를 공유 잠금한 채 credential을 검증해 session 등록과 직렬화한다."""

    normalized_username = username.strip().lower()
    if not normalized_username or not password:
        raise _authentication_error()
    result = await session.execute(
        text(
            """
            SELECT password_salt, password_hash, password_iterations,
                   subject, role, active, deleted_at
            FROM security.auth_accounts
            WHERE username = :username
            FOR SHARE
            """
        ),
        {"username": normalized_username},
    )
    row = result.mappings().one_or_none()
    matched = _account_credential(row) if row is not None else None
    salt = urlsafe_b64decode(
        (matched.password_salt if matched else "AAAAAAAAAAAAAAAAAAAAAA") + "=="
    )
    iterations = matched.password_iterations if matched else PASSWORD_ITERATIONS
    supplied_hash = await asyncio.to_thread(
        _derive_password_hash, password, salt, iterations
    )
    expected_hash = matched.password_hash if matched else "0" * 64
    if (
        matched is None
        or not matched.active
        or row["deleted_at"] is not None
        or not is_internal_user_account_role(matched.principal.role)
        or not hmac.compare_digest(expected_hash, supplied_hash)
    ):
        raise _authentication_error()
    return matched.principal


async def authenticate_credentials(username: str, password: str) -> Principal:
    """DB account의 PBKDF2 hash와 입력 비밀번호를 constant-time으로 검증한다.

    존재하지 않거나 비활성인 계정도 같은 해시 비용을 지불한 뒤 동일한 인증 오류를 내어
    사용자명 존재 여부와 비교 위치가 timing으로 노출되지 않게 한다.
    """
    normalized_username = username.strip().lower()
    if not normalized_username or not password:
        raise _authentication_error()
    matched = await _load_account(normalized_username)
    salt = urlsafe_b64decode((matched.password_salt if matched else "AAAAAAAAAAAAAAAAAAAAAA") + "==")
    iterations = matched.password_iterations if matched else PASSWORD_ITERATIONS
    # 존재하지 않는 계정도 동일 PBKDF2 경로를 수행해야 사용자명 존재 여부가 응답 시간으로
    # 새지 않는다. 마지막 비교 역시 constant-time으로 수행해 해시 prefix 추측을 차단한다.
    supplied_hash = await asyncio.to_thread(
        _derive_password_hash, password, salt, iterations
    )
    expected_hash = matched.password_hash if matched else "0" * 64
    if (
        matched is None
        or not matched.active
        or not is_internal_user_account_role(matched.principal.role)
        or not hmac.compare_digest(expected_hash, supplied_hash)
    ):
        raise _authentication_error()
    return matched.principal


def _session_secret() -> bytes:
    secret = os.getenv("AUTH_SESSION_SECRET", "").strip()
    if len(secret) < 32:
        raise _authentication_error(503)
    return secret.encode("utf-8")


def issue_session_token(principal: Principal, *, now: datetime | None = None) -> str:
    """주체·역할·고유 세션 ID·제한된 유효기간을 담은 HMAC 서명 token을 발급한다."""
    issued_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ttl = min(86_400, max(900, int(os.getenv("AUTH_SESSION_TTL_SECONDS", "86400"))))
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


async def _session_principal(token: str, now: datetime) -> Principal:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(_session_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        actual_signature = urlsafe_b64decode(supplied_signature + "=" * (-len(supplied_signature) % 4))
        # payload를 해석하기 전에 HMAC을 constant-time 비교해야 공격자가 변조한 role/sub를
        # 파서나 DB 조회 경계까지 전달하지 못하며 signature byte 위치도 노출하지 않는다.
        if not hmac.compare_digest(expected_signature, actual_signature):
            raise ValueError("invalid signature")
        payload = json.loads(urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if set(payload) != {"sid", "sub", "role", "iat", "exp"} or not payload["iat"] <= int(now.timestamp()) < payload["exp"]:
            raise ValueError("invalid session window")
        UUID(str(payload["sid"]))
        principal = Principal(UUID(str(payload["sub"])), Role(str(payload["role"])))
        await _assert_session_active(token, principal, now)
        return principal
    except AuthenticationError:
        raise
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise _authentication_error() from exc


def _session_store_url() -> str:
    return os.getenv("APP_RUNTIME_DATABASE_URL", "").strip()


def _required_session_store_url() -> str:
    database_url = _session_store_url()
    if database_url:
        return database_url
    raise _authentication_error(503)


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


async def _insert_session(
    session: AsyncSession, token: str, principal: Principal
) -> None:
    """호출자가 소유한 transaction에 원문 token 없는 session digest를 등록한다."""

    issued_at, expires_at = _session_window(token)
    await session.execute(text("""
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


async def register_session(token: str, principal: Principal) -> None:
    """기존 호출자를 위해 독립 transaction으로 session digest를 등록한다."""

    try:
        async with session_scope(_required_session_store_url()) as session:
            await _insert_session(session, token, principal)
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise _authentication_error(503) from exc


async def create_authenticated_session(
    username: str, password: str
) -> tuple[Principal, str]:
    """credential 검증과 session 등록을 같은 계정 잠금 transaction으로 완료한다."""

    try:
        async with session_scope(_required_session_store_url()) as session:
            principal = await _authenticate_credentials_in_session(
                session, username, password
            )
            token = issue_session_token(principal)
            await _insert_session(session, token, principal)
    except AuthenticationError:
        raise
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise _authentication_error(503) from exc
    return principal, token


async def revoke_session(token: str | None) -> None:
    """현재 token의 SHA-256 행을 원자적으로 폐기하고 저장소 장애를 인증 실패로 전달한다."""
    database_url = _required_session_store_url()
    if not database_url or not token or token.count(".") != 1:
        return
    try:
        async with session_scope(database_url) as session:
            await session.execute(text("""
                UPDATE security.auth_sessions
                SET revoked_at = now()
                WHERE token_sha256 = :token_sha256 AND revoked_at IS NULL
            """), {"token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest()})
    except SQLAlchemyError as exc:
        raise _authentication_error(503) from exc


async def _assert_session_active(token: str, principal: Principal, now: datetime) -> None:
    if not is_internal_user_account_role(principal.role):
        raise _authentication_error()
    database_url = _required_session_store_url()
    if not database_url:
        return
    try:
        async with session_scope(database_url) as session:
            result = await session.execute(text("""
                SELECT 1
                FROM security.auth_sessions AS sessions
                JOIN security.auth_accounts AS accounts
                  ON accounts.subject = sessions.subject
                 AND accounts.role = sessions.role
                WHERE sessions.token_sha256 = :token_sha256
                  AND sessions.subject = :subject
                  AND sessions.role = :role
                  AND sessions.revoked_at IS NULL
                  AND sessions.issued_at <= :now
                  AND sessions.expires_at > :now
                  AND accounts.active
                  AND accounts.deleted_at IS NULL
                  AND accounts.role IN ('analyst', 'platform_admin')
            """), {
                "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                "subject": principal.subject,
                "role": principal.role.value,
                "now": now,
            })
            active = result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise _authentication_error(503) from exc
    if active is None:
        raise _authentication_error()


async def _release_principal(token: str, now: datetime) -> Principal:
    if token.count(".") == 1:
        return await _session_principal(token, now)
    records = await asyncio.to_thread(
        _load_principals,
        _configured_principal_path(),
    )
    supplied_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    matched = None
    for record in records:
        if hmac.compare_digest(record.token_sha256, supplied_digest):
            matched = record
    if (
        matched is None
        or now < matched.not_before
        or now >= matched.expires_at
        or not is_internal_user_account_role(matched.principal.role)
    ):
        raise _authentication_error()
    return matched.principal


async def authenticate_token(token: str | None, *, now: datetime | None = None) -> Principal:
    """서명·만료·revocation 검증을 통과한 운영 principal만 반환한다."""
    if token is None or not token.strip():
        raise _authentication_error()
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    return await _release_principal(token, current_time.astimezone(timezone.utc))


async def require_active_subject_with_capability(
    subject: UUID,
    capability: Capability,
    *,
    now: datetime | None = None,
) -> Principal:
    """Background 실행 전에 주체의 현재 Role이 필요한 Capability를 유지하는지 재확인한다.

    저장된 보고서의 과거 Role을 신뢰하거나 관리자 actor의 권한을 빌리지 않는다.
    DB 계정 정본에서 같은 subject의 현재 활성 Role을 다시 읽고 Capability를 만족할
    때만 그 Principal을 반환한다. 비활성·삭제·권한 축소는 403으로 닫는다.
    """

    del now  # 공개 계약 호환용이며 DB의 현재 상태는 별도 wall-clock 비교가 필요 없다.
    principal = await _load_active_principal(subject)
    if principal is None or not has_capability(principal.role, capability):
        raise _authentication_error(403)
    return principal
