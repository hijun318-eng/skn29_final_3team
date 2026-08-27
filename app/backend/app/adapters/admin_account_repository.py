"""관리 계정·세션 폐기·append-only 감사 이벤트를 하나의 DB transaction에서 처리한다.

권위 입력은 ``security.accounts``이며 비밀번호 verifier는 API 응답과 감사 payload에 넣지
않는다. 호출자가 소유한 ``AsyncSession``만 사용해 commit·rollback 경계를 중복 소유하지 않는다.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from datetime import date, datetime
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


class AuditTrailNotFound(LookupError):
    """요청한 서버 grouping 감사 trail이 존재하지 않음을 알린다."""


class InvalidAuditTrailCursor(ValueError):
    """변조되었거나 지원하지 않는 감사 trail cursor를 알린다."""


_AUDIT_OUTCOMES = {
    "SUCCEEDED",
    "FAILED",
    "DENIED",
    "CANCELLED",
    "IN_PROGRESS",
    "CLARIFICATION_REQUIRED",
    "UNKNOWN",
}


def _encode_audit_cursor(started_at: datetime, trail_id: str) -> str:
    """마지막 정렬 키를 URL-safe 불투명 cursor로 직렬화한다."""

    payload = json.dumps(
        {"started_at": started_at.isoformat(), "trail_id": trail_id},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_audit_cursor(cursor: str) -> tuple[datetime | None, str]:
    """목록 keyset cursor를 엄격히 검증하며 빈 값은 첫 페이지로 해석한다."""

    if not cursor:
        return None, ""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if set(payload) != {"started_at", "trail_id"}:
            raise ValueError
        started_at = datetime.fromisoformat(payload["started_at"])
        trail_id = payload["trail_id"]
        if started_at.tzinfo is None or not isinstance(trail_id, str) or not trail_id:
            raise ValueError
        return started_at, trail_id
    except (
        binascii.Error,
        UnicodeDecodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        raise InvalidAuditTrailCursor("감사 추적 cursor가 올바르지 않습니다.") from error


def _audit_outcome(value: object) -> str:
    """DB의 과거 결과 별칭을 현재 공개 감사 결과 값으로 정규화한다."""

    normalized = str(value or "UNKNOWN").upper()
    aliases = {
        "SUCCESS": "SUCCEEDED",
        "FAILURE": "FAILED",
        "ERROR": "FAILED",
        "RUNNING": "IN_PROGRESS",
    }
    outcome = aliases.get(normalized, normalized)
    return outcome if outcome in _AUDIT_OUTCOMES else "UNKNOWN"


def _audit_actor(row: Mapping[str, Any]) -> dict[str, Any]:
    """감사 row에서 credential 없는 수행자 공개 필드만 투영한다."""

    subject = row.get("actor_subject")
    display_name = row.get("actor_display_name")
    return {
        "subject": subject,
        "display_name": str(display_name or subject or "시스템"),
        "role": str(row.get("actor_role") or "system"),
    }


def _audit_details(value: object) -> dict[str, Any]:
    """DB가 보장한 redacted JSON object만 반환하고 손상된 타입은 실패로 닫는다."""

    if not isinstance(value, Mapping):
        raise ValueError("감사 상세 데이터가 JSON object가 아닙니다.")
    return dict(value)


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

    async def list_audit_trails(
        self,
        *,
        cursor: str,
        limit: int,
        query: str,
        outcome: str,
        action: str,
        from_date: date | None,
        to_date: date | None,
    ) -> tuple[tuple[dict[str, Any], ...], str | None]:
        """append-only 이벤트를 correlation 우선순위로 묶어 keyset 기반 최신순 반환한다.

        검색·기간·결과·action 필터는 서버 grouping 이후 적용하며 cursor에는 마지막
        ``started_at``과 ``trail_id``만 포함한다. 저장된 redacted JSON은 이 목록에 싣지 않는다.
        """

        cursor_started_at, cursor_trail_id = _decode_audit_cursor(cursor)
        rows_result = await self._session.execute(
            text(
                f"""
                WITH normalized AS (
                    SELECT e.*,
                           CASE
                               WHEN e.request_id IS NOT NULL THEN 'request_id'
                               WHEN e.report_run_id IS NOT NULL THEN 'report_run_id'
                               WHEN e.query_execution_id IS NOT NULL THEN 'query_execution_id'
                               WHEN e.trace_id IS NOT NULL THEN 'trace_id'
                               ELSE 'audit_event_id'
                           END AS correlation_type,
                           COALESCE(
                               e.request_id::text,
                               e.report_run_id::text,
                               e.query_execution_id::text,
                               e.trace_id,
                               e.audit_event_id::text
                           ) AS correlation_id,
                           CASE upper(COALESCE(
                               e.details_json_redacted->>'result',
                               e.details_json_redacted->>'status',
                               'UNKNOWN'
                           ))
                               WHEN 'SUCCESS' THEN 'SUCCEEDED'
                               WHEN 'SUCCEEDED' THEN 'SUCCEEDED'
                               WHEN 'FAILURE' THEN 'FAILED'
                               WHEN 'ERROR' THEN 'FAILED'
                               WHEN 'FAILED' THEN 'FAILED'
                               WHEN 'DENIED' THEN 'DENIED'
                               WHEN 'CANCELLED' THEN 'CANCELLED'
                               WHEN 'RUNNING' THEN 'IN_PROGRESS'
                               WHEN 'IN_PROGRESS' THEN 'IN_PROGRESS'
                               WHEN 'CLARIFICATION_REQUIRED' THEN 'CLARIFICATION_REQUIRED'
                               ELSE 'UNKNOWN'
                           END AS normalized_outcome,
                           a.username AS actor_display_name
                    FROM governance.audit_events e
                    LEFT JOIN security.accounts a ON a.subject = e.actor_user_id
                ), grouped AS (
                    SELECT correlation_type || ':' || correlation_id AS trail_id,
                           correlation_type,
                           correlation_id,
                           min(created_at) AS started_at,
                           max(created_at) AS ended_at,
                           count(*)::integer AS event_count,
                           (array_agg(action_code ORDER BY created_at DESC, audit_event_id DESC))[1] AS headline,
                           (array_agg(normalized_outcome ORDER BY created_at DESC, audit_event_id DESC))[1] AS outcome,
                           (array_agg(actor_user_id ORDER BY created_at DESC, audit_event_id DESC))[1] AS actor_subject,
                           (array_agg(actor_display_name ORDER BY created_at DESC, audit_event_id DESC))[1] AS actor_display_name,
                           (array_agg(actor_role ORDER BY created_at DESC, audit_event_id DESC))[1] AS actor_role,
                           (array_agg(object_type ORDER BY created_at DESC, audit_event_id DESC))[1] AS object_type,
                           (array_agg(object_id ORDER BY created_at DESC, audit_event_id DESC))[1] AS object_id,
                           array_agg(DISTINCT action_code) AS action_codes,
                           lower(string_agg(
                               concat_ws(' ', action_code, object_type, object_id,
                                   actor_user_id::text, actor_display_name, correlation_id),
                               ' '
                           )) AS search_text
                    FROM normalized
                    GROUP BY correlation_type, correlation_id
                )
                SELECT trail_id, correlation_type, correlation_id,
                       started_at, ended_at, event_count, headline, outcome,
                       actor_subject, actor_display_name, actor_role,
                       object_type, object_id
                FROM grouped
                WHERE (:query = '' OR strpos(search_text, :query) > 0)
                  AND (:outcome = '' OR outcome = :outcome)
                  AND (:action = '' OR :action = ANY(action_codes))
                  AND (CAST(:from_date AS date) IS NULL
                       OR started_at >= CAST(:from_date AS date))
                  AND (CAST(:to_date AS date) IS NULL
                       OR started_at < CAST(:to_date AS date) + INTERVAL '1 day')
                  AND (
                      CAST(:cursor_started_at AS timestamptz) IS NULL
                      OR (started_at, trail_id) < (
                          CAST(:cursor_started_at AS timestamptz), :cursor_trail_id
                      )
                  )
                ORDER BY started_at DESC, trail_id DESC
                LIMIT :fetch_limit
                """
            ),
            {
                "query": query.strip().lower(),
                "outcome": _audit_outcome(outcome) if outcome else "",
                "action": action.strip(),
                "from_date": from_date,
                "to_date": to_date,
                "cursor_started_at": cursor_started_at,
                "cursor_trail_id": cursor_trail_id,
                "fetch_limit": limit + 1,
            },
        )
        rows = [dict(row) for row in rows_result.mappings()]
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(
            {
                "trail_id": row["trail_id"],
                "headline": row["headline"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "outcome": _audit_outcome(row["outcome"]),
                "event_count": row["event_count"],
                "actor": _audit_actor(row),
                "primary_object": {
                    "type": row["object_type"],
                    "id": row["object_id"],
                },
                "correlation": {
                    "type": row["correlation_type"],
                    "id": row["correlation_id"],
                },
            }
            for row in visible
        )
        next_cursor = None
        if has_more and visible:
            next_cursor = _encode_audit_cursor(
                visible[-1]["started_at"], visible[-1]["trail_id"]
            )
        return items, next_cursor

    async def get_audit_trail(self, trail_id: str) -> dict[str, Any]:
        """서버 correlation과 정확히 일치하는 이벤트를 발생 순서와 근거 식별자로 반환한다."""

        result = await self._session.execute(
            text(
                """
                WITH normalized AS (
                    SELECT e.*,
                           CASE
                               WHEN e.request_id IS NOT NULL THEN 'request_id'
                               WHEN e.report_run_id IS NOT NULL THEN 'report_run_id'
                               WHEN e.query_execution_id IS NOT NULL THEN 'query_execution_id'
                               WHEN e.trace_id IS NOT NULL THEN 'trace_id'
                               ELSE 'audit_event_id'
                           END AS correlation_type,
                           COALESCE(
                               e.request_id::text,
                               e.report_run_id::text,
                               e.query_execution_id::text,
                               e.trace_id,
                               e.audit_event_id::text
                           ) AS correlation_id,
                           a.username AS actor_display_name,
                           q.trino_query_id AS query_id
                    FROM governance.audit_events e
                    LEFT JOIN security.accounts a ON a.subject = e.actor_user_id
                    LEFT JOIN query.query_executions q
                        ON q.query_execution_id = e.query_execution_id
                )
                SELECT audit_event_id AS event_id, created_at AS occurred_at,
                       actor_user_id AS actor_subject, actor_display_name, actor_role,
                       action_code, object_type, object_id, details_json_redacted,
                       request_id, trace_id, query_execution_id, query_id,
                       artifact_id, report_run_id, context_release_id,
                       model_version_id, sql_policy_version
                FROM normalized
                WHERE correlation_type || ':' || correlation_id = :trail_id
                ORDER BY created_at, audit_event_id
                """
            ),
            {"trail_id": trail_id},
        )
        rows = [dict(row) for row in result.mappings()]
        if not rows:
            raise AuditTrailNotFound("감사 추적을 찾을 수 없습니다.")

        events: list[dict[str, Any]] = []
        for sequence, row in enumerate(rows):
            details = _audit_details(row["details_json_redacted"])
            events.append(
                {
                    "event_id": row["event_id"],
                    "occurred_at": row["occurred_at"],
                    "sequence": sequence,
                    "action_code": row["action_code"],
                    "action_label": row["action_code"],
                    "summary": str(
                        details.get("summary")
                        or details.get("message")
                        or row["action_code"]
                    ),
                    "outcome": _audit_outcome(
                        details.get("result") or details.get("status")
                    ),
                    "actor": _audit_actor(row),
                    "object": {"type": row["object_type"], "id": row["object_id"]},
                    "evidence": {
                        key: row[key]
                        for key in (
                            "request_id",
                            "trace_id",
                            "query_execution_id",
                            "query_id",
                            "artifact_id",
                            "report_run_id",
                            "context_release_id",
                            "model_version_id",
                            "sql_policy_version",
                        )
                    },
                    "details_redacted": details,
                }
            )

        return {
            "trail_id": trail_id,
            "headline": events[-1]["action_code"],
            "started_at": rows[0]["occurred_at"],
            "ended_at": rows[-1]["occurred_at"],
            "outcome": events[-1]["outcome"],
            "events": tuple(events),
        }

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
