"""운영 계정 검증, HMAC 세션 발급, DB revocation과 background 주체 재확인을 구현한다."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.auth_principal_store import (
    AuthenticationError,
    Principal,
    _authentication_error,
    _configured_principal_path,
    _load_accounts,
    _load_principals,
    _principal_store_kind,
)
from app.database import session_scope
from app.authorization import has_capability
from app.contracts import Capability, Role
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


def authenticate_credentials(username: str, password: str) -> Principal:
    """운영 account 파일의 PBKDF2 hash와 입력 비밀번호를 constant-time으로 검증한다.

    존재하지 않거나 비활성인 계정도 같은 해시 비용을 지불한 뒤 동일한 인증 오류를 내어
    사용자명 존재 여부와 비교 위치가 timing으로 노출되지 않게 한다.
    """
    normalized_username = username.strip().lower()
    if not normalized_username or not password:
        raise _authentication_error()
    records = _load_accounts(_configured_principal_path())
    matched = next((record for record in records if record.username == normalized_username), None)
    salt = urlsafe_b64decode((matched.password_salt if matched else "AAAAAAAAAAAAAAAAAAAAAA") + "==")
    iterations = matched.password_iterations if matched else 210_000
    # 존재하지 않는 계정도 동일 PBKDF2 경로를 수행해야 사용자명 존재 여부가 응답 시간으로
    # 새지 않는다. 마지막 비교 역시 constant-time으로 수행해 해시 prefix 추측을 차단한다.
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


async def register_session(token: str, principal: Principal) -> None:
    """세션의 SHA-256 식별자와 권한·유효기간을 한 DB transaction으로 등록한다.

    원문 bearer token은 저장하지 않으며 DB가 없거나 쓰기에 실패하면 503 인증 오류로
    닫아 revocation을 보장할 수 없는 세션이 발급되지 않게 한다.
    """
    database_url = _required_session_store_url()
    if not database_url:
        return
    issued_at, expires_at = _session_window(token)
    try:
        async with session_scope(database_url) as session:
            # 원문 bearer token은 인증 자격 증명이므로 DB에 저장하지 않는다. revocation 조회에는
            # 단방향 SHA-256 식별자만 필요하며 유출 시에도 원문 세션을 바로 재사용할 수 없다.
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
    except SQLAlchemyError as exc:
        raise _authentication_error(503) from exc


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
    database_url = _required_session_store_url()
    if not database_url:
        return
    try:
        async with session_scope(database_url) as session:
            result = await session.execute(text("""
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
    if matched is None or now < matched.not_before or now >= matched.expires_at:
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


async def require_active_subject(
    subject: UUID,
    role: Role,
    *,
    now: datetime | None = None,
) -> Principal:
    """대화형 token을 재사용하지 않고 background 실행 주체의 활성 권한을 다시 확인한다.

    계정 파일이면 active 상태를, digest principal 파일이면 not-before/expiry 구간을 검사하며
    요청 subject와 role이 모두 정확히 일치하지 않으면 403으로 거부한다.
    """
    path = _configured_principal_path()
    kind = await asyncio.to_thread(_principal_store_kind, path)
    if kind == "account":
        records = await asyncio.to_thread(_load_accounts, path)
        matched = next(
            (
                record
                for record in records
                if record.principal.subject == subject
                and record.principal.role is role
                and record.active
            ),
            None,
        )
    else:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        records = await asyncio.to_thread(_load_principals, path)
        matched = next(
            (
                record
                for record in records
                if record.principal.subject == subject
                and record.principal.role is role
                and record.not_before <= current < record.expires_at
            ),
            None,
        )
    if matched is None:
        raise _authentication_error(403)
    return matched.principal


async def require_active_subject_with_capability(
    subject: UUID,
    capability: Capability,
    *,
    now: datetime | None = None,
) -> Principal:
    """Background 실행 전에 주체의 현재 Role이 필요한 Capability를 유지하는지 재확인한다.

    저장된 보고서의 과거 Role을 신뢰하거나 관리자 actor의 권한을 빌리지 않는다. 외부
    principal store에서 같은 subject의 현재 활성 Role을 다시 읽고, 정확히 하나의 Role만
    Capability를 만족할 때 그 Principal을 반환한다. 중복·모호한 Role은 권한 확대로
    보정하지 않고 403으로 닫는다.
    """

    path = _configured_principal_path()
    kind = await asyncio.to_thread(_principal_store_kind, path)
    if kind == "account":
        records = await asyncio.to_thread(_load_accounts, path)
        principals = {
            record.principal
            for record in records
            if record.principal.subject == subject
            and record.active
            and has_capability(record.principal.role, capability)
        }
    else:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        records = await asyncio.to_thread(_load_principals, path)
        principals = {
            record.principal
            for record in records
            if record.principal.subject == subject
            and record.not_before <= current < record.expires_at
            and has_capability(record.principal.role, capability)
        }
    if len(principals) != 1:
        raise _authentication_error(403)
    return next(iter(principals))
