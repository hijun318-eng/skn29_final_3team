from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from psycopg import AsyncConnection

from app.schemas import AdminRole, UserCreate, UserPatch


class UserRepository:
    async def list(self, connection: AsyncConnection) -> list[dict[str, Any]]:
        result = await connection.execute(
            """SELECT id, name, email, role, is_active, created_at, updated_at
               FROM admin_users WHERE deleted_at IS NULL ORDER BY created_at DESC"""
        )
        return list(await result.fetchall())

    async def by_email(self, connection: AsyncConnection, email: str) -> dict[str, Any] | None:
        result = await connection.execute(
            "SELECT * FROM admin_users WHERE email = %s AND deleted_at IS NULL", (email,)
        )
        return await result.fetchone()

    async def by_id(self, connection: AsyncConnection, user_id: UUID) -> dict[str, Any] | None:
        result = await connection.execute(
            "SELECT * FROM admin_users WHERE id = %s AND deleted_at IS NULL", (user_id,)
        )
        return await result.fetchone()

    async def create(
        self, connection: AsyncConnection, payload: UserCreate, password_hash: str
    ) -> dict[str, Any]:
        result = await connection.execute(
            """INSERT INTO admin_users (id, name, email, password_hash, role, is_active)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, name, email, role, is_active, created_at, updated_at""",
            (uuid4(), payload.name.strip(), payload.email, password_hash, payload.role.value, payload.is_active),
        )
        return await result.fetchone()

    async def update(
        self,
        connection: AsyncConnection,
        user_id: UUID,
        payload: UserPatch,
        password_hash: str | None,
    ) -> dict[str, Any] | None:
        fields: list[str] = []
        values: list[Any] = []
        for name in ("name", "email", "role", "is_active"):
            value = getattr(payload, name)
            if value is not None:
                fields.append(f"{name} = %s")
                values.append(value.value if isinstance(value, AdminRole) else value)
        if password_hash is not None:
            fields.append("password_hash = %s")
            values.append(password_hash)
        fields.append("updated_at = NOW()")
        values.append(user_id)
        result = await connection.execute(
            f"""UPDATE admin_users SET {', '.join(fields)}
                WHERE id = %s AND deleted_at IS NULL
                RETURNING id, name, email, role, is_active, created_at, updated_at""",
            values,
        )
        return await result.fetchone()

    async def soft_delete(self, connection: AsyncConnection, user_id: UUID) -> bool:
        result = await connection.execute(
            """UPDATE admin_users SET is_active = FALSE, deleted_at = NOW(), updated_at = NOW()
               WHERE id = %s AND deleted_at IS NULL""",
            (user_id,),
        )
        return result.rowcount == 1

    async def active_admin_count(self, connection: AsyncConnection) -> int:
        result = await connection.execute(
            """SELECT COUNT(*) AS count FROM admin_users
               WHERE role = 'ADMIN' AND is_active AND deleted_at IS NULL"""
        )
        row = await result.fetchone()
        return int(row["count"])


class SessionRepository:
    async def create(
        self, connection: AsyncConnection, admin_id: UUID, token_hash: str, expires_at: datetime
    ) -> None:
        await connection.execute(
            "INSERT INTO admin_sessions (token_hash, admin_id, expires_at) VALUES (%s, %s, %s)",
            (token_hash, admin_id, expires_at),
        )

    async def resolve(self, connection: AsyncConnection, token_hash: str) -> dict[str, Any] | None:
        result = await connection.execute(
            """SELECT u.id, u.name, u.email, u.role, u.is_active, u.created_at, u.updated_at
               FROM admin_sessions s JOIN admin_users u ON u.id = s.admin_id
               WHERE s.token_hash = %s AND s.expires_at > NOW()
                 AND u.is_active AND u.deleted_at IS NULL""",
            (token_hash,),
        )
        return await result.fetchone()

    async def delete(self, connection: AsyncConnection, token_hash: str) -> None:
        await connection.execute("DELETE FROM admin_sessions WHERE token_hash = %s", (token_hash,))


class AuditRepository:
    async def record(
        self,
        connection: AsyncConnection,
        action: str,
        result: str,
        request_id: str,
        actor: dict[str, Any] | None = None,
        actor_email: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        await connection.execute(
            """INSERT INTO admin_audit_events
               (actor_admin_id, actor_email, action, target_type, target_id, result, detail, request_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)""",
            (
                actor.get("id") if actor else None,
                actor.get("email") if actor else actor_email,
                action,
                target_type,
                target_id,
                result,
                json.dumps(detail or {}, ensure_ascii=False),
                request_id,
            ),
        )

    async def page(
        self, connection: AsyncConnection, page: int, search: str, result_filter: str
    ) -> tuple[int, list[dict[str, Any]]]:
        conditions = ["TRUE"]
        values: list[Any] = []
        if search:
            conditions.append("(actor_email ILIKE %s OR action ILIKE %s OR target_id ILIKE %s)")
            term = f"%{search}%"
            values.extend((term, term, term))
        if result_filter:
            conditions.append("result = %s")
            values.append(result_filter)
        where = " AND ".join(conditions)
        count_result = await connection.execute(
            f"SELECT COUNT(*) AS count FROM admin_audit_events WHERE {where}", values
        )
        total = int((await count_result.fetchone())["count"])
        query_values = [*values, 20, (page - 1) * 20]
        rows = await connection.execute(
            f"""SELECT id, occurred_at, actor_email, action, target_type, target_id,
                       result, detail, request_id
                FROM admin_audit_events WHERE {where}
                ORDER BY occurred_at DESC, id DESC LIMIT %s OFFSET %s""",
            query_values,
        )
        return total, list(await rows.fetchall())
