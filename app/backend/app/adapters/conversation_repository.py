"""PostgreSQL App DB에 대한 멀티턴 대화, 턴, 멱등성 명령, ViewSpec 영속화 리포지토리 (SQLAlchemy Async)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class ConversationRepository:
    """chat.conversations, chat.turns, chat.turn_commands, artifact.view_specs 관리 리포지토리."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def get_conversation(self, conversation_id: UUID, user_id: UUID) -> dict[str, Any] | None:
        """대화방을 조회하고 소유권을 확인한다."""
        stmt = text("""
        SELECT conversation_id, owner_user_id, title, status, head_turn_id, turn_count,
               active_command_id, lease_expires_at, created_at, updated_at
        FROM chat.conversations
        WHERE conversation_id = :conv_id AND owner_user_id = :user_id
        """)
        async with self._sessionmaker() as session:
            result = await session.execute(stmt, {"conv_id": conversation_id, "user_id": user_id})
            row = result.mappings().first()
            return dict(row) if row else None

    async def create_conversation(self, user_id: UUID, title: str) -> dict[str, Any]:
        """새 대화방을 생성한다."""
        conv_id = uuid4()
        stmt = text("""
        INSERT INTO chat.conversations (conversation_id, owner_user_id, title, status)
        VALUES (:conv_id, :user_id, :title, 'ACTIVE')
        RETURNING conversation_id, owner_user_id, title, status, head_turn_id, turn_count, created_at
        """)
        async with self._sessionmaker() as session:
            async with session.begin():
                result = await session.execute(stmt, {"conv_id": conv_id, "user_id": user_id, "title": title})
                row = result.mappings().first()
                return dict(row)

    async def list_turns(self, conversation_id: UUID) -> list[dict[str, Any]]:
        """대화방의 모든 불변 턴 목록을 순서대로 조회한다."""
        stmt = text("""
        SELECT t.turn_id, t.conversation_id, t.turn_index, t.user_message, t.route,
               t.source_turn_ids, t.request_id, t.artifact_id, t.view_spec_id,
               t.report_definition_id, t.resolved_slots, t.created_at,
               a.data_snapshot_json, a.chart_spec_json, a.narrative_markdown, a.evidence_json,
               v.view_type, v.spec_json AS view_spec_json
        FROM chat.turns t
        LEFT JOIN artifact.analysis_artifacts a ON t.artifact_id = a.artifact_id
        LEFT JOIN artifact.view_specs v ON t.view_spec_id = v.view_spec_id
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
               status, turn_id, error_response, created_at
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
        lease_seconds: int = 60,
    ) -> tuple[bool, str | None]:
        """CAS(head_turn_id) 검사 및 동시성 Lease 획득을 원자적으로 수행한다."""
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        expires_at = now + timedelta(seconds=lease_seconds)

        async with self._sessionmaker() as session:
            async with session.begin():
                # 1. 대화방 잠금 및 상태 확인
                # turn_commands.conversation_id가 conversations를 참조하므로, INSERT를
                # 먼저 하면 그 FK가 잡는 공유 잠금과 이 SELECT FOR UPDATE의 배타 잠금이
                # 두 동시 트랜잭션 사이에서 서로 반대 순서로 얽혀 deadlock을 만든다.
                # FOR UPDATE를 항상 먼저 획득해 모든 트랜잭션이 같은 잠금 순서를 쓰게 한다.
                lock_conv = text("SELECT head_turn_id, active_command_id, lease_expires_at, status FROM chat.conversations WHERE conversation_id = :conv_id FOR UPDATE")
                res = await session.execute(lock_conv, {"conv_id": conversation_id})
                conv = res.mappings().first()
                if not conv:
                    return False, "CONVERSATION_NOT_FOUND"
                if conv["status"] == "ARCHIVED":
                    return False, "CONVERSATION_ARCHIVED"

                # CAS 검사 (명시적 expected_head_turn_id가 주어졌을 때만 검증)
                if expected_head_turn_id is not None and conv["head_turn_id"] != expected_head_turn_id:
                    return False, "CONVERSATION_CONFLICT"

                # Lease 검사
                if conv["active_command_id"] and conv["lease_expires_at"] and conv["lease_expires_at"] > now:
                    return False, "CONVERSATION_BUSY"

                # 2. 멱등성 명령 등록 (conversations 잠금을 확보한 뒤에만 실행)
                insert_cmd = text("""
                INSERT INTO chat.turn_commands (command_id, conversation_id, idempotency_key, canonical_input_hash, status)
                VALUES (:cmd_id, :conv_id, :idemp, :hash, 'RUNNING')
                """)
                try:
                    await session.execute(insert_cmd, {
                        "cmd_id": command_id,
                        "conv_id": conversation_id,
                        "idemp": idempotency_key,
                        "hash": input_hash,
                    })
                except Exception as e:
                    if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                        return False, "IDEMPOTENCY_CONFLICT"
                    raise

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
    ) -> None:
        """새 턴을 등록하고, conversation의 head_turn_id를 전진시키며 Lease를 해제한다."""
        now = datetime.now(timezone.utc)
        async with self._sessionmaker() as session:
            async with session.begin():
                # 1. 턴 삽입
                insert_turn = text("""
                INSERT INTO chat.turns (
                    turn_id, conversation_id, turn_index, user_message, route,
                    source_turn_ids, request_id, artifact_id, view_spec_id,
                    report_definition_id, resolved_slots, created_at
                ) VALUES (:turn_id, :conv_id, :idx, :msg, :route,
                          :source_ids, :req_id, :art_id, :v_id,
                          :rep_id, :slots, :now)
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
                    "now": now,
                })

                # 2. 대화방 head_turn_id 전진 및 Lease 해제
                update_conv = text("""
                UPDATE chat.conversations
                SET head_turn_id = :turn_id, turn_count = turn_count + 1,
                    active_command_id = NULL, lease_expires_at = NULL, updated_at = :now
                WHERE conversation_id = :conv_id
                """)
                await session.execute(update_conv, {
                    "turn_id": turn_id,
                    "now": now,
                    "conv_id": conversation_id,
                })

                # 3. command 상태 완료로 갱신
                update_cmd = text("""
                UPDATE chat.turn_commands
                SET status = 'COMPLETED', turn_id = :turn_id
                WHERE command_id = :cmd_id
                """)
                await session.execute(update_cmd, {
                    "turn_id": turn_id,
                    "cmd_id": command_id,
                })

    async def release_lease_on_failure(self, conversation_id: UUID, command_id: UUID, error_response: dict[str, Any]) -> None:
        """명령 실행 실패 시 Lease를 즉시 해제하고 에러 상태를 기록한다."""
        now = datetime.now(timezone.utc)
        async with self._sessionmaker() as session:
            async with session.begin():
                update_conv = text("""
                UPDATE chat.conversations
                SET active_command_id = NULL, lease_expires_at = NULL, updated_at = :now
                WHERE conversation_id = :conv_id
                """)
                await session.execute(update_conv, {"now": now, "conv_id": conversation_id})

                update_cmd = text("""
                UPDATE chat.turn_commands
                SET status = 'FAILED', error_response = :err
                WHERE command_id = :cmd_id
                """)
                await session.execute(update_cmd, {
                    "err": json.dumps(error_response, default=str),
                    "cmd_id": command_id,
                })

    async def create_view_spec(
        self,
        artifact_id: UUID,
        view_type: str,
        spec_json: dict[str, Any],
        user_id: UUID | None = None,
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

                # 2. ViewSpec 삽입
                stmt = text("""
                INSERT INTO artifact.view_specs (view_spec_id, artifact_id, view_type, spec_json)
                VALUES (:v_id, :art_id, :v_type, :spec)
                RETURNING view_spec_id
                """)
                await session.execute(stmt, {
                    "v_id": view_spec_id,
                    "art_id": artifact_id,
                    "v_type": view_type,
                    "spec": json.dumps(spec_json),
                })
                return view_spec_id
