from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from psycopg.errors import UniqueViolation

from app.config import ProbeTarget, Settings
from app.db import Database
from app.repositories import AuditRepository, SessionRepository, UserRepository
from app.schemas import AdminRole, ConnectionList, ConnectionOut, UserCreate, UserPatch


class ServiceError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.users = UserRepository()
        self.sessions = SessionRepository()
        self.audit = AuditRepository()
        self.passwords = PasswordHasher()

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def bootstrap(self) -> None:
        async with self.db.connection() as connection, connection.transaction():
            if await self.users.by_email(connection, self.settings.bootstrap_email):
                return
            payload = UserCreate(
                name=self.settings.bootstrap_name,
                email=self.settings.bootstrap_email,
                password=self.settings.bootstrap_password,
                role=AdminRole.ADMIN,
            )
            user = await self.users.create(connection, payload, self.passwords.hash(payload.password))
            await self.audit.record(
                connection, "ADMIN_USER.CREATE", "SUCCESS", "bootstrap",
                actor_email="system", target_type="ADMIN_USER", target_id=str(user["id"]),
                detail={"bootstrap": True},
            )

    async def login(self, email: str, password: str, request_id: str) -> tuple[dict[str, Any], str]:
        async with self.db.connection() as connection, connection.transaction():
            user = await self.users.by_email(connection, email)
            valid = bool(user and user["is_active"])
            if valid:
                try:
                    self.passwords.verify(user["password_hash"], password)
                except VerifyMismatchError:
                    valid = False
            if not valid:
                await self.audit.record(
                    connection, "AUTH.LOGIN.FAIL", "FAILED", request_id, actor_email=email
                )
                raise ServiceError(401, "계정 또는 비밀번호가 올바르지 않습니다.")
            token = secrets.token_urlsafe(32)
            expires = datetime.now(timezone.utc) + timedelta(seconds=self.settings.session_ttl_seconds)
            await self.sessions.create(connection, user["id"], self.token_hash(token), expires)
            await self.audit.record(connection, "AUTH.LOGIN.SUCCESS", "SUCCESS", request_id, actor=user)
            return user, token

    async def current(self, token: str) -> dict[str, Any] | None:
        async with self.db.connection() as connection:
            return await self.sessions.resolve(connection, self.token_hash(token))

    async def logout(self, token: str, actor: dict[str, Any], request_id: str) -> None:
        async with self.db.connection() as connection, connection.transaction():
            await self.sessions.delete(connection, self.token_hash(token))
            await self.audit.record(connection, "AUTH.LOGOUT", "SUCCESS", request_id, actor=actor)


class UserService:
    def __init__(self, db: Database, passwords: PasswordHasher) -> None:
        self.db = db
        self.passwords = passwords
        self.users = UserRepository()
        self.audit = AuditRepository()

    async def list(self) -> list[dict[str, Any]]:
        async with self.db.connection() as connection:
            return await self.users.list(connection)

    async def create(self, payload: UserCreate, actor: dict[str, Any], request_id: str) -> dict[str, Any]:
        try:
            async with self.db.connection() as connection, connection.transaction():
                user = await self.users.create(connection, payload, self.passwords.hash(payload.password))
                await self.audit.record(
                    connection, "ADMIN_USER.CREATE", "SUCCESS", request_id, actor,
                    target_type="ADMIN_USER", target_id=str(user["id"]),
                    detail={"email": user["email"], "role": user["role"]},
                )
                return user
        except UniqueViolation as error:
            raise ServiceError(409, "이미 등록된 계정입니다.") from error

    async def update(
        self, user_id: UUID, payload: UserPatch, actor: dict[str, Any], request_id: str
    ) -> dict[str, Any]:
        try:
            async with self.db.connection() as connection, connection.transaction():
                current = await self.users.by_id(connection, user_id)
                if not current:
                    raise ServiceError(404, "관리자 계정을 찾을 수 없습니다.")
                removing_admin = current["role"] == "ADMIN" and current["is_active"] and (
                    payload.role == AdminRole.VIEWER or payload.is_active is False
                )
                if removing_admin and await self.users.active_admin_count(connection) <= 1:
                    raise ServiceError(409, "마지막 활성 ADMIN 계정은 변경할 수 없습니다.")
                password_hash = self.passwords.hash(payload.password) if payload.password else None
                user = await self.users.update(connection, user_id, payload, password_hash)
                await self.audit.record(
                    connection, "ADMIN_USER.UPDATE", "SUCCESS", request_id, actor,
                    target_type="ADMIN_USER", target_id=str(user_id),
                    detail={"changed_fields": sorted(payload.model_fields_set)},
                )
                return user
        except UniqueViolation as error:
            raise ServiceError(409, "이미 등록된 계정입니다.") from error

    async def delete(self, user_id: UUID, actor: dict[str, Any], request_id: str) -> None:
        async with self.db.connection() as connection, connection.transaction():
            current = await self.users.by_id(connection, user_id)
            if not current:
                raise ServiceError(404, "관리자 계정을 찾을 수 없습니다.")
            if current["role"] == "ADMIN" and current["is_active"]:
                if await self.users.active_admin_count(connection) <= 1:
                    raise ServiceError(409, "마지막 활성 ADMIN 계정은 삭제할 수 없습니다.")
            await self.users.soft_delete(connection, user_id)
            await self.audit.record(
                connection, "ADMIN_USER.DELETE", "SUCCESS", request_id, actor,
                target_type="ADMIN_USER", target_id=str(user_id),
                detail={"email": current["email"]},
            )


class ConnectionService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.audit = AuditRepository()

    async def check(self, actor: dict[str, Any], request_id: str) -> ConnectionList:
        readiness = await self._readiness_dependencies()
        items = await asyncio.gather(
            *(self._probe(target, readiness) for target in self.settings.probes)
        )
        async with self.db.connection() as connection, connection.transaction():
            await self.audit.record(
                connection, "CONNECTION.CHECK", "SUCCESS", request_id, actor,
                target_type="CONNECTION_SET",
                detail={item.key: item.status for item in items},
            )
        return ConnectionList(checked_at=datetime.now(timezone.utc), items=list(items))

    async def _readiness_dependencies(self) -> dict[str, str]:
        if not self.settings.existing_readiness_url:
            return {}
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.probe_timeout_seconds, follow_redirects=True
            ) as client:
                response = await client.get(self.settings.existing_readiness_url)
            payload = response.json()
            dependencies = payload.get("data", {}).get("dependencies", {})
            return dependencies if isinstance(dependencies, dict) else {}
        except (httpx.HTTPError, ValueError, TypeError):
            return {}

    async def _probe(
        self, target: ProbeTarget, readiness: dict[str, str]
    ) -> ConnectionOut:
        if not target.endpoint:
            readiness_key = {
                "app-postgres": "app_postgres",
                "trino": "trino",
                "datahub": "datahub_transport",
                "model": "model",
            }.get(target.key)
            value = readiness.get(readiness_key, "") if readiness_key else ""
            status = "READY" if value == "ready" else "DOWN" if value == "not_ready" else "UNKNOWN"
            return ConnectionOut(
                key=target.key, name=target.name, type=target.type,
                status=status, latency_ms=None,
            )
        started = time.perf_counter()
        status = "DOWN"
        try:
            if target.kind == "tcp":
                host, port = target.endpoint.rsplit(":", 1)
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, int(port)),
                    timeout=self.settings.probe_timeout_seconds,
                )
                writer.close()
                await writer.wait_closed()
                status = "READY"
            elif target.kind == "dsn":
                connection = await psycopg.AsyncConnection.connect(
                    target.endpoint, connect_timeout=max(1, int(self.settings.probe_timeout_seconds))
                )
                try:
                    await connection.execute("SELECT 1")
                finally:
                    await connection.close()
                status = "READY"
            else:
                async with httpx.AsyncClient(
                    timeout=self.settings.probe_timeout_seconds, follow_redirects=True
                ) as client:
                    response = await client.get(target.endpoint)
                status = "READY" if response.status_code < 400 else "DEGRADED" if response.status_code < 500 else "DOWN"
        except (httpx.HTTPError, psycopg.Error, OSError, TimeoutError):
            status = "DOWN"
        latency = round((time.perf_counter() - started) * 1000)
        return ConnectionOut(
            key=target.key, name=target.name, type=target.type,
            status=status, latency_ms=latency,
        )
