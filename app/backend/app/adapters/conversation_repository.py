"""PostgreSQL App DB에 대한 멀티턴 대화, 턴, 멱등성 명령, ViewSpec 영속화 리포지토리 (SQLAlchemy Async)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class ConversationRepository:
    """chat.conversations, chat.turns, chat.turn_commands, artifact.view_specs 관리 리포지토리."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    @staticmethod
    async def _insert_release_binding(
        session: AsyncSession,
        *,
        object_kind: str,
        object_id: UUID | str,
        product_release_id: str,
        permission_snapshot_id: str,
        semantic_release_id: str,
    ) -> None:
        """Phase 0B의 immutable binding에 domain object receipt를 함께 기록한다."""

        await session.execute(
            text(
                """
                INSERT INTO governance.product_release_bindings (
                    object_kind, object_id, product_release_id,
                    permission_snapshot_id, semantic_release_id,
                    capability_release_vector_json, evidence_refs_json
                ) VALUES (
                    :object_kind, :object_id, :product_release_id,
                    :permission_snapshot_id, :semantic_release_id,
                    '{"conversation.command":"1.0.0"}'::jsonb, '[]'::jsonb
                )
                """
            ),
            {
                "object_kind": object_kind,
                "object_id": str(object_id),
                "product_release_id": product_release_id,
                "permission_snapshot_id": permission_snapshot_id,
                "semantic_release_id": semantic_release_id,
            },
        )

    @classmethod
    async def _insert_view_spec(
        cls,
        session: AsyncSession,
        *,
        view_spec_id: UUID,
        artifact_id: UUID,
        view_type: str,
        spec_json: dict[str, Any],
        product_release_id: str,
        permission_snapshot_id: str,
        semantic_release_id: str,
    ) -> None:
        """Insert an immutable View and its release binding in the caller transaction."""

        if view_type not in {"TABLE", "BAR", "LINE", "PIE", "AREA", "SCATTER", "KPI"}:
            raise ValueError("지원하지 않는 View type입니다.")
        canonical = json.dumps(
            spec_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        )
        await session.execute(
            text(
                """
                INSERT INTO artifact.view_specs (
                    view_spec_id, artifact_id, view_type, spec_json, spec_sha256,
                    product_release_id, permission_snapshot_id, semantic_release_id
                ) VALUES (
                    :view_spec_id, :artifact_id, :view_type, CAST(:spec_json AS jsonb),
                    :spec_sha256, :product_release_id, :permission_snapshot_id,
                    :semantic_release_id
                )
                """
            ),
            {
                "view_spec_id": view_spec_id,
                "artifact_id": artifact_id,
                "view_type": view_type,
                "spec_json": canonical,
                "spec_sha256": sha256(canonical.encode("utf-8")).hexdigest(),
                "product_release_id": product_release_id,
                "permission_snapshot_id": permission_snapshot_id,
                "semantic_release_id": semantic_release_id,
            },
        )
        await cls._insert_release_binding(
            session,
            object_kind="VIEW",
            object_id=view_spec_id,
            product_release_id=product_release_id,
            permission_snapshot_id=permission_snapshot_id,
            semantic_release_id=semantic_release_id,
        )

    async def get_conversation(self, conversation_id: UUID, user_id: UUID) -> dict[str, Any] | None:
        """대화방을 조회하고 소유권을 확인한다."""
        stmt = text("""
        SELECT conversation_id, owner_user_id, title, status, head_turn_id, turn_count,
               active_command_id, lease_expires_at, product_release_id,
               permission_snapshot_id, semantic_release_id, release_pinned_at,
               wall_clock_anchor, data_focus_turn_id, data_focus_artifact_id,
               view_focus_turn_id, view_focus_spec_id,
               created_at, updated_at
        FROM chat.conversations
        WHERE conversation_id = :conv_id AND owner_user_id = :user_id
        """)
        async with self._sessionmaker() as session:
            result = await session.execute(stmt, {"conv_id": conversation_id, "user_id": user_id})
            row = result.mappings().first()
            return dict(row) if row else None

    async def create_conversation(
        self,
        user_id: UUID,
        title: str,
        *,
        product_release_id: str,
        permission_snapshot_id: str,
        semantic_release_id: str,
        wall_clock_anchor: date,
    ) -> dict[str, Any]:
        """새 대화방을 생성한다."""
        conv_id = uuid4()
        stmt = text("""
        INSERT INTO chat.conversations (
            conversation_id, owner_user_id, title, status, product_release_id,
            permission_snapshot_id, semantic_release_id, release_pinned_at,
            wall_clock_anchor
        ) VALUES (
            :conv_id, :user_id, :title, 'ACTIVE', :product_release_id,
            :permission_snapshot_id, :semantic_release_id, :pinned_at,
            :wall_clock_anchor
        )
        RETURNING conversation_id, owner_user_id, title, status, head_turn_id,
                  turn_count, product_release_id, permission_snapshot_id,
                  semantic_release_id, release_pinned_at, wall_clock_anchor,
                  data_focus_turn_id, data_focus_artifact_id,
                  view_focus_turn_id, view_focus_spec_id, created_at
        """)
        async with self._sessionmaker() as session:
            async with session.begin():
                result = await session.execute(
                    stmt,
                    {
                        "conv_id": conv_id,
                        "user_id": user_id,
                        "title": title,
                        "product_release_id": product_release_id,
                        "permission_snapshot_id": permission_snapshot_id,
                        "semantic_release_id": semantic_release_id,
                        "pinned_at": datetime.now(timezone.utc),
                        "wall_clock_anchor": wall_clock_anchor,
                    },
                )
                row = result.mappings().first()
                await self._insert_release_binding(
                    session,
                    object_kind="CONVERSATION",
                    object_id=conv_id,
                    product_release_id=product_release_id,
                    permission_snapshot_id=permission_snapshot_id,
                    semantic_release_id=semantic_release_id,
                )
                return dict(row)

    async def list_turns(self, conversation_id: UUID) -> list[dict[str, Any]]:
        """대화방의 모든 불변 턴 목록을 순서대로 조회한다."""
        stmt = text("""
        SELECT t.turn_id, t.conversation_id, t.turn_index, t.user_message, t.route,
               t.source_turn_ids, t.request_id, t.artifact_id, t.view_spec_id,
               COALESCE(
                   t.report_draft_definition_id,
                   t.report_definition_id
               ) AS report_definition_id,
               t.resolved_slots, t.created_at,
               t.reply_to_turn_id, t.clarifies_turn_id,
               t.terminal_status, t.reason_code,
               t.product_release_id, t.permission_snapshot_id, t.semantic_release_id,
               a.data_snapshot_json, a.chart_spec_json, a.narrative_markdown, a.evidence_json,
               v.view_type, v.spec_json AS view_spec_json, v.spec_sha256,
               command.status AS command_status, command.error_response AS command_error
        FROM chat.turns t
        LEFT JOIN artifact.analysis_artifacts a ON t.artifact_id = a.artifact_id
        LEFT JOIN artifact.view_specs v ON t.view_spec_id = v.view_spec_id
        LEFT JOIN LATERAL (
            SELECT c.status, c.error_response
            FROM chat.turn_commands c
            WHERE c.turn_id = t.turn_id
            ORDER BY c.created_at DESC, c.command_id DESC
            LIMIT 1
        ) command ON TRUE
        WHERE t.conversation_id = :conv_id
        ORDER BY t.turn_index ASC
        """)
        async with self._sessionmaker() as session:
            result = await session.execute(stmt, {"conv_id": conversation_id})
            return [dict(r) for r in result.mappings().all()]

    async def get_command(self, conversation_id: UUID, idempotency_key: str) -> dict[str, Any] | None:
        """멱등성 키로 기존 명령 실행 기록을 조회한다."""
        stmt = text("""
        SELECT command_id, conversation_id, idempotency_key, canonical_input_hash,
               status, turn_id, error_response, expected_head_turn_id,
               effective_subject_id, product_release_id, permission_snapshot_id,
               semantic_release_id, terminal_at, created_at
        FROM chat.turn_commands
        WHERE conversation_id = :conv_id AND idempotency_key = :idemp
        """)
        async with self._sessionmaker() as session:
            result = await session.execute(stmt, {"conv_id": conversation_id, "idemp": idempotency_key})
            row = result.mappings().first()
            return dict(row) if row else None

    async def acquire_lease_and_check_cas(
        self,
        conversation_id: UUID,
        expected_head_turn_id: UUID | None,
        command_id: UUID,
        idempotency_key: str,
        input_hash: str,
        effective_subject_id: UUID,
        product_release_id: str,
        permission_snapshot_id: str,
        semantic_release_id: str,
        lease_seconds: int = 60,
    ) -> tuple[bool, str | None]:
        """CAS(head_turn_id) 검사 및 동시성 Lease 획득을 원자적으로 수행한다."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=lease_seconds)

        async with self._sessionmaker() as session:
            async with session.begin():
                # 1. 대화방 잠금 및 상태 확인
                # turn_commands.conversation_id가 conversations를 참조하므로, INSERT를
                # 먼저 하면 그 FK가 잡는 공유 잠금과 이 SELECT FOR UPDATE의 배타 잠금이
                # 두 동시 트랜잭션 사이에서 서로 반대 순서로 얽혀 deadlock을 만든다.
                # FOR UPDATE를 항상 먼저 획득해 모든 트랜잭션이 같은 잠금 순서를 쓰게 한다.
                lock_conv = text(
                    "SELECT head_turn_id, active_command_id, lease_expires_at, status, "
                    "product_release_id, permission_snapshot_id, semantic_release_id "
                    "FROM chat.conversations WHERE conversation_id = :conv_id FOR UPDATE"
                )
                res = await session.execute(lock_conv, {"conv_id": conversation_id})
                conv = res.mappings().first()
                if not conv:
                    return False, "CONVERSATION_NOT_FOUND"
                if conv["status"] == "ARCHIVED":
                    return False, "CONVERSATION_ARCHIVED"

                if conv["head_turn_id"] != expected_head_turn_id:
                    return False, "CONVERSATION_CONFLICT"

                if conv["product_release_id"] != product_release_id:
                    return False, "PRODUCT_RELEASE_MISMATCH"
                if conv["permission_snapshot_id"] != permission_snapshot_id:
                    return False, "PERMISSION_SNAPSHOT_MISMATCH"
                if conv["semantic_release_id"] != semantic_release_id:
                    return False, "SEMANTIC_RELEASE_MISMATCH"

                existing = (
                    await session.execute(
                        text(
                            "SELECT canonical_input_hash FROM chat.turn_commands "
                            "WHERE conversation_id = :conv_id AND idempotency_key = :idemp"
                        ),
                        {"conv_id": conversation_id, "idemp": idempotency_key},
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return (
                        False,
                        "IDEMPOTENCY_EXISTS"
                        if str(existing).strip() == input_hash
                        else "IDEMPOTENCY_PAYLOAD_MISMATCH",
                    )

                # Lease 검사
                if conv["active_command_id"]:
                    return False, (
                        "CONVERSATION_BUSY"
                        if conv["lease_expires_at"] and conv["lease_expires_at"] > now
                        else "CONVERSATION_STALE_LEASE"
                    )

                # 2. 멱등성 명령 등록 (conversations 잠금을 확보한 뒤에만 실행)
                insert_cmd = text("""
                INSERT INTO chat.turn_commands (
                    command_id, conversation_id, idempotency_key,
                    canonical_input_hash, status, expected_head_turn_id,
                    effective_subject_id, product_release_id,
                    permission_snapshot_id, semantic_release_id
                ) VALUES (
                    :cmd_id, :conv_id, :idemp, :hash, 'RUNNING', :expected_head,
                    :effective_subject_id, :product_release_id,
                    :permission_snapshot_id, :semantic_release_id
                )
                """)
                await session.execute(
                    insert_cmd,
                    {
                        "cmd_id": command_id,
                        "conv_id": conversation_id,
                        "idemp": idempotency_key,
                        "hash": input_hash,
                        "expected_head": expected_head_turn_id,
                        "effective_subject_id": effective_subject_id,
                        "product_release_id": product_release_id,
                        "permission_snapshot_id": permission_snapshot_id,
                        "semantic_release_id": semantic_release_id,
                    },
                )

                # Lease 획득
                update_conv = text("""
                UPDATE chat.conversations
                SET active_command_id = :cmd_id, lease_expires_at = :exp, updated_at = :now
                WHERE conversation_id = :conv_id
                """)
                await session.execute(update_conv, {
                    "cmd_id": command_id,
                    "exp": expires_at,
                    "now": now,
                    "conv_id": conversation_id,
                })
                return True, None

    async def commit_turn(
        self,
        conversation_id: UUID,
        command_id: UUID,
        turn_id: UUID,
        turn_index: int,
        user_message: str,
        route: str,
        source_turn_ids: list[str],
        request_id: UUID | None,
        artifact_id: UUID | None,
        view_spec_id: UUID | None,
        report_definition_id: UUID | None,
        resolved_slots: dict[str, Any],
        product_release_id: str,
        permission_snapshot_id: str,
        semantic_release_id: str,
        terminal_writer: Callable[[AsyncSession], Awaitable[None]] | None = None,
        *,
        terminal_status: str = "SUCCEEDED",
        reason_code: str | None = None,
        clarifies_turn_id: UUID | None = None,
        view_spec: dict[str, Any] | None = None,
    ) -> None:
        """종결 도메인 상태·불변 Turn·focus·head·lease를 한 트랜잭션으로 확정한다."""
        if terminal_status not in {
            "SUCCEEDED", "BLOCKED", "PARTIAL", "FAILED", "CANCELLED"
        }:
            raise ValueError("terminal Turn status가 유효하지 않습니다.")
        if len(source_turn_ids) > 2 or len(source_turn_ids) != len(set(source_turn_ids)):
            raise ValueError("source Turn은 중복 없이 최대 두 개만 허용됩니다.")
        source_uuids = [UUID(str(item)) for item in source_turn_ids]
        if view_spec is not None and (view_spec_id is None or artifact_id is None):
            raise ValueError("ViewSpec은 immutable View와 Artifact identity가 필요합니다.")
        now = datetime.now(timezone.utc)
        async with self._sessionmaker() as session:
            async with session.begin():
                command = (
                    await session.execute(
                        text(
                            "SELECT expected_head_turn_id, status FROM chat.turn_commands "
                            "WHERE command_id = :cmd_id AND conversation_id = :conv_id FOR UPDATE"
                        ),
                        {"cmd_id": command_id, "conv_id": conversation_id},
                    )
                ).mappings().one_or_none()
                if command is None or command["status"] != "RUNNING":
                    raise ValueError("RUNNING conversation command를 찾을 수 없습니다.")
                if source_uuids:
                    eligible = (
                        await session.execute(
                            text(
                                """
                                SELECT turn_id
                                FROM chat.turns
                                WHERE turn_id = ANY(:source_turn_ids)
                                  AND conversation_id = :conversation_id
                                  AND product_release_id = :product_release_id
                                  AND terminal_status = 'SUCCEEDED'
                                  AND route = 'ANALYSIS'
                                  AND artifact_id IS NOT NULL
                                """
                            ),
                            {
                                "source_turn_ids": source_uuids,
                                "conversation_id": conversation_id,
                                "product_release_id": product_release_id,
                            },
                        )
                    ).scalars().all()
                    if set(eligible) != set(source_uuids):
                        raise ValueError("source Turn이 같은 대화의 Safe Analysis가 아닙니다.")
                if terminal_writer is not None:
                    await terminal_writer(session)
                if view_spec is not None:
                    await self._insert_view_spec(
                        session,
                        view_spec_id=view_spec_id,
                        artifact_id=artifact_id,
                        view_type=str(view_spec["view_type"]),
                        spec_json=dict(view_spec["spec_json"]),
                        product_release_id=product_release_id,
                        permission_snapshot_id=permission_snapshot_id,
                        semantic_release_id=semantic_release_id,
                    )
                # 1. 턴 삽입
                insert_turn = text("""
                INSERT INTO chat.turns (
                    turn_id, conversation_id, turn_index, user_message, route,
                    source_turn_ids, request_id, artifact_id, view_spec_id,
                    report_draft_definition_id, resolved_slots, product_release_id,
                    permission_snapshot_id, semantic_release_id, reply_to_turn_id,
                    clarifies_turn_id, terminal_status, reason_code, created_at
                ) VALUES (:turn_id, :conv_id, :idx, :msg, :route,
                          :source_ids, :req_id, :art_id, :v_id,
                          :rep_id, :slots, :product_release_id,
                          :permission_snapshot_id, :semantic_release_id,
                          :reply_to_turn_id, :clarifies_turn_id,
                          :terminal_status, :reason_code, :now)
                """)
                await session.execute(insert_turn, {
                    "turn_id": turn_id,
                    "conv_id": conversation_id,
                    "idx": turn_index,
                    "msg": user_message,
                    "route": route,
                    "source_ids": json.dumps(source_turn_ids),
                    "req_id": request_id,
                    "art_id": artifact_id,
                    "v_id": view_spec_id,
                    "rep_id": report_definition_id,
                    "slots": json.dumps(resolved_slots, default=str),
                    "product_release_id": product_release_id,
                    "permission_snapshot_id": permission_snapshot_id,
                    "semantic_release_id": semantic_release_id,
                    "reply_to_turn_id": command["expected_head_turn_id"],
                    "clarifies_turn_id": clarifies_turn_id,
                    "terminal_status": terminal_status,
                    "reason_code": reason_code,
                    "now": now,
                })
                await self._insert_release_binding(
                    session,
                    object_kind="TURN",
                    object_id=turn_id,
                    product_release_id=product_release_id,
                    permission_snapshot_id=permission_snapshot_id,
                    semantic_release_id=semantic_release_id,
                )

                # 2. 대화방 head_turn_id 전진 및 Lease 해제
                update_conv = text("""
                UPDATE chat.conversations
                SET head_turn_id = :turn_id, turn_count = turn_count + 1,
                    data_focus_turn_id = CASE
                        WHEN :terminal_status = 'SUCCEEDED'
                         AND :route = 'ANALYSIS'
                         AND CAST(:artifact_id AS uuid) IS NOT NULL
                        THEN :turn_id ELSE data_focus_turn_id END,
                    data_focus_artifact_id = CASE
                        WHEN :terminal_status = 'SUCCEEDED'
                         AND :route = 'ANALYSIS'
                         AND CAST(:artifact_id AS uuid) IS NOT NULL
                        THEN :artifact_id ELSE data_focus_artifact_id END,
                    view_focus_turn_id = CASE
                        WHEN :terminal_status = 'SUCCEEDED'
                         AND CAST(:view_spec_id AS uuid) IS NOT NULL
                        THEN :turn_id ELSE view_focus_turn_id END,
                    view_focus_spec_id = CASE
                        WHEN :terminal_status = 'SUCCEEDED'
                         AND CAST(:view_spec_id AS uuid) IS NOT NULL
                        THEN :view_spec_id ELSE view_focus_spec_id END,
                    active_command_id = NULL, lease_expires_at = NULL, updated_at = :now
                WHERE conversation_id = :conv_id
                  AND active_command_id = :cmd_id
                  AND head_turn_id IS NOT DISTINCT FROM :expected_head
                RETURNING conversation_id
                """)
                update_result = await session.execute(update_conv, {
                    "turn_id": turn_id,
                    "now": now,
                    "conv_id": conversation_id,
                    "cmd_id": command_id,
                    "expected_head": command["expected_head_turn_id"],
                    "terminal_status": terminal_status,
                    "route": route,
                    "artifact_id": artifact_id,
                    "view_spec_id": view_spec_id,
                })
                if update_result.scalar_one_or_none() is None:
                    raise ValueError("conversation terminal CAS가 일치하지 않습니다.")

                # 3. command 상태 완료로 갱신
                update_cmd = text("""
                UPDATE chat.turn_commands
                SET status = 'COMPLETED', turn_id = :turn_id, terminal_at = :now
                WHERE command_id = :cmd_id AND status = 'RUNNING'
                RETURNING command_id
                """)
                command_result = await session.execute(update_cmd, {
                    "turn_id": turn_id,
                    "cmd_id": command_id,
                    "now": now,
                })
                if command_result.scalar_one_or_none() is None:
                    raise ValueError("conversation command terminal 전이가 실패했습니다.")

    async def release_lease_on_failure(self, conversation_id: UUID, command_id: UUID, error_response: dict[str, Any]) -> None:
        """명령 실행 실패 시 Lease를 즉시 해제하고 에러 상태를 기록한다."""
        now = datetime.now(timezone.utc)
        async with self._sessionmaker() as session:
            async with session.begin():
                update_conv = text("""
                UPDATE chat.conversations
                SET active_command_id = NULL, lease_expires_at = NULL, updated_at = :now
                WHERE conversation_id = :conv_id AND active_command_id = :cmd_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM chat.analysis_requests r
                      JOIN query.query_executions q ON q.request_id = r.request_id
                      WHERE r.command_id = :cmd_id AND q.execution_status = 'RUNNING'
                  )
                """)
                await session.execute(
                    update_conv,
                    {"now": now, "conv_id": conversation_id, "cmd_id": command_id},
                )

                update_cmd = text("""
                UPDATE chat.turn_commands
                SET status = 'FAILED', error_response = :err, terminal_at = :now
                WHERE command_id = :cmd_id AND status = 'RUNNING'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM chat.analysis_requests r
                      JOIN query.query_executions q ON q.request_id = r.request_id
                      WHERE r.command_id = :cmd_id AND q.execution_status = 'RUNNING'
                  )
                """)
                await session.execute(update_cmd, {
                    "err": json.dumps(error_response, default=str),
                    "cmd_id": command_id,
                    "now": now,
                })

    async def commit_failed_turn(
        self,
        conversation_id: UUID,
        command_id: UUID,
        turn_id: UUID,
        turn_index: int,
        user_message: str,
        error_response: dict[str, Any],
        *,
        request_id: UUID | None = None,
        terminal_writer: Callable[[AsyncSession], Awaitable[None]] | None = None,
    ) -> None:
        """실패 Run·Turn·head·command·lease를 한 transaction에서 함께 종결한다."""

        now = datetime.now(timezone.utc)
        async with self._sessionmaker() as session:
            async with session.begin():
                command = (
                    await session.execute(
                        text(
                            "SELECT product_release_id, permission_snapshot_id, semantic_release_id, "
                            "expected_head_turn_id FROM chat.turn_commands "
                            "WHERE command_id = :cmd_id AND conversation_id = :conv_id "
                            "AND status = 'RUNNING' FOR UPDATE"
                        ),
                        {"cmd_id": command_id, "conv_id": conversation_id},
                    )
                ).mappings().one_or_none()
                if command is None:
                    raise ValueError("RUNNING conversation command를 찾을 수 없습니다.")
                if terminal_writer is not None:
                    await terminal_writer(session)
                if request_id is not None:
                    running_query = (
                        await session.execute(
                            text(
                                "SELECT EXISTS ("
                                "SELECT 1 FROM query.query_executions "
                                "WHERE request_id = :request_id "
                                "AND execution_status = 'RUNNING')"
                            ),
                            {"request_id": request_id},
                        )
                    ).scalar_one()
                    if running_query:
                        raise RuntimeError(
                            "RUNNING query의 external terminal evidence 없이는 command를 닫을 수 없습니다."
                        )
                # route가 'ANALYSIS' 고정인 이유: 이 메서드는 분석 제출 preflight에서 해석이
                # 실패했을 때만 호출되므로 turn이 속한 경로는 이미 분석으로 확정돼 있고,
                # 미결정인 값은 route가 아니라 resolved_slots다. chat.turns.route는 NOT NULL
                # CHECK ('ANALYSIS','PRESENTATION','REPORT_ACTION')이라 NULL·UNKNOWN 표기를
                # 쓸 수 없으므로, 실패 사유는 route가 아닌 command 응답에 typed로 남긴다.
                await session.execute(
                    text("""
                    INSERT INTO chat.turns (
                        turn_id, conversation_id, turn_index, user_message, route,
                        source_turn_ids, request_id, resolved_slots, product_release_id,
                        permission_snapshot_id, semantic_release_id, reply_to_turn_id,
                        terminal_status, reason_code, created_at
                    ) VALUES (
                        :turn_id, :conv_id, :idx, :msg, 'ANALYSIS', '[]', :request_id, '{}',
                        :product_release_id, :permission_snapshot_id,
                        :semantic_release_id, :reply_to_turn_id,
                        'FAILED', :reason_code, :now
                    )
                    """),
                    {
                        "turn_id": turn_id,
                        "conv_id": conversation_id,
                        "idx": turn_index,
                        "msg": user_message,
                        "request_id": request_id,
                        "product_release_id": command["product_release_id"],
                        "permission_snapshot_id": command["permission_snapshot_id"],
                        "semantic_release_id": command["semantic_release_id"],
                        "reply_to_turn_id": command["expected_head_turn_id"],
                        "reason_code": str(
                            error_response.get("code")
                            or "CONVERSATION_COMMAND_FAILED"
                        ),
                        "now": now,
                    },
                )
                await self._insert_release_binding(
                    session,
                    object_kind="TURN",
                    object_id=turn_id,
                    product_release_id=command["product_release_id"],
                    permission_snapshot_id=command["permission_snapshot_id"],
                    semantic_release_id=command["semantic_release_id"],
                )
                conversation_result = await session.execute(
                    text("""
                    UPDATE chat.conversations
                    SET head_turn_id = :turn_id, turn_count = turn_count + 1,
                        active_command_id = NULL, lease_expires_at = NULL, updated_at = :now
                    WHERE conversation_id = :conv_id
                      AND active_command_id = :cmd_id
                      AND head_turn_id IS NOT DISTINCT FROM :expected_head
                    """),
                    {
                        "turn_id": turn_id,
                        "now": now,
                        "conv_id": conversation_id,
                        "cmd_id": command_id,
                        "expected_head": command["expected_head_turn_id"],
                    },
                )
                if conversation_result.rowcount != 1:
                    raise ValueError("conversation failure terminal CAS가 일치하지 않습니다.")
                command_result = await session.execute(
                    text("""
                    UPDATE chat.turn_commands
                    SET status = 'FAILED', turn_id = :turn_id,
                        error_response = :err, terminal_at = :now
                    WHERE command_id = :cmd_id AND status = 'RUNNING'
                    """),
                    {
                        "turn_id": turn_id,
                        "err": json.dumps(error_response, default=str),
                        "cmd_id": command_id,
                        "now": now,
                    },
                )
                if command_result.rowcount != 1:
                    raise ValueError("conversation command 실패 전이가 실패했습니다.")

    async def create_view_spec(
        self,
        artifact_id: UUID,
        view_type: str,
        spec_json: dict[str, Any],
        user_id: UUID | None = None,
        *,
        product_release_id: str,
        permission_snapshot_id: str,
        semantic_release_id: str,
    ) -> UUID:
        """불변 ViewSpec 레코드를 생성한다."""
        view_spec_id = uuid4()
        async with self._sessionmaker() as session:
            async with session.begin():
                # 1. 외래키 참조 무결성을 위해 artifact.analysis_artifacts 존재 여부 엄격 확인
                check_art = await session.execute(
                    text("SELECT 1 FROM artifact.analysis_artifacts WHERE artifact_id = :art_id"),
                    {"art_id": artifact_id},
                )
                if not check_art.scalar():
                    raise ValueError(f"Referenced artifact {artifact_id} does not exist.")
                await self._insert_view_spec(
                    session,
                    view_spec_id=view_spec_id,
                    artifact_id=artifact_id,
                    view_type=view_type,
                    spec_json=spec_json,
                    product_release_id=product_release_id,
                    permission_snapshot_id=permission_snapshot_id,
                    semantic_release_id=semantic_release_id,
                )
                return view_spec_id

    async def list_orphan_queries(
        self,
        *,
        stale_before: datetime,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """만료 command에 연결된 RUNNING Trino query를 bounded 목록으로 반환한다."""

        async with self._sessionmaker() as session:
            rows = await session.execute(
                text(
                    """
                    SELECT q.query_execution_id, q.trino_query_id,
                           q.trino_cancel_uri, c.command_id
                    FROM query.query_executions q
                    JOIN chat.analysis_requests r ON r.request_id = q.request_id
                    JOIN chat.turn_commands c ON c.command_id = r.command_id
                    LEFT JOIN chat.conversations conversation
                      ON conversation.conversation_id = c.conversation_id
                    WHERE q.execution_status = 'RUNNING'
                      AND c.status = 'RUNNING'
                      AND c.created_at < :stale_before
                      AND (
                          conversation.active_command_id IS DISTINCT FROM c.command_id
                          OR conversation.lease_expires_at IS NULL
                          OR conversation.lease_expires_at <= :now
                      )
                    ORDER BY c.created_at, q.query_execution_id
                    LIMIT :limit
                    """
                ),
                {
                    "stale_before": stale_before,
                    "now": datetime.now(timezone.utc),
                    "limit": limit,
                },
            )
            return [dict(row) for row in rows.mappings().all()]

    async def reconcile_stale(
        self,
        *,
        stale_before: datetime,
        cancelled_query_execution_ids: tuple[UUID, ...] = (),
        limit: int = 100,
    ) -> dict[str, int]:
        """만료 command/run/query를 멱등 terminalize하고 필요하면 recovery Turn을 만든다."""

        now = datetime.now(timezone.utc)
        counts = {"commands": 0, "runs": 0, "queries": 0, "turns": 0}
        cancelled = set(cancelled_query_execution_ids)
        async with self._sessionmaker() as session:
            async with session.begin():
                commands = (
                    await session.execute(
                        text(
                            """
                            SELECT c.command_id, c.conversation_id, c.turn_id,
                                   c.product_release_id, c.permission_snapshot_id,
                                   c.semantic_release_id,
                                   conversation.active_command_id,
                                   conversation.head_turn_id,
                                   conversation.turn_count,
                                   conversation.lease_expires_at,
                                   r.request_id, r.status AS run_status,
                                   a.artifact_id
                            FROM chat.turn_commands c
                            JOIN chat.conversations conversation
                              ON conversation.conversation_id = c.conversation_id
                            LEFT JOIN chat.analysis_requests r ON r.command_id = c.command_id
                            LEFT JOIN LATERAL (
                                SELECT artifact_id
                                FROM artifact.analysis_artifacts
                                WHERE request_id = r.request_id
                                ORDER BY artifact_id
                                LIMIT 1
                            ) a ON true
                            WHERE c.status = 'RUNNING'
                              AND c.created_at < :stale_before
                              AND (
                                  conversation.active_command_id IS DISTINCT FROM c.command_id
                                  OR conversation.lease_expires_at IS NULL
                                  OR conversation.lease_expires_at <= :now
                              )
                            ORDER BY c.created_at, c.command_id
                            FOR UPDATE OF c, conversation SKIP LOCKED
                            LIMIT :limit
                            """
                        ),
                        {"stale_before": stale_before, "now": now, "limit": limit},
                    )
                ).mappings().all()

                for command in commands:
                    running_queries = (
                        await session.execute(
                            text(
                                "SELECT query_execution_id FROM query.query_executions "
                                "WHERE request_id = :request_id AND execution_status = 'RUNNING'"
                            ),
                            {"request_id": command["request_id"]},
                        )
                    ).scalars().all() if command["request_id"] is not None else []
                    if any(UUID(str(item)) not in cancelled for item in running_queries):
                        continue
                    if running_queries:
                        result = await session.execute(
                            text(
                                """
                                UPDATE query.query_executions
                                SET execution_status = 'CANCELLED',
                                    trino_cancel_uri = NULL,
                                    error_code = 'STALE_COMMAND_RECOVERED',
                                    error_message_redacted = 'Cancelled by conversation reconciler'
                                WHERE request_id = :request_id
                                  AND execution_status = 'RUNNING'
                                """
                            ),
                            {"request_id": command["request_id"]},
                        )
                        counts["queries"] += result.rowcount

                    run_was_terminal = command["run_status"] in {
                        "SUCCEEDED", "PARTIAL", "DENIED", "FAILED", "CANCELLED", "CLARIFYING"
                    }
                    if command["request_id"] is not None and not run_was_terminal:
                        result = await session.execute(
                            text(
                                """
                                UPDATE chat.analysis_requests
                                SET status = 'FAILED', error_type = 'RECOVERY', completed_at = :now
                                WHERE request_id = :request_id
                                  AND status IN ('RECEIVED','ROUTED','RUNNING')
                                """
                            ),
                            {"request_id": command["request_id"], "now": now},
                        )
                        counts["runs"] += result.rowcount

                    recovery_turn_id = command["turn_id"]
                    owns_lease = command["active_command_id"] == command["command_id"]
                    if recovery_turn_id is None and owns_lease:
                        recovery_turn_id = uuid4()
                        await session.execute(
                            text(
                                """
                                INSERT INTO chat.turns (
                                    turn_id, conversation_id, turn_index, user_message,
                                    route, source_turn_ids, request_id, artifact_id,
                                    resolved_slots, product_release_id,
                                    permission_snapshot_id, semantic_release_id,
                                    reply_to_turn_id, terminal_status, reason_code, created_at
                                ) VALUES (
                                    :turn_id, :conversation_id, :turn_index,
                                    '[RECOVERY_REDACTED]', 'ANALYSIS', '[]'::jsonb,
                                    :request_id, :artifact_id,
                                    CAST(:resolved_slots AS jsonb), :product_release_id,
                                    :permission_snapshot_id, :semantic_release_id,
                                    :reply_to_turn_id, 'FAILED',
                                    'STALE_COMMAND_RECOVERED', :now
                                )
                                """
                            ),
                            {
                                "turn_id": recovery_turn_id,
                                "conversation_id": command["conversation_id"],
                                "turn_index": command["turn_count"],
                                "request_id": command["request_id"],
                                "artifact_id": command["artifact_id"],
                                "resolved_slots": json.dumps({"recovered": True}),
                                "product_release_id": command["product_release_id"],
                                "permission_snapshot_id": command["permission_snapshot_id"],
                                "semantic_release_id": command["semantic_release_id"],
                                "reply_to_turn_id": command["head_turn_id"],
                                "now": now,
                            },
                        )
                        await self._insert_release_binding(
                            session,
                            object_kind="TURN",
                            object_id=recovery_turn_id,
                            product_release_id=command["product_release_id"],
                            permission_snapshot_id=command["permission_snapshot_id"],
                            semantic_release_id=command["semantic_release_id"],
                        )
                        await session.execute(
                            text(
                                """
                                UPDATE chat.conversations
                                SET head_turn_id = :turn_id, turn_count = turn_count + 1,
                                    active_command_id = NULL, lease_expires_at = NULL,
                                    updated_at = :now
                                WHERE conversation_id = :conversation_id
                                  AND active_command_id = :command_id
                                """
                            ),
                            {
                                "turn_id": recovery_turn_id,
                                "conversation_id": command["conversation_id"],
                                "command_id": command["command_id"],
                                "now": now,
                            },
                        )
                        counts["turns"] += 1

                    terminal_status = "COMPLETED" if run_was_terminal else "FAILED"
                    error_response = None if run_was_terminal else json.dumps(
                        {
                            "code": "STALE_COMMAND_RECOVERED",
                            "message": "만료된 대화 명령을 안전하게 종료했습니다.",
                            "retryable": True,
                        }
                    )
                    result = await session.execute(
                        text(
                            """
                            UPDATE chat.turn_commands
                            SET status = :status, turn_id = :turn_id,
                                error_response = CAST(:error_response AS jsonb),
                                terminal_at = :now
                            WHERE command_id = :command_id AND status = 'RUNNING'
                            """
                        ),
                        {
                            "status": terminal_status,
                            "turn_id": recovery_turn_id,
                            "error_response": error_response,
                            "now": now,
                            "command_id": command["command_id"],
                        },
                    )
                    counts["commands"] += result.rowcount

                # command lineage가 없는 legacy RECEIVED도 같은 cutoff 뒤 실패로 닫는다.
                result = await session.execute(
                    text(
                        """
                        UPDATE chat.analysis_requests
                        SET status = 'FAILED', error_type = 'RECOVERY', completed_at = :now
                        WHERE status IN ('RECEIVED','ROUTED','RUNNING')
                          AND started_at < :stale_before
                          AND command_id IS NULL
                        """
                    ),
                    {"now": now, "stale_before": stale_before},
                )
                counts["runs"] += result.rowcount
        return counts
