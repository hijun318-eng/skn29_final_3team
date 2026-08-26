"""관리 계정·세션 폐기·append-only 감사 이벤트를 하나의 DB transaction에서 처리한다.

권위 입력은 ``security.accounts``이며 비밀번호 verifier는 API 응답과 감사 payload에 넣지
않는다. 호출자가 소유한 ``AsyncSession``만 사용해 commit·rollback 경계를 중복 소유하지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_password_verifier
from app.contracts import RequestContext, Role


class AdminAccountNotFound(LookupError):
    """관리 대상 계정이 없거나 이미 삭제됐음을 공개 식별자 없이 알린다."""


class AdminAccountConflict(ValueError):
    """username 중복 또는 마지막 관리자 보호 규칙과 요청이 충돌했음을 알린다."""


class LastActiveAdminConflict(AdminAccountConflict):
    """활성 admin이 0명이 되는 Role·활성·삭제 변경을 구분해 알린다."""


class AdminAccountRepository:
    """관리 API의 계정 CRUD와 감사 조회를 현재 요청 transaction에 결합한다."""

    def __init__(self, session: AsyncSession) -> None:
        """commit하지 않는 요청 범위 DB 세션을 저장한다."""

        self._session = session

    async def list_accounts(
        self, *, page: int, page_size: int, search: str
    ) -> tuple[tuple[dict[str, Any], ...], int]:
        """삭제되지 않은 계정을 login ID 순서로 검색하고 정확한 전체 건수를 반환한다."""

        normalized_search = search.strip().lower()
        predicate = "(:search = '' OR strpos(username, :search) > 0)"
        parameters = {
            "search": normalized_search,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        total_result = await self._session.execute(
            text(
                f"""
                SELECT count(*)
                FROM security.accounts
                WHERE deleted_at IS NULL AND {predicate}
                """
            ),
            parameters,
        )
        rows = await self._session.execute(
            text(
                f"""
                SELECT subject, username, role, active,
                       created_at, updated_at, deactivated_at, deleted_at
                FROM security.accounts
                WHERE deleted_at IS NULL AND {predicate}
                ORDER BY username, subject
                LIMIT :limit OFFSET :offset
                """
            ),
            parameters,
        )
        return tuple(dict(row) for row in rows.mappings()), int(total_result.scalar_one())

    async def create_account(
        self,
        *,
        username: str,
        password: str,
        role: Role,
        actor: RequestContext,
    ) -> dict[str, Any]:
        """새 UUID subject와 PBKDF2 verifier를 저장하고 같은 transaction에 감사를 추가한다."""

        salt, digest, iterations = await create_password_verifier(password)
        subject = uuid4()
        try:
            async with self._session.begin_nested():
                result = await self._session.execute(
                    text(
                        """
                        INSERT INTO security.accounts (
                            subject, username, password_salt, password_hash,
                            password_iterations, role, active
                        ) VALUES (
                            :subject, :username, :password_salt, :password_hash,
                            :password_iterations, :role, true
                        )
                        RETURNING subject, username, role, active,
                                  created_at, updated_at, deactivated_at, deleted_at
                        """
                    ),
                    {
                        "subject": subject,
                        "username": username,
                        "password_salt": salt,
                        "password_hash": digest,
                        "password_iterations": iterations,
                        "role": role.value,
                    },
                )
                account = dict(result.mappings().one())
        except IntegrityError as exc:
            raise AdminAccountConflict("이미 사용 중인 아이디입니다.") from exc
        await self._append_audit(
            actor,
            "AUTH_ACCOUNT_CREATED",
            subject,
            {"result": "SUCCESS", "username": username, "role": role.value},
        )
        return account

    async def update_account(
        self,
        subject: UUID,
        *,
        changes: Mapping[str, Any],
        actor: RequestContext,
    ) -> dict[str, Any]:
        """계정 row를 잠그고 Role·활성 변경 시 session을 폐기한 뒤 감사를 기록한다."""

        await self._serialize_account_mutation()
        current = await self._locked_account(subject)
        username = changes.get("username")
        role = changes.get("role")
        active = changes.get("active")
        next_role = role.value if isinstance(role, Role) else str(current["role"])
        next_active = bool(active) if active is not None else bool(current["active"])
        if (
            str(current["role"]) == Role.ADMIN.value
            and bool(current["active"])
            and (next_role != Role.ADMIN.value or not next_active)
        ):
            await self._protect_last_admin(subject)

        changed_fields: list[str] = []
        if username is not None and username != current["username"]:
            changed_fields.append("username")
        if role is not None and role.value != current["role"]:
            changed_fields.append("role")
        if active is not None and bool(active) != bool(current["active"]):
            changed_fields.append("active")
        if not changed_fields:
            return dict(current)

        try:
            async with self._session.begin_nested():
                result = await self._session.execute(
                    text(
                        """
                        UPDATE security.accounts
                        SET username = COALESCE(:username, username),
                            role = COALESCE(:role, role),
                            active = COALESCE(:active, active),
                            deactivated_at = CASE
                                WHEN :active IS NULL THEN deactivated_at
                                WHEN :active THEN NULL
                                ELSE COALESCE(deactivated_at, now())
                            END,
                            updated_at = now()
                        WHERE subject = :subject AND deleted_at IS NULL
                        RETURNING subject, username, role, active,
                                  created_at, updated_at, deactivated_at, deleted_at
                        """
                    ),
                    {
                        "subject": subject,
                        "username": username,
                        "role": role.value if isinstance(role, Role) else None,
                        "active": active,
                    },
                )
                account = dict(result.mappings().one())
        except IntegrityError as exc:
            raise AdminAccountConflict("이미 사용 중인 아이디입니다.") from exc
        if "role" in changed_fields or "active" in changed_fields:
            await self._revoke_subject_sessions(subject)
        await self._append_audit(
            actor,
            "AUTH_ACCOUNT_UPDATED",
            subject,
            {
                "result": "SUCCESS",
                "changed_fields": sorted(changed_fields),
                "role": account["role"],
                "active": account["active"],
            },
        )
        return account

    async def reset_password(
        self, subject: UUID, *, password: str, actor: RequestContext
    ) -> None:
        """새 verifier를 저장하고 대상의 모든 활성 session을 즉시 폐기하며 감사를 남긴다."""

        await self._locked_account(subject)
        salt, digest, iterations = await create_password_verifier(password)
        await self._session.execute(
            text(
                """
                UPDATE security.accounts
                SET password_salt = :password_salt,
                    password_hash = :password_hash,
                    password_iterations = :password_iterations,
                    updated_at = now()
                WHERE subject = :subject AND deleted_at IS NULL
                """
            ),
            {
                "subject": subject,
                "password_salt": salt,
                "password_hash": digest,
                "password_iterations": iterations,
            },
        )
        await self._revoke_subject_sessions(subject)
        await self._append_audit(
            actor,
            "AUTH_ACCOUNT_PASSWORD_RESET",
            subject,
            {"result": "SUCCESS", "changed_fields": ["password"]},
        )

    async def delete_account(self, subject: UUID, *, actor: RequestContext) -> None:
        """마지막 활성 관리자를 보호하면서 계정을 soft-delete하고 session을 폐기한다."""

        await self._serialize_account_mutation()
        current = await self._locked_account(subject)
        if current["role"] == Role.ADMIN.value and bool(current["active"]):
            await self._protect_last_admin(subject)
        await self._session.execute(
            text(
                """
                UPDATE security.accounts
                SET active = false,
                    deactivated_at = COALESCE(deactivated_at, now()),
                    deleted_at = now(),
                    updated_at = now()
                WHERE subject = :subject AND deleted_at IS NULL
                """
            ),
            {"subject": subject},
        )
        await self._revoke_subject_sessions(subject)
        await self._append_audit(
            actor,
            "AUTH_ACCOUNT_DELETED",
            subject,
            {"result": "SUCCESS", "soft_delete": True},
        )

    async def list_audit_events(
        self,
        *,
        page: int,
        page_size: int,
        search: str,
        result_filter: str,
    ) -> tuple[tuple[dict[str, Any], ...], int]:
        """append-only 감사 기록을 action·대상·actor와 결과로 검색해 최신순 반환한다."""

        normalized_search = search.strip().lower()
        normalized_result = result_filter.strip().upper()
        event_result = (
            "upper(COALESCE(details_json_redacted->>'result', "
            "details_json_redacted->>'status', 'UNKNOWN'))"
        )
        predicate = f"""
            (:search = '' OR strpos(lower(action_code), :search) > 0
             OR strpos(lower(object_type), :search) > 0
             OR strpos(lower(object_id), :search) > 0
             OR strpos(lower(COALESCE(actor_user_id::text, '')), :search) > 0)
            AND (:result = '' OR {event_result} = :result)
        """
        parameters = {
            "search": normalized_search,
            "result": normalized_result,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        total_result = await self._session.execute(
            text(f"SELECT count(*) FROM governance.audit_events WHERE {predicate}"),
            parameters,
        )
        rows = await self._session.execute(
            text(
                f"""
                SELECT audit_event_id AS event_id,
                       created_at AS occurred_at,
                       actor_user_id AS actor_subject,
                       action_code,
                       object_type AS target_type,
                       object_id AS target_id,
                       {event_result} AS result,
                       details_json_redacted AS details
                FROM governance.audit_events
                WHERE {predicate}
                ORDER BY created_at DESC, audit_event_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            parameters,
        )
        return tuple(dict(row) for row in rows.mappings()), int(total_result.scalar_one())

    async def record_connection_check(
        self,
        *,
        actor: RequestContext,
        connections: tuple[Mapping[str, object], ...],
    ) -> None:
        """고정 dependency 점검 결과만 URL·credential 없이 append-only 감사에 기록한다."""

        statuses = {
            str(item["id"]): str(item["status"])
            for item in connections
            if item.get("id") is not None and item.get("status") is not None
        }
        await self._session.execute(
            text(
                """
                INSERT INTO governance.audit_events (
                    actor_user_id, actor_role, action_code,
                    object_type, object_id, details_json_redacted, trace_id
                ) VALUES (
                    :actor_user_id, :actor_role, 'CONNECTION_CHECK',
                    'CONNECTION_SET', 'admin-connections',
                    CAST(:details AS jsonb), :trace_id
                )
                """
            ),
            {
                "actor_user_id": actor.user_id,
                "actor_role": actor.role.value,
                "details": json.dumps(
                    {"result": "SUCCESS", "statuses": statuses},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "trace_id": actor.trace_id,
            },
        )

    async def _serialize_account_mutation(self) -> None:
        """계정 변경이 서로 다른 대상 row를 먼저 잠가 deadlock을 만들지 않게 직렬화한다.

        transaction-scoped advisory lock을 대상 ``FOR UPDATE``보다 먼저 얻어 마지막 활성
        admin 집합의 잠금 순서를 하나로 고정하며 commit·rollback 때 자동 해제한다.
        """

        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(1208571443, 260826)")
        )

    async def _locked_account(self, subject: UUID) -> dict[str, Any]:
        result = await self._session.execute(
            text(
                """
                SELECT subject, username, role, active,
                       created_at, updated_at, deactivated_at, deleted_at
                FROM security.accounts
                WHERE subject = :subject AND deleted_at IS NULL
                FOR UPDATE
                """
            ),
            {"subject": subject},
        )
        account = result.mappings().one_or_none()
        if account is None:
            raise AdminAccountNotFound("계정을 찾을 수 없습니다.")
        return dict(account)

    async def _protect_last_admin(self, subject: UUID) -> None:
        result = await self._session.execute(
            text(
                """
                SELECT subject
                FROM security.accounts
                WHERE role = 'admin' AND active AND deleted_at IS NULL
                ORDER BY subject
                FOR UPDATE
                """
            )
        )
        active_admins = {UUID(str(item)) for item in result.scalars()}
        if subject in active_admins and len(active_admins) == 1:
            raise LastActiveAdminConflict(
                "마지막 활성 관리자는 변경하거나 삭제할 수 없습니다."
            )

    async def _revoke_subject_sessions(self, subject: UUID) -> None:
        await self._session.execute(
            text(
                """
                UPDATE security.auth_sessions
                SET revoked_at = now()
                WHERE subject = :subject AND revoked_at IS NULL
                """
            ),
            {"subject": subject},
        )

    async def _append_audit(
        self,
        actor: RequestContext,
        action_code: str,
        target_subject: UUID,
        details: Mapping[str, Any],
    ) -> None:
        await self._session.execute(
            text(
                """
                INSERT INTO governance.audit_events (
                    actor_user_id, actor_role, action_code,
                    object_type, object_id, details_json_redacted, trace_id
                ) VALUES (
                    :actor_user_id, :actor_role, :action_code,
                    'AUTH_ACCOUNT', :object_id,
                    CAST(:details AS jsonb), :trace_id
                )
                """
            ),
            {
                "actor_user_id": actor.user_id,
                "actor_role": actor.role.value,
                "action_code": action_code,
                "object_id": str(target_subject),
                "details": json.dumps(
                    dict(details), ensure_ascii=False, sort_keys=True, default=str
                ),
                "trace_id": actor.trace_id,
            },
        )
