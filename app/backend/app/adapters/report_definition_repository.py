"""보고서 definition version과 block 배치를 draft·approved 상태 규칙으로 영속화한다."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.report_repository_common import _uuid
from src.report.domain import (
    BlockType,
    DefinitionStatus,
    ReportBlock,
    ReportDefinitionLifecycle,
    ReportDefinitionVersion,
    normalize_report_block_content,
    normalize_report_title,
)


def _canonical_atomic_blocks(
    blocks: tuple[ReportBlock, ...],
) -> tuple[ReportBlock, ...]:
    """새 저장 대상만 원자 view로 정규화하고 기존 DB 행은 읽기 시 변경하지 않는다."""

    return tuple(
        replace(
            block,
            content=normalize_report_block_content(block.type, block.content),
        )
        for block in blocks
    )
from src.report.repository import ReportLifecycleConflict, ReportRevisionConflict


def _draft_blocks_match(
    stored_blocks: list[Mapping[str, Any]],
    requested_blocks: tuple[ReportBlock, ...],
) -> bool:
    """DB block rows와 공개 저장 payload를 query ID 비노출 계약까지 반영해 비교한다."""

    if len(stored_blocks) != len(requested_blocks):
        return False
    requested = sorted(
        requested_blocks,
        key=lambda block: (block.y, block.x, str(block.block_id)),
    )
    for stored, block in zip(stored_blocks, requested, strict=True):
        stored_query_id = stored["query_id"]
        if block.query_id is not None and block.query_id != stored_query_id:
            return False
        if (
            str(stored["block_id"]) != str(block.block_id)
            or stored["title"] != block.title
            or (
                str(stored["artifact_id"]) if stored["artifact_id"] else None
            ) != block.artifact_id
            or (
                str(stored["view_spec_id"]) if stored["view_spec_id"] else None
            ) != block.view_spec_id
            or stored["columns"] != block.columns
            or stored["block_type"] != block.type.value
            or stored["x"] != block.x
            or stored["y"] != block.y
            or stored["w"] != block.w
            or stored["h"] != block.h
            or stored["content"] != block.content
            or tuple(stored["evidence_refs"] or ()) != block.evidence_refs
        ):
            return False
    return True


class ReportDefinitionRepositoryMixin:
    """보고서 definition version과 block lineage를 소유자 범위에서 저장하고 조회한다.

    draft block의 artifact는 현재 소유자의 승인 분석과 Trino query ID에 연결돼야 하며,
    승인 전이는 ``draft`` 상태를 조건으로 수행한다. ``_manage_all`` 조합은 definition 접근
    범위만 확장하고 타인 분석 artifact를 draft에 연결하지는 않는다.
    """
    def _scope_params(self) -> dict[str, object]:
        return {"owner_id": self._owner_id, "manage_all": self._manage_all}

    async def _require_owned_artifact(
        self,
        session: AsyncSession,
        artifact_id: UUID,
        query_id: str | None,
    ) -> tuple[UUID, int, str, str | None, str | None, str | None]:
        locked = (await session.execute(
            text(
                """
                SELECT 1
                FROM artifact.analysis_artifacts a
                JOIN query.query_executions q
                  ON q.query_execution_id = a.query_execution_id
                JOIN chat.analysis_requests r ON r.request_id = a.request_id
                WHERE a.artifact_id = :artifact_id
                  AND a.status = 'APPROVED'
                  AND r.status IN ('SUCCEEDED', 'PARTIAL')
                  AND r.user_id = :owner_id
                  AND (CAST(:query_id AS text) IS NULL
                       OR q.trino_query_id = CAST(:query_id AS text))
                FOR KEY SHARE OF r
                """
            ),
            {
                "artifact_id": artifact_id,
                "owner_id": self._owner_id,
                "query_id": query_id,
            },
        )).one_or_none()
        if locked is None:
            raise KeyError("본인의 승인된 Analysis Artifact를 찾을 수 없습니다.")

        # Artifact 원본은 runtime에 SELECT/INSERT만 허용된 불변 row다. 변경 가능한
        # owner request row의 key-share lock을 archive의 exclusive lock과 공유한 뒤
        # lifecycle을 별도 statement로 읽어 이전 snapshot 결속을 막는다.
        owned = (await session.execute(
            text(
                """
                SELECT l.definition_id, l.definition_version, q.trino_query_id,
                       a.product_release_id, a.permission_snapshot_id,
                       a.semantic_release_id
                FROM artifact.analysis_artifacts a
                JOIN query.query_executions q
                  ON q.query_execution_id = a.query_execution_id
                JOIN chat.analysis_requests r ON r.request_id = a.request_id
                JOIN analysis_v1.analysis_run_links l ON l.request_id = r.request_id
                WHERE a.artifact_id = :artifact_id
                  AND a.status = 'APPROVED'
                  AND r.status IN ('SUCCEEDED', 'PARTIAL')
                  AND r.user_id = :owner_id
                  AND NOT EXISTS (
                      SELECT 1 FROM artifact.user_artifact_lifecycle lifecycle
                      WHERE lifecycle.owner_id = r.user_id
                        AND lifecycle.artifact_id = a.artifact_id
                        AND lifecycle.archived_at IS NOT NULL
                  )
                  AND (CAST(:query_id AS text) IS NULL
                       OR q.trino_query_id = CAST(:query_id AS text))
                """
            ),
            {
                "artifact_id": artifact_id,
                "owner_id": self._owner_id,
                "query_id": query_id,
            },
        )).one_or_none()
        if owned is None:
            raise KeyError("본인의 승인된 Analysis Artifact를 찾을 수 없습니다.")

        return (
            UUID(str(owned[0])),
            int(owned[1]),
            str(owned[2]),
            str(owned[3]) if owned[3] else None,
            str(owned[4]) if owned[4] else None,
            str(owned[5]) if owned[5] else None,
        )

    async def _require_artifact_view_spec(
        self,
        session: AsyncSession,
        view_spec_id: UUID,
        artifact_id: UUID | None,
    ) -> None:
        """ViewSpec이 검증된 같은 Artifact에 결속됐는지 확인한다."""

        if artifact_id is None:
            raise KeyError("Report ViewSpec에 연결된 Analysis Artifact를 찾을 수 없습니다.")
        matched = (await session.execute(
            text(
                """
                SELECT 1
                FROM artifact.view_specs
                WHERE view_spec_id = :view_spec_id
                  AND artifact_id = :artifact_id
                """
            ),
            {"view_spec_id": view_spec_id, "artifact_id": artifact_id},
        )).one_or_none()
        if matched is None:
            raise KeyError("Report ViewSpec이 Analysis Artifact와 일치하지 않습니다.")

    async def add_draft(self, draft: ReportDefinitionVersion) -> ReportDefinitionVersion:
        """draft 레코드를 저장소의 비동기 트랜잭션 안에서 영속화한다."""
        if draft.status is not DefinitionStatus.DRAFT:
            raise ValueError("draft만 저장할 수 있습니다.")
        draft = replace(draft, blocks=_canonical_atomic_blocks(draft.blocks))
        definition_id = _uuid(draft.definition_id, "definition_id")
        try:
            async with self._sessionmaker.begin() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_definitions (definition_id, owner_id)
                        VALUES (:definition_id, :owner_id)
                        ON CONFLICT (definition_id) DO NOTHING
                        """
                    ),
                    {"definition_id": definition_id, "owner_id": self._owner_id},
                )
                owner = (await session.execute(
                    text(
                        """
                        SELECT owner_id, archived_at
                        FROM report_v1.report_definitions
                        WHERE definition_id = :definition_id
                        """
                    ),
                    {"definition_id": definition_id},
                )).one()
                if owner.owner_id != self._owner_id and not self._manage_all:
                    raise ValueError("다른 사용자의 Report definition입니다.")
                if owner.archived_at is not None:
                    raise ValueError("보관된 Report definition에는 draft를 추가할 수 없습니다.")
                receipt = await self._resolve_report_receipt(
                    session,
                    (
                        draft.product_release_id,
                        draft.permission_snapshot_id,
                        draft.semantic_release_id,
                    ),
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_definition_versions
                            (definition_id, version, status, title,
                             orientation, currency_display_unit,
                             product_release_id, permission_snapshot_id,
                             semantic_release_id)
                        VALUES (:definition_id, :version, 'draft', :title,
                                :orientation, :currency_display_unit,
                                :product_release_id, :permission_snapshot_id,
                                :semantic_release_id)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "version": draft.version,
                        "title": draft.title,
                        "orientation": draft.orientation,
                        "currency_display_unit": draft.currency_display_unit,
                        "product_release_id": receipt[0] if receipt else None,
                        "permission_snapshot_id": receipt[1] if receipt else None,
                        "semantic_release_id": receipt[2] if receipt else None,
                    },
                )
                for block in draft.blocks:
                    block_artifact_id = (
                        _uuid(block.artifact_id, "artifact_id")
                        if block.artifact_id
                        else None
                    )
                    analysis_lineage = None
                    if block_artifact_id is not None:
                        analysis_lineage = await self._require_owned_artifact(
                            session, block_artifact_id, block.query_id
                        )
                        artifact_receipt = analysis_lineage[3:]
                        if receipt is not None and artifact_receipt != receipt:
                            raise ValueError(
                                "Report block Artifact release receipt does not match"
                            )
                    view_spec_id = (
                        _uuid(block.view_spec_id, "view_spec_id")
                        if block.view_spec_id
                        else None
                    )
                    if view_spec_id is not None:
                        await self._require_artifact_view_spec(
                            session, view_spec_id, block_artifact_id
                        )
                    await session.execute(
                        text(
                            """
                            INSERT INTO report_v1.report_blocks
                                (definition_id, definition_version, block_id, title,
                                 artifact_id, query_id, view_spec_id, columns,
                                 block_type, x, y, w, h, content,
                                 evidence_refs,
                                 analysis_definition_id, analysis_definition_version)
                            VALUES (:definition_id, :version, :block_id, :title,
                                    :artifact_id, :query_id, :view_spec_id,
                                    :columns, :block_type,
                                    :x, :y, :w, :h, :content,
                                    :evidence_refs,
                                    :analysis_definition_id, :analysis_definition_version)
                            """
                        ),
                        {
                            "definition_id": definition_id,
                            "version": draft.version,
                            "block_id": _uuid(block.block_id, "block_id"),
                            "title": block.title,
                            "artifact_id": block_artifact_id,
                            "query_id": analysis_lineage[2] if analysis_lineage else None,
                            "view_spec_id": view_spec_id,
                            "columns": block.columns,
                            "block_type": block.type.value,
                            "x": block.x,
                            "y": block.y,
                            "w": block.w,
                            "h": block.h,
                            "content": block.content,
                            "evidence_refs": list(block.evidence_refs),
                            "analysis_definition_id": analysis_lineage[0] if analysis_lineage else None,
                            "analysis_definition_version": analysis_lineage[1] if analysis_lineage else None,
                        },
                    )
                await self._bind_report_receipt(
                    session,
                    object_id=f"definition:{definition_id}:v{draft.version}",
                    receipt=receipt,
                )
        except IntegrityError as error:
            raise ValueError("같은 Report definition version이 이미 존재합니다.") from error
        stored = replace(draft, draft_revision=1)
        if receipt is None:
            return stored
        return replace(
            stored,
            product_release_id=receipt[0],
            permission_snapshot_id=receipt[1],
            semantic_release_id=receipt[2],
        )

    async def add_draft_in_session(
        self,
        session: AsyncSession,
        draft: ReportDefinitionVersion,
    ) -> ReportDefinitionVersion:
        """호출자가 소유한 종결 트랜잭션 안에서 Report draft를 저장한다."""

        if draft.status is not DefinitionStatus.DRAFT:
            raise ValueError("draft만 저장할 수 있습니다.")
        draft = replace(draft, blocks=_canonical_atomic_blocks(draft.blocks))
        definition_id = _uuid(draft.definition_id, "definition_id")
        await session.execute(
            text(
                """
                INSERT INTO report_v1.report_definitions (definition_id, owner_id)
                VALUES (:definition_id, :owner_id)
                ON CONFLICT (definition_id) DO NOTHING
                """
            ),
            {"definition_id": definition_id, "owner_id": self._owner_id},
        )
        owner = (await session.execute(
            text(
                """
                    SELECT owner_id, archived_at
                    FROM report_v1.report_definitions
                    WHERE definition_id = :definition_id
                """
            ),
            {"definition_id": definition_id},
        )).one()
        if owner.owner_id != self._owner_id and not self._manage_all:
            raise ValueError("다른 사용자의 Report definition입니다.")
        if owner.archived_at is not None:
            raise ValueError("보관된 Report definition에는 draft를 추가할 수 없습니다.")
        receipt = await self._resolve_report_receipt(
            session,
            (
                draft.product_release_id,
                draft.permission_snapshot_id,
                draft.semantic_release_id,
            ),
        )
        await session.execute(
            text(
                """
                INSERT INTO report_v1.report_definition_versions
                    (definition_id, version, status, title,
                     orientation, currency_display_unit,
                     product_release_id, permission_snapshot_id,
                     semantic_release_id)
                VALUES (:definition_id, :version, 'draft', :title,
                        :orientation, :currency_display_unit,
                        :product_release_id, :permission_snapshot_id,
                        :semantic_release_id)
                """
            ),
            {
                "definition_id": definition_id,
                "version": draft.version,
                "title": draft.title,
                "orientation": draft.orientation,
                "currency_display_unit": draft.currency_display_unit,
                "product_release_id": receipt[0] if receipt else None,
                "permission_snapshot_id": receipt[1] if receipt else None,
                "semantic_release_id": receipt[2] if receipt else None,
            },
        )
        for block in draft.blocks:
            block_artifact_id = (
                _uuid(block.artifact_id, "artifact_id")
                if block.artifact_id
                else None
            )
            analysis_lineage = None
            if block_artifact_id is not None:
                analysis_lineage = await self._require_owned_artifact(
                    session, block_artifact_id, block.query_id
                )
                if receipt is not None and analysis_lineage[2:] != receipt:
                    raise ValueError(
                        "Report block Artifact release receipt does not match"
                    )
            view_spec_id = (
                _uuid(block.view_spec_id, "view_spec_id")
                if block.view_spec_id
                else None
            )
            if view_spec_id is not None:
                await self._require_artifact_view_spec(
                    session, view_spec_id, block_artifact_id
                )
            await session.execute(
                text(
                    """
                    INSERT INTO report_v1.report_blocks
                        (definition_id, definition_version, block_id, title,
                         artifact_id, query_id, view_spec_id, columns,
                         block_type, x, y, w, h, content,
                         analysis_definition_id, analysis_definition_version)
                    VALUES (:definition_id, :version, :block_id, :title,
                            :artifact_id, :query_id, :view_spec_id,
                            :columns, :block_type, :x, :y, :w, :h, :content,
                            :analysis_definition_id, :analysis_definition_version)
                    """
                ),
                {
                    "definition_id": definition_id,
                    "version": draft.version,
                    "block_id": _uuid(block.block_id, "block_id"),
                    "title": block.title,
                    "artifact_id": block_artifact_id,
                    "query_id": block.query_id,
                    "view_spec_id": view_spec_id,
                    "columns": block.columns,
                    "block_type": block.type.value,
                    "x": block.x,
                    "y": block.y,
                    "w": block.w,
                    "h": block.h,
                    "content": block.content,
                    "analysis_definition_id": (
                        analysis_lineage[0] if analysis_lineage else None
                    ),
                    "analysis_definition_version": (
                        analysis_lineage[1] if analysis_lineage else None
                    ),
                },
            )
        await self._bind_report_receipt(
            session,
            object_id=f"definition:{definition_id}:v{draft.version}",
            receipt=receipt,
        )
        stored = replace(draft, draft_revision=1)
        if receipt is None:
            return stored
        return replace(
            stored,
            product_release_id=receipt[0],
            permission_snapshot_id=receipt[1],
            semantic_release_id=receipt[2],
        )

    @staticmethod
    def _validate_lifecycle_actor(actor_role: str, trace_id: str | None) -> None:
        """감사 column 경계를 넘는 actor·trace를 lifecycle transaction 전에 거부한다."""

        if not actor_role.strip() or len(actor_role) > 64:
            raise ValueError("Report lifecycle actor role이 유효하지 않습니다.")
        if trace_id is not None and (not trace_id.strip() or len(trace_id) > 128):
            raise ValueError("Report lifecycle trace ID가 유효하지 않습니다.")

    @staticmethod
    def _lifecycle(row: Mapping[str, Any]) -> ReportDefinitionLifecycle:
        return ReportDefinitionLifecycle(
            definition_id=str(row["definition_id"]),
            archived_at=row["archived_at"],
            archived_by=(
                str(row["archived_by"]) if row["archived_by"] is not None else None
            ),
        )

    async def archive_definition(
        self,
        definition_id: str,
        *,
        actor_role: str,
        trace_id: str | None = None,
    ) -> ReportDefinitionLifecycle:
        """소유 보고서를 멱등 보관하고 진행 중 작업이 없을 때 schedule을 함께 끈다."""

        self._validate_lifecycle_actor(actor_role, trace_id)
        definition_uuid = _uuid(definition_id, "definition_id")
        async with self._sessionmaker.begin() as session:
            current = (await session.execute(
                text(
                    """
                    SELECT definition_id, archived_at, archived_by
                    FROM report_v1.report_definitions
                    WHERE definition_id = :definition_id AND owner_id = :owner_id
                    FOR UPDATE
                    """
                ),
                {"definition_id": definition_uuid, "owner_id": self._owner_id},
            )).mappings().one_or_none()
            if current is None:
                raise KeyError("Report definition을 찾을 수 없습니다.")
            if current["archived_at"] is not None:
                return self._lifecycle(current)

            blocked = (await session.execute(
                text(
                    """
                    SELECT
                        EXISTS (
                            SELECT 1 FROM report_v1.report_runs
                            WHERE definition_id = :definition_id
                              AND status IN ('queued', 'running')
                        )
                        OR EXISTS (
                            SELECT 1 FROM report_v1.report_manual_run_commands
                            WHERE definition_id = :definition_id
                              AND status IN ('queued', 'running')
                        )
                        OR EXISTS (
                            SELECT 1 FROM report_v1.report_assistant_requests
                            WHERE (
                                session_definition_id = :definition_id
                                OR definition_id = :definition_id
                            )
                              AND (
                                  status = 'running'
                                  OR phase IN (
                                      'ready', 'waiting_patch_approval',
                                      'waiting_approval', 'running_data_agent',
                                      'waiting_artifact', 'saving_revision'
                                  )
                              )
                        )
                    """
                ),
                {"definition_id": definition_uuid},
            )).scalar_one()
            if blocked:
                raise ReportLifecycleConflict("REPORT_ARCHIVE_IN_PROGRESS")

            await session.execute(
                text(
                    """
                    UPDATE report_v1.report_schedules
                    SET enabled = false, updated_at = now()
                    WHERE definition_id = :definition_id AND enabled
                    """
                ),
                {"definition_id": definition_uuid},
            )
            archived = (await session.execute(
                text(
                    """
                    UPDATE report_v1.report_definitions
                    SET archived_at = now(), archived_by = :owner_id
                    WHERE definition_id = :definition_id
                      AND owner_id = :owner_id AND archived_at IS NULL
                    RETURNING definition_id, archived_at, archived_by
                    """
                ),
                {"definition_id": definition_uuid, "owner_id": self._owner_id},
            )).mappings().one()
            await session.execute(
                text(
                    """
                    INSERT INTO governance.audit_events (
                        actor_user_id, actor_role, action_code,
                        object_type, object_id, details_json_redacted, trace_id
                    ) VALUES (
                        :owner_id, :actor_role, 'REPORT_ARCHIVED',
                        'REPORT_DEFINITION', :object_id, '{}'::jsonb, :trace_id
                    )
                    """
                ),
                {
                    "owner_id": self._owner_id,
                    "actor_role": actor_role,
                    "object_id": str(definition_uuid),
                    "trace_id": trace_id,
                },
            )
            return self._lifecycle(archived)

    async def restore_definition(
        self,
        definition_id: str,
        *,
        actor_role: str,
        trace_id: str | None = None,
    ) -> ReportDefinitionLifecycle:
        """소유 보고서를 멱등 복원하며 보관 시 꺼진 schedule은 다시 켜지 않는다."""

        self._validate_lifecycle_actor(actor_role, trace_id)
        definition_uuid = _uuid(definition_id, "definition_id")
        async with self._sessionmaker.begin() as session:
            current = (await session.execute(
                text(
                    """
                    SELECT definition_id, archived_at, archived_by
                    FROM report_v1.report_definitions
                    WHERE definition_id = :definition_id AND owner_id = :owner_id
                    FOR UPDATE
                    """
                ),
                {"definition_id": definition_uuid, "owner_id": self._owner_id},
            )).mappings().one_or_none()
            if current is None:
                raise KeyError("Report definition을 찾을 수 없습니다.")
            if current["archived_at"] is None:
                return self._lifecycle(current)

            restored = (await session.execute(
                text(
                    """
                    UPDATE report_v1.report_definitions
                    SET archived_at = NULL, archived_by = NULL
                    WHERE definition_id = :definition_id
                      AND owner_id = :owner_id AND archived_at IS NOT NULL
                    RETURNING definition_id, archived_at, archived_by
                    """
                ),
                {"definition_id": definition_uuid, "owner_id": self._owner_id},
            )).mappings().one()
            await session.execute(
                text(
                    """
                    INSERT INTO governance.audit_events (
                        actor_user_id, actor_role, action_code,
                        object_type, object_id, details_json_redacted, trace_id
                    ) VALUES (
                        :owner_id, :actor_role, 'REPORT_RESTORED',
                        'REPORT_DEFINITION', :object_id, '{}'::jsonb, :trace_id
                    )
                    """
                ),
                {
                    "owner_id": self._owner_id,
                    "actor_role": actor_role,
                    "object_id": str(definition_uuid),
                    "trace_id": trace_id,
                },
            )
            return self._lifecycle(restored)

    async def get_version(self, definition_id: str, version: int) -> ReportDefinitionVersion:
        """접근 가능한 definition의 정확한 version과 배치 순 block을 값 객체로 복원한다.

        UUID 형식 오류는 ``ValueError``이며, 누락된 version과 소유 범위 밖 version은 모두
        ``KeyError``로 반환해 객체 존재를 구분하지 않는다.
        """
        definition_uuid = _uuid(definition_id, "definition_id")
        async with self._sessionmaker() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT v.definition_id, v.version, v.status, v.title, v.approved_at,
                           v.orientation, v.currency_display_unit,
                           v.product_release_id, v.permission_snapshot_id,
                           v.semantic_release_id, v.revision,
                           d.archived_at, d.archived_by
                    FROM report_v1.report_definition_versions v
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE v.definition_id = :definition_id AND v.version = :version
                      AND (:manage_all OR d.owner_id = :owner_id)
                    """
                ),
                {
                    **self._scope_params(),
                    "definition_id": definition_uuid,
                    "version": version,
                },
            )).mappings().one_or_none()
            if row is None:
                raise KeyError("Report definition version을 찾을 수 없습니다.")
            blocks = (await session.execute(
                text(
                    """
                    SELECT block_id, title, artifact_id, query_id, view_spec_id, columns,
                           block_type, x, y, w, h, content, evidence_refs
                    FROM report_v1.report_blocks
                    WHERE definition_id = :definition_id
                      AND definition_version = :version
                    ORDER BY y, x, block_id
                    """
                ),
                {"definition_id": definition_uuid, "version": version},
            )).mappings()
            return ReportDefinitionVersion(
                definition_id=str(row["definition_id"]),
                version=row["version"],
                status=DefinitionStatus(row["status"]),
                title=row["title"],
                blocks=tuple(
                    ReportBlock(
                        str(block["block_id"]),
                        block["title"],
                        str(block["artifact_id"]) if block["artifact_id"] else None,
                        block["columns"],
                        block["query_id"],
                        BlockType(block["block_type"]),
                        block["x"],
                        block["y"],
                        block["w"],
                        block["h"],
                        block["content"],
                        view_spec_id=(
                            str(block["view_spec_id"])
                            if block["view_spec_id"]
                            else None
                        ),
                        evidence_refs=tuple(block["evidence_refs"] or ()),
                    )
                    for block in blocks
                ),
                approved_at=row["approved_at"],
                orientation=row["orientation"],
                currency_display_unit=row["currency_display_unit"],
                product_release_id=row["product_release_id"],
                permission_snapshot_id=row["permission_snapshot_id"],
                semantic_release_id=row["semantic_release_id"],
                draft_revision=int(row["revision"]),
                archived_at=row["archived_at"],
                archived_by=(
                    str(row["archived_by"]) if row["archived_by"] else None
                ),
            )

    async def get_draft_revision(self, definition_id: str, version: int) -> int:
        """현재 소유 범위의 draft CAS revision을 반환한다.

        Report 도메인 값 객체에는 저장소 CAS counter가 포함되지 않으므로 재시도·저장 전
        검증은 이 조회를 사용한다. 누락·비소유·draft가 아닌 version은 모두 ``KeyError``로
        감춰 호출자가 최신 draft를 다시 열도록 한다.
        """

        definition_uuid = _uuid(definition_id, "definition_id")
        async with self._sessionmaker() as session:
            revision = (await session.execute(
                text(
                    """
                    SELECT v.revision
                    FROM report_v1.report_definition_versions v
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE v.definition_id = :definition_id AND v.version = :version
                      AND v.status = 'draft'
                      AND d.archived_at IS NULL
                      AND (:manage_all OR d.owner_id = :owner_id)
                    """
                ),
                {
                    **self._scope_params(),
                    "definition_id": definition_uuid,
                    "version": version,
                },
            )).scalar_one_or_none()
        if revision is None:
            raise KeyError("접근 가능한 draft Report version을 찾을 수 없습니다.")
        return int(revision)

    async def list_definitions(
        self,
        *,
        archived: bool = False,
    ) -> tuple[ReportDefinitionVersion, ...]:
        """owner scope에서 active 또는 명시한 archived report version만 복원한다."""
        async with self._sessionmaker() as session:
            keys = (await session.execute(
                text(
                    """
                    SELECT v.definition_id, v.version
                    FROM report_v1.report_definition_versions v
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE (:manage_all OR d.owner_id = :owner_id)
                      AND (
                          (:archived AND d.archived_at IS NOT NULL)
                          OR (NOT :archived AND d.archived_at IS NULL)
                      )
                    ORDER BY v.created_at DESC, v.definition_id, v.version DESC
                    """
                ),
                {**self._scope_params(), "archived": archived},
            )).all()
        return tuple([
            await self.get_version(str(definition_id), version)
            for definition_id, version in keys
        ])

    async def approve(
        self,
        definition_id: str,
        version: int,
        approved_at: datetime,
    ) -> ReportDefinitionVersion:
        """소유자 또는 ``manage_all`` 범위의 draft version을 approved로 비교 갱신한다.

        갱신 행이 없을 때 version 자체가 없거나 비소유면 ``KeyError``, 이미 승인됐거나 다른
        상태면 ``ValueError``로 구분한다. 성공하면 승인 시각을 포함한 전체 definition 값을
        다시 조회해 반환한다.
        """
        definition_uuid = _uuid(definition_id, "definition_id")
        async with self._sessionmaker.begin() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE report_v1.report_definition_versions v
                    SET status = 'approved', approved_at = :approved_at
                    FROM report_v1.report_definitions d
                    WHERE v.definition_id = d.definition_id
                      AND v.definition_id = :definition_id AND v.version = :version
                      AND (:manage_all OR d.owner_id = :owner_id)
                      AND d.archived_at IS NULL
                      AND v.status = 'draft'
                    """
                ),
                {
                    **self._scope_params(),
                    "definition_id": definition_uuid,
                    "version": version,
                    "approved_at": approved_at,
                },
            )
            if result.rowcount != 1:
                existing = (await session.execute(
                    text(
                        """
                        SELECT d.archived_at
                        FROM report_v1.report_definition_versions v
                        JOIN report_v1.report_definitions d USING (definition_id)
                        WHERE v.definition_id = :definition_id AND v.version = :version
                          AND (:manage_all OR d.owner_id = :owner_id)
                        """
                    ),
                    {
                        **self._scope_params(),
                        "definition_id": definition_uuid,
                        "version": version,
                    },
                )).one_or_none()
                if existing is None:
                    raise KeyError("Report definition version을 찾을 수 없습니다.")
                if existing.archived_at is not None:
                    raise ValueError("보관된 Report definition은 승인할 수 없습니다.")
                raise ValueError("draft Report version만 승인할 수 있습니다.")
        return await self.get_version(definition_id, version)

    async def create_next_draft(
        self,
        definition_id: str,
        approved_version: int,
    ) -> ReportDefinitionVersion:
        """접근 가능한 승인 version을 복사해 version을 하나 올린 draft를 저장한다.

        기준 version 누락·비소유는 ``KeyError``, 승인본이 아니거나 다음 version이 이미
        존재하면 ``ValueError``다. block 배치와 표시 설정은 그대로 복제되며 새 version 전체가
        한 transaction에 삽입된다.
        """
        approved = await self.get_version(definition_id, approved_version)
        return await self.add_draft(approved.next_draft())

    async def replace_draft_blocks_in_session(
        self,
        session: AsyncSession,
        definition_id: str,
        version: int,
        blocks: tuple[ReportBlock, ...],
        *,
        title: str | None = None,
        orientation: str | None = None,
        currency_display_unit: str | None = None,
    ) -> None:
        """호출자가 소유한 종결 트랜잭션 안에서 Report draft 배치를 교체한다."""

        title = normalize_report_title(title) if title is not None else None
        blocks = _canonical_atomic_blocks(blocks)
        definition_uuid = _uuid(definition_id, "definition_id")
        version_row = (await session.execute(
            text(
                """
                SELECT v.status, v.product_release_id,
                       v.permission_snapshot_id, v.semantic_release_id
                FROM report_v1.report_definition_versions v
                JOIN report_v1.report_definitions d USING (definition_id)
                WHERE v.definition_id = :definition_id AND v.version = :version
                  AND (:manage_all OR d.owner_id = :owner_id)
                  AND d.archived_at IS NULL
                  FOR UPDATE
                """
            ),
            {
                **self._scope_params(),
                "definition_id": definition_uuid,
                "version": version,
            },
        )).mappings().one_or_none()
        if version_row is None:
            raise KeyError("Report definition version을 찾을 수 없습니다.")
        if version_row["status"] != DefinitionStatus.DRAFT.value:
            raise ValueError("draft Report version만 block layout을 교체할 수 있습니다.")
        receipt_values = (
            version_row["product_release_id"],
            version_row["permission_snapshot_id"],
            version_row["semantic_release_id"],
        )
        if any(receipt_values) and not all(receipt_values):
            raise ValueError("Stored Report release receipt is incomplete")
        receipt = (
            tuple(str(value) for value in receipt_values)
            if all(receipt_values)
            else None
        )
        if receipt is not None:
            receipt = await self._resolve_report_receipt(session, receipt)
        elif await self._resolve_report_receipt(session, (None, None, None)) is not None:
            raise ValueError("Legacy Report draft has no release receipt")
        await session.execute(
            text(
                """
                UPDATE report_v1.report_definition_versions
                SET title = COALESCE(:title, title),
                    orientation = COALESCE(:orientation, orientation),
                    currency_display_unit = COALESCE(
                        :currency_display_unit, currency_display_unit
                    ),
                    revision = revision + 1
                WHERE definition_id = :definition_id AND version = :version
                  AND status = 'draft'
                """
            ),
            {
                "definition_id": definition_uuid,
                "version": version,
                "title": title,
                "orientation": orientation,
                "currency_display_unit": currency_display_unit,
            },
        )
        await session.execute(
            text(
                """
                DELETE FROM report_v1.report_blocks
                WHERE definition_id = :definition_id
                  AND definition_version = :version
                """
            ),
            {"definition_id": definition_uuid, "version": version},
        )
        for block in blocks:
            block_artifact_id = (
                _uuid(block.artifact_id, "artifact_id")
                if block.artifact_id
                else None
            )
            analysis_lineage = None
            if block_artifact_id is not None:
                analysis_lineage = await self._require_owned_artifact(
                    session, block_artifact_id, block.query_id
                )
                if receipt is not None and analysis_lineage[2:] != receipt:
                    raise ValueError(
                        "Report block Artifact release receipt does not match"
                    )
            view_spec_id = (
                _uuid(block.view_spec_id, "view_spec_id")
                if block.view_spec_id
                else None
            )
            if view_spec_id is not None:
                await self._require_artifact_view_spec(
                    session, view_spec_id, block_artifact_id
                )
            await session.execute(
                text(
                    """
                    INSERT INTO report_v1.report_blocks
                        (definition_id, definition_version, block_id, title,
                         artifact_id, query_id, view_spec_id, columns,
                         block_type, x, y, w, h, content,
                         analysis_definition_id, analysis_definition_version)
                    VALUES (:definition_id, :version, :block_id, :title,
                            :artifact_id, :query_id, :view_spec_id,
                            :columns, :block_type, :x, :y, :w, :h, :content,
                            :analysis_definition_id, :analysis_definition_version)
                    """
                ),
                {
                    "definition_id": definition_uuid,
                    "version": version,
                    "block_id": _uuid(block.block_id, "block_id"),
                    "title": block.title,
                    "artifact_id": block_artifact_id,
                    "query_id": block.query_id,
                    "view_spec_id": view_spec_id,
                    "columns": block.columns,
                    "block_type": block.type.value,
                    "x": block.x,
                    "y": block.y,
                    "w": block.w,
                    "h": block.h,
                    "content": block.content,
                    "analysis_definition_id": (
                        analysis_lineage[0] if analysis_lineage else None
                    ),
                    "analysis_definition_version": (
                        analysis_lineage[1] if analysis_lineage else None
                    ),
                },
            )

    async def replace_draft_blocks(
        self,
        definition_id: str,
        version: int,
        blocks: tuple[ReportBlock, ...],
        *,
        title: str | None = None,
        orientation: str | None = None,
        currency_display_unit: str | None = None,
        expected_draft_revision: int | None = None,
    ) -> ReportDefinitionVersion:
        """draft 제목·blocks 변경을 현재 상태와 충돌 여부를 확인한 뒤 원자적으로 반영한다."""
        title = normalize_report_title(title) if title is not None else None
        blocks = _canonical_atomic_blocks(blocks)
        if expected_draft_revision is not None and (
            isinstance(expected_draft_revision, bool)
            or not isinstance(expected_draft_revision, int)
            or expected_draft_revision < 1
        ):
            raise ValueError("expected_draft_revision은 1 이상이어야 합니다.")
        definition_uuid = _uuid(definition_id, "definition_id")
        async with self._sessionmaker.begin() as session:
            version_row = (await session.execute(
                text(
                    """
                    SELECT v.status, v.title, v.orientation,
                           v.currency_display_unit, v.revision,
                           v.product_release_id, v.permission_snapshot_id,
                           v.semantic_release_id
                    FROM report_v1.report_definition_versions v
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE v.definition_id = :definition_id AND v.version = :version
                      AND (:manage_all OR d.owner_id = :owner_id)
                      AND d.archived_at IS NULL
                    FOR UPDATE
                    """
                ),
                {
                    **self._scope_params(),
                    "definition_id": definition_uuid,
                    "version": version,
                },
            )).mappings().one_or_none()
            if version_row is None:
                raise KeyError("Report definition version을 찾을 수 없습니다.")
            if version_row["status"] != DefinitionStatus.DRAFT.value:
                raise ValueError("draft Report version만 block layout을 교체할 수 있습니다.")
            stored_blocks = (await session.execute(
                text(
                    """
                    SELECT block_id, title, artifact_id, query_id, view_spec_id,
                           columns, block_type, x, y, w, h, content, evidence_refs
                    FROM report_v1.report_blocks
                    WHERE definition_id = :definition_id
                      AND definition_version = :version
                    ORDER BY y, x, block_id
                    """
                ),
                {"definition_id": definition_uuid, "version": version},
            )).mappings().all()
            current_revision = int(version_row["revision"])
            payload_unchanged = (
                (title is None or title == version_row["title"])
                and (
                    orientation is None
                    or orientation == version_row["orientation"]
                )
                and (
                    currency_display_unit is None
                    or currency_display_unit == version_row["currency_display_unit"]
                )
                and _draft_blocks_match(stored_blocks, blocks)
            )
            receipt_values = (
                version_row["product_release_id"],
                version_row["permission_snapshot_id"],
                version_row["semantic_release_id"],
            )
            if any(receipt_values) and not all(receipt_values):
                raise ValueError("Stored Report release receipt is incomplete")
            receipt = (
                tuple(str(value) for value in receipt_values)
                if all(receipt_values)
                else None
            )
            if receipt is not None:
                receipt = await self._resolve_report_receipt(session, receipt)
            else:
                current_receipt = await self._resolve_report_receipt(
                    session, (None, None, None)
                )
                if current_receipt is not None:
                    raise ValueError("Legacy Report draft has no release receipt")
            if (
                expected_draft_revision is not None
                and expected_draft_revision != current_revision
                and not payload_unchanged
            ):
                raise ReportRevisionConflict(current_revision)
            if payload_unchanged:
                return ReportDefinitionVersion(
                    definition_id=definition_id,
                    version=version,
                    status=DefinitionStatus.DRAFT,
                    title=version_row["title"],
                    blocks=tuple(
                        ReportBlock(
                            str(block["block_id"]),
                            block["title"],
                            str(block["artifact_id"]) if block["artifact_id"] else None,
                            block["columns"],
                            block["query_id"],
                            BlockType(block["block_type"]),
                            block["x"],
                            block["y"],
                            block["w"],
                            block["h"],
                            block["content"],
                            tuple(block["evidence_refs"] or ()),
                            str(block["view_spec_id"]) if block["view_spec_id"] else None,
                        )
                        for block in stored_blocks
                    ),
                    orientation=version_row["orientation"],
                    currency_display_unit=version_row["currency_display_unit"],
                    product_release_id=version_row["product_release_id"],
                    permission_snapshot_id=version_row["permission_snapshot_id"],
                    semantic_release_id=version_row["semantic_release_id"],
                    draft_revision=current_revision,
                )
            await session.execute(
                text(
                    """
                    UPDATE report_v1.report_definition_versions
                    SET title = COALESCE(:title, title),
                        orientation = COALESCE(:orientation, orientation),
                        currency_display_unit = COALESCE(
                            :currency_display_unit, currency_display_unit
                        ),
                        revision = revision + 1
                    WHERE definition_id = :definition_id AND version = :version
                      AND status = 'draft'
                    """
                ),
                {
                    "definition_id": definition_uuid,
                    "version": version,
                    "title": title,
                    "orientation": orientation,
                    "currency_display_unit": currency_display_unit,
                },
            )
            await session.execute(
                text(
                    """
                    DELETE FROM report_v1.report_blocks
                    WHERE definition_id = :definition_id AND definition_version = :version
                    """
                ),
                {"definition_id": definition_uuid, "version": version},
            )
            for block in blocks:
                block_artifact_id = (
                    _uuid(block.artifact_id, "artifact_id")
                    if block.artifact_id
                    else None
                )
                analysis_lineage = None
                if block_artifact_id is not None:
                    analysis_lineage = await self._require_owned_artifact(
                        session, block_artifact_id, block.query_id
                    )
                    artifact_receipt = analysis_lineage[3:]
                    if receipt is not None and artifact_receipt != receipt:
                        raise ValueError(
                            "Report block Artifact release receipt does not match"
                        )
                view_spec_id = (
                    _uuid(block.view_spec_id, "view_spec_id")
                    if block.view_spec_id
                    else None
                )
                if view_spec_id is not None:
                    await self._require_artifact_view_spec(
                        session, view_spec_id, block_artifact_id
                    )
                await session.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_blocks
                            (definition_id, definition_version, block_id, title,
                             artifact_id, query_id, view_spec_id, columns,
                             block_type, x, y, w, h, content,
                             evidence_refs,
                             analysis_definition_id, analysis_definition_version)
                        VALUES (:definition_id, :version, :block_id, :title,
                                :artifact_id, :query_id, :view_spec_id,
                                :columns, :block_type,
                                :x, :y, :w, :h, :content,
                                :evidence_refs,
                                :analysis_definition_id, :analysis_definition_version)
                        """
                    ),
                    {
                        "definition_id": definition_uuid,
                        "version": version,
                        "block_id": _uuid(block.block_id, "block_id"),
                        "title": block.title,
                        "artifact_id": block_artifact_id,
                        "query_id": analysis_lineage[2] if analysis_lineage else None,
                        "view_spec_id": view_spec_id,
                        "columns": block.columns,
                        "block_type": block.type.value,
                        "x": block.x,
                        "y": block.y,
                        "w": block.w,
                        "h": block.h,
                        "content": block.content,
                        "evidence_refs": list(block.evidence_refs),
                        "analysis_definition_id": analysis_lineage[0] if analysis_lineage else None,
                        "analysis_definition_version": analysis_lineage[1] if analysis_lineage else None,
                    },
                )
        return await self.get_version(definition_id, version)
