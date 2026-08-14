from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import datetime, timedelta
from functools import lru_cache
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from app.adapters.report_document_repository import PostgresReportDocumentRepositoryMixin
from src.report.domain import (
    BlockFailureCode,
    BlockRunStatus,
    BlockType,
    DefinitionStatus,
    ManualRunCommand,
    ReportBlock,
    ReportBlockRun,
    ReportDefinitionVersion,
    ReportRun,
    RunStatus,
)


@lru_cache(maxsize=None)
def _engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def _uuid(value: str, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(f"{field}는 UUID 형식이어야 합니다.") from error


def _advance_schedule(current: datetime, cadence: str) -> datetime:
    local = current.astimezone(ZoneInfo("Asia/Seoul"))
    if cadence == "daily":
        return local + timedelta(days=1)
    if cadence == "weekly":
        return local + timedelta(days=7)
    if cadence == "monthly":
        year = local.year + (1 if local.month == 12 else 0)
        month = 1 if local.month == 12 else local.month + 1
        return local.replace(year=year, month=month, day=min(local.day, monthrange(year, month)[1]))
    raise ValueError("지원하지 않는 Report cadence입니다.")


class PostgresReportRepository(PostgresReportDocumentRepositoryMixin):
    """Owner-scoped Report 저장소이며 관리자는 명시적으로 전체 범위를 관리한다."""

    def __init__(
        self,
        database_url: str,
        owner_id: UUID,
        *,
        manage_all: bool = False,
    ) -> None:
        self._engine = _engine(database_url)
        self._owner_id = owner_id
        self._manage_all = manage_all

    def _scope_params(self) -> dict[str, object]:
        return {"owner_id": self._owner_id, "manage_all": self._manage_all}

    def _require_owned_artifact(
        self,
        connection,
        artifact_id: UUID,
        query_id: str | None,
    ) -> tuple[UUID, int]:
        if not query_id:
            raise KeyError("본인의 승인된 Analysis Artifact를 찾을 수 없습니다.")
        owned = connection.execute(
            text(
                """
                SELECT l.definition_id, l.definition_version
                FROM artifact.analysis_artifacts a
                JOIN query.query_executions q
                  ON q.query_execution_id = a.query_execution_id
                JOIN chat.analysis_requests r ON r.request_id = a.request_id
                JOIN analysis_v1.analysis_run_links l ON l.request_id = r.request_id
                WHERE a.artifact_id = :artifact_id
                  AND a.status = 'APPROVED'
                  AND r.status IN ('SUCCEEDED', 'PARTIAL')
                  AND r.user_id = :owner_id
                  AND q.trino_query_id = :query_id
                """
            ),
            {
                "artifact_id": artifact_id,
                "owner_id": self._owner_id,
                "query_id": query_id,
            },
        ).one_or_none()
        if owned is None:
            raise KeyError("본인의 승인된 Analysis Artifact를 찾을 수 없습니다.")

        return UUID(str(owned[0])), int(owned[1])

    def add_draft(self, draft: ReportDefinitionVersion) -> ReportDefinitionVersion:
        if draft.status is not DefinitionStatus.DRAFT:
            raise ValueError("draft만 저장할 수 있습니다.")
        definition_id = _uuid(draft.definition_id, "definition_id")
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_definitions (definition_id, owner_id)
                        VALUES (:definition_id, :owner_id)
                        ON CONFLICT (definition_id) DO NOTHING
                        """
                    ),
                    {"definition_id": definition_id, "owner_id": self._owner_id},
                )
                owner = connection.execute(
                    text(
                        """
                        SELECT owner_id FROM report_v1.report_definitions
                        WHERE definition_id = :definition_id
                        """
                    ),
                    {"definition_id": definition_id},
                ).scalar_one()
                if owner != self._owner_id and not self._manage_all:
                    raise ValueError("다른 사용자의 Report definition입니다.")
                connection.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_definition_versions
                            (definition_id, version, status, title,
                             orientation, currency_display_unit)
                        VALUES (:definition_id, :version, 'draft', :title,
                                :orientation, :currency_display_unit)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "version": draft.version,
                        "title": draft.title,
                        "orientation": draft.orientation,
                        "currency_display_unit": draft.currency_display_unit,
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
                        analysis_lineage = self._require_owned_artifact(
                            connection, block_artifact_id, block.query_id
                        )
                    connection.execute(
                        text(
                            """
                            INSERT INTO report_v1.report_blocks
                                (definition_id, definition_version, block_id, title,
                                 artifact_id, query_id, columns, block_type, x, y, w, h, content,
                                 analysis_definition_id, analysis_definition_version)
                            VALUES (:definition_id, :version, :block_id, :title,
                                    :artifact_id, :query_id, :columns, :block_type,
                                    :x, :y, :w, :h, :content,
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
                            "columns": block.columns,
                            "block_type": block.type.value,
                            "x": block.x,
                            "y": block.y,
                            "w": block.w,
                            "h": block.h,
                            "content": block.content,
                            "analysis_definition_id": analysis_lineage[0] if analysis_lineage else None,
                            "analysis_definition_version": analysis_lineage[1] if analysis_lineage else None,
                        },
                    )
        except IntegrityError as error:
            raise ValueError("같은 Report definition version이 이미 존재합니다.") from error
        return draft

    def get_version(self, definition_id: str, version: int) -> ReportDefinitionVersion:
        definition_uuid = _uuid(definition_id, "definition_id")
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT v.definition_id, v.version, v.status, v.title, v.approved_at,
                           v.orientation, v.currency_display_unit
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
            ).mappings().one_or_none()
            if row is None:
                raise KeyError("Report definition version을 찾을 수 없습니다.")
            blocks = connection.execute(
                text(
                    """
                    SELECT block_id, title, artifact_id, query_id, columns,
                           block_type, x, y, w, h, content
                    FROM report_v1.report_blocks
                    WHERE definition_id = :definition_id
                      AND definition_version = :version
                    ORDER BY y, x, block_id
                    """
                ),
                {"definition_id": definition_uuid, "version": version},
            ).mappings()
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
                    )
                    for block in blocks
                ),
                approved_at=row["approved_at"],
                orientation=row["orientation"],
                currency_display_unit=row["currency_display_unit"],
            )

    def list_definitions(self) -> tuple[ReportDefinitionVersion, ...]:
        with self._engine.connect() as connection:
            keys = connection.execute(
                text(
                    """
                    SELECT v.definition_id, v.version
                    FROM report_v1.report_definition_versions v
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE (:manage_all OR d.owner_id = :owner_id)
                    ORDER BY v.created_at DESC, v.definition_id, v.version DESC
                    """
                ),
                self._scope_params(),
            ).all()
        return tuple(self.get_version(str(definition_id), version) for definition_id, version in keys)

    def approve(
        self,
        definition_id: str,
        version: int,
        approved_at: datetime,
    ) -> ReportDefinitionVersion:
        definition_uuid = _uuid(definition_id, "definition_id")
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE report_v1.report_definition_versions v
                    SET status = 'approved', approved_at = :approved_at
                    FROM report_v1.report_definitions d
                    WHERE v.definition_id = d.definition_id
                      AND v.definition_id = :definition_id AND v.version = :version
                      AND (:manage_all OR d.owner_id = :owner_id)
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
                existing = connection.execute(
                    text(
                        """
                        SELECT 1 FROM report_v1.report_definition_versions v
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
                ).first()
                if existing is None:
                    raise KeyError("Report definition version을 찾을 수 없습니다.")
                raise ValueError("draft Report version만 승인할 수 있습니다.")
        return self.get_version(definition_id, version)

    def create_next_draft(
        self,
        definition_id: str,
        approved_version: int,
    ) -> ReportDefinitionVersion:
        return self.add_draft(
            self.get_version(definition_id, approved_version).next_draft()
        )

    def replace_draft_blocks(
        self,
        definition_id: str,
        version: int,
        blocks: tuple[ReportBlock, ...],
        *,
        orientation: str | None = None,
        currency_display_unit: str | None = None,
    ) -> ReportDefinitionVersion:
        definition_uuid = _uuid(definition_id, "definition_id")
        with self._engine.begin() as connection:
            status = connection.execute(
                text(
                    """
                    SELECT v.status
                    FROM report_v1.report_definition_versions v
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE v.definition_id = :definition_id AND v.version = :version
                      AND (:manage_all OR d.owner_id = :owner_id)
                    FOR UPDATE
                    """
                ),
                {
                    **self._scope_params(),
                    "definition_id": definition_uuid,
                    "version": version,
                },
            ).scalar_one_or_none()
            if status is None:
                raise KeyError("Report definition version을 찾을 수 없습니다.")
            if status != DefinitionStatus.DRAFT.value:
                raise ValueError("draft Report version만 block layout을 교체할 수 있습니다.")
            connection.execute(
                text(
                    """
                    UPDATE report_v1.report_definition_versions
                    SET orientation = COALESCE(:orientation, orientation),
                        currency_display_unit = COALESCE(
                            :currency_display_unit, currency_display_unit
                        )
                    WHERE definition_id = :definition_id AND version = :version
                      AND status = 'draft'
                    """
                ),
                {
                    "definition_id": definition_uuid,
                    "version": version,
                    "orientation": orientation,
                    "currency_display_unit": currency_display_unit,
                },
            )
            connection.execute(
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
                    analysis_lineage = self._require_owned_artifact(
                        connection, block_artifact_id, block.query_id
                    )
                connection.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_blocks
                            (definition_id, definition_version, block_id, title,
                             artifact_id, query_id, columns, block_type, x, y, w, h, content,
                             analysis_definition_id, analysis_definition_version)
                        VALUES (:definition_id, :version, :block_id, :title,
                                :artifact_id, :query_id, :columns, :block_type,
                                :x, :y, :w, :h, :content,
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
                        "columns": block.columns,
                        "block_type": block.type.value,
                        "x": block.x,
                        "y": block.y,
                        "w": block.w,
                        "h": block.h,
                        "content": block.content,
                        "analysis_definition_id": analysis_lineage[0] if analysis_lineage else None,
                        "analysis_definition_version": analysis_lineage[1] if analysis_lineage else None,
                    },
                )
        return self.get_version(definition_id, version)

    def add_run(self, run: ReportRun) -> ReportRun:
        run_id = _uuid(run.run_id, "run_id")
        definition_id = _uuid(run.definition_id, "definition_id")
        try:
            with self._engine.begin() as connection:
                approved = connection.execute(
                    text(
                        """
                        SELECT 1 FROM report_v1.report_definition_versions v
                        JOIN report_v1.report_definitions d USING (definition_id)
                        WHERE v.definition_id = :definition_id
                          AND v.version = :version AND v.status = 'approved'
                          AND (:manage_all OR d.owner_id = :owner_id)
                        """
                    ),
                    {
                        **self._scope_params(),
                        "definition_id": definition_id,
                        "version": run.definition_version,
                    },
                ).first()
                if approved is None:
                    raise ValueError("승인된 Report definition version만 실행할 수 있습니다.")
                connection.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_runs
                            (run_id, definition_id, definition_version, as_of,
                             policy_version, context_hash, watermark, status)
                        VALUES (:run_id, :definition_id, :definition_version, :as_of,
                                :policy_version, :context_hash,
                                CAST(:watermark AS jsonb), :status)
                        """
                    ),
                    {
                        "run_id": run_id,
                        "definition_id": definition_id,
                        "definition_version": run.definition_version,
                        "as_of": run.as_of,
                        "policy_version": run.policy_version,
                        "context_hash": run.context_hash,
                        "watermark": json.dumps(dict(run.watermark)),
                        "status": run.status.value,
                    },
                )
                for block in run.blocks:
                    connection.execute(
                        text(
                            """
                            INSERT INTO report_v1.report_block_runs
                                (run_id, block_id, artifact_id, query_id,
                                 snapshot_checksum, status)
                            VALUES (:run_id, :block_id, :artifact_id, :query_id,
                                    :snapshot_checksum, :status)
                            """
                        ),
                        {
                            "run_id": run_id,
                            "block_id": _uuid(block.block_id, "block_id"),
                            "artifact_id": _uuid(block.artifact_id, "artifact_id"),
                            "query_id": block.query_id,
                            "snapshot_checksum": block.snapshot_checksum,
                            "status": block.status.value,
                        },
                    )
        except IntegrityError as error:
            raise ValueError("같은 Report run_id를 다시 저장할 수 없습니다.") from error
        return run

    def list_runs(self, definition_id: str | None = None) -> tuple[ReportRun, ...]:
        parameters = self._scope_params()
        filter_sql = ""
        if definition_id is not None:
            parameters["definition_id"] = _uuid(definition_id, "definition_id")
            filter_sql = "AND r.definition_id = :definition_id"
        with self._engine.connect() as connection:
            run_ids = connection.execute(
                text(
                    f"""
                    SELECT r.run_id
                    FROM report_v1.report_runs r
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE (:manage_all OR d.owner_id = :owner_id) {filter_sql}
                    ORDER BY r.created_at, r.run_id
                    """
                ),
                parameters,
            ).scalars().all()
        return tuple(self.get_run(str(run_id)) for run_id in run_ids)

    def get_run(self, run_id: str) -> ReportRun:
        run_uuid = _uuid(run_id, "run_id")
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT r.run_id, r.definition_id, r.definition_version, r.as_of,
                           r.policy_version, r.context_hash, r.watermark, r.status
                    FROM report_v1.report_runs r
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE r.run_id = :run_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                    """
                ),
                {**self._scope_params(), "run_id": run_uuid},
            ).mappings().one_or_none()
            if row is None:
                raise KeyError("Report run을 찾을 수 없습니다.")
            blocks = connection.execute(
                text(
                    """
                    SELECT block_id, artifact_id, query_id, snapshot_checksum, status,
                           request_id, failure_code, failure_message
                    FROM report_v1.report_block_runs
                    WHERE run_id = :run_id ORDER BY block_id
                    """
                ),
                {"run_id": run_uuid},
            ).mappings()
            return ReportRun(
                str(row["run_id"]),
                str(row["definition_id"]),
                row["definition_version"],
                row["as_of"],
                row["policy_version"],
                row["context_hash"],
                row["watermark"],
                RunStatus(row["status"]),
                tuple(
                    ReportBlockRun(
                        str(block["block_id"]),
                        str(block["artifact_id"]) if block["artifact_id"] else None,
                        block["query_id"],
                        block["snapshot_checksum"],
                        BlockRunStatus(block["status"]),
                        str(block["request_id"]) if block["request_id"] else None,
                        BlockFailureCode(block["failure_code"]) if block["failure_code"] else None,
                        block["failure_message"],
                    )
                    for block in blocks
                        ),
                    )

    def queue_manual_run(
        self,
        definition_id: str,
        version: int,
        as_of: datetime,
        idempotency_key: str,
    ) -> ManualRunCommand:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key는 비어 있을 수 없습니다.")
        definition_uuid = _uuid(definition_id, "definition_id")
        with self._engine.begin() as connection:
            approved = connection.execute(
                text(
                    """
                    SELECT 1 FROM report_v1.report_definition_versions v
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE v.definition_id = :definition_id AND v.version = :version
                      AND v.status = 'approved'
                      AND (:manage_all OR d.owner_id = :owner_id)
                    """
                ),
                {
                    **self._scope_params(),
                    "definition_id": definition_uuid,
                    "version": version,
                },
            ).first()
            if approved is None:
                raise ValueError("승인된 Report definition version만 실행할 수 있습니다.")
            row = connection.execute(
                text(
                    """
                    INSERT INTO report_v1.report_manual_run_commands
                        (command_id, definition_id, definition_version, as_of, idempotency_key)
                    VALUES (:command_id, :definition_id, :version, :as_of, :idempotency_key)
                    ON CONFLICT (definition_id, definition_version, idempotency_key)
                    DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
                    RETURNING command_id, definition_id, definition_version, as_of,
                              idempotency_key, status
                    """
                ),
                {
                    "command_id": uuid4(),
                    "definition_id": definition_uuid,
                    "version": version,
                    "as_of": as_of,
                    "idempotency_key": idempotency_key,
                },
            ).mappings().one()
        return ManualRunCommand(
            str(row["command_id"]),
            str(row["definition_id"]),
            row["definition_version"],
            row["as_of"],
            row["idempotency_key"],
            RunStatus(row["status"]),
        )

    def claim_manual_run(self, command_id: str) -> dict[str, object]:
        """Atomically claim a command and return immutable replay inputs."""
        command_uuid = _uuid(command_id, "command_id")
        with self._engine.begin() as connection:
            command = connection.execute(
                text(
                    """
                    SELECT c.definition_id, c.definition_version, c.as_of, c.run_id,
                           c.status, d.owner_id
                    FROM report_v1.report_manual_run_commands c
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE c.command_id = :command_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                    FOR UPDATE OF c
                    """
                ),
                {**self._scope_params(), "command_id": command_uuid},
            ).mappings().one_or_none()
            if command is None:
                raise KeyError("Report manual run command not found")
            if command["run_id"] is not None:
                return {
                    "claimed": False,
                    "run_id": str(command["run_id"]),
                    "status": command["status"],
                    "blocks": (),
                }

            blocks = connection.execute(
                text(
                    """
                    SELECT block_id, analysis_definition_id,
                           analysis_definition_version
                    FROM report_v1.report_blocks
                    WHERE definition_id = :definition_id
                      AND definition_version = :version
                      AND block_type IN ('table', 'chart', 'artifact')
                    ORDER BY y, x, block_id
                    """
                ),
                {
                    "definition_id": command["definition_id"],
                    "version": command["definition_version"],
                },
            ).mappings().all()
            run_id = uuid4()
            empty_watermark = json.dumps({}, sort_keys=True)
            connection.execute(
                text(
                    """
                    INSERT INTO report_v1.report_runs
                        (run_id, definition_id, definition_version, as_of,
                         policy_version, context_hash, watermark, status)
                    VALUES (:run_id, :definition_id, :version, :as_of,
                            'pending', :context_hash, CAST(:watermark AS jsonb),
                            'running')
                    """
                ),
                {
                    "run_id": run_id,
                    "definition_id": command["definition_id"],
                    "version": command["definition_version"],
                    "as_of": command["as_of"],
                    "context_hash": hashlib.sha256(empty_watermark.encode()).hexdigest(),
                    "watermark": empty_watermark,
                },
            )
            connection.execute(
                text(
                    """
                    UPDATE report_v1.report_manual_run_commands
                    SET status = 'running', run_id = :run_id
                    WHERE command_id = :command_id AND status = 'queued'
                    """
                ),
                {"run_id": run_id, "command_id": command_uuid},
            )
            return {
                "claimed": True,
                "run_id": str(run_id),
                "definition_id": str(command["definition_id"]),
                "definition_version": int(command["definition_version"]),
                "owner_id": UUID(str(command["owner_id"])),
                "as_of": command["as_of"],
                "blocks": tuple(
                    {
                        "block_id": str(block["block_id"]),
                        "analysis_definition_id": (
                            str(block["analysis_definition_id"])
                            if block["analysis_definition_id"]
                            else None
                        ),
                        "analysis_definition_version": (
                            int(block["analysis_definition_version"])
                            if block["analysis_definition_version"] is not None
                            else None
                        ),
                    }
                    for block in blocks
                ),
            }

    def record_block_run(
        self,
        run_id: str,
        block_id: str,
        *,
        status: BlockRunStatus,
        request_id: str | None = None,
        artifact_id: str | None = None,
        query_id: str | None = None,
        snapshot_checksum: str | None = None,
        policy_version: str | None = None,
        failure_code: BlockFailureCode | None = None,
        failure_message: str | None = None,
    ) -> None:
        run_uuid = _uuid(run_id, "run_id")
        block_uuid = _uuid(block_id, "block_id")
        status = BlockRunStatus(status)
        failure_code = BlockFailureCode(failure_code) if failure_code else None
        ReportBlockRun(
            block_id,
            artifact_id,
            query_id,
            snapshot_checksum,
            status,
            request_id,
            failure_code,
            failure_message,
        )
        with self._engine.begin() as connection:
            inserted = connection.execute(
                text(
                    """
                    INSERT INTO report_v1.report_block_runs
                        (run_id, block_id, request_id, artifact_id, query_id,
                         snapshot_checksum, policy_version, status,
                         failure_code, failure_message)
                    SELECT r.run_id, b.block_id, :request_id, :artifact_id, :query_id,
                           :checksum, :policy_version, :status,
                           :failure_code, :failure_message
                    FROM report_v1.report_runs r
                    JOIN report_v1.report_definitions d USING (definition_id)
                    JOIN report_v1.report_blocks b
                      ON b.definition_id = r.definition_id
                     AND b.definition_version = r.definition_version
                     AND b.block_id = :block_id
                    WHERE r.run_id = :run_id AND r.status = 'running'
                      AND b.block_type IN ('table', 'chart', 'artifact')
                      AND (:manage_all OR d.owner_id = :owner_id)
                    ON CONFLICT (run_id, block_id) DO NOTHING
                    """
                ),
                {
                    **self._scope_params(),
                    "run_id": run_uuid,
                    "block_id": block_uuid,
                    "request_id": _uuid(request_id, "request_id") if request_id else None,
                    "artifact_id": _uuid(artifact_id, "artifact_id") if artifact_id else None,
                    "query_id": query_id,
                    "checksum": snapshot_checksum,
                    "policy_version": policy_version,
                    "status": status.value,
                    "failure_code": failure_code.value if failure_code else None,
                    "failure_message": failure_message,
                },
            )
            if inserted.rowcount != 1:
                existing = connection.execute(
                    text(
                        "SELECT 1 FROM report_v1.report_block_runs "
                        "WHERE run_id = :run_id AND block_id = :block_id"
                    ),
                    {"run_id": run_uuid, "block_id": block_uuid},
                ).first()
                if existing is None:
                    raise KeyError("running Report block not found")

    def finish_manual_run(self, command_id: str) -> ReportRun:
        command_uuid = _uuid(command_id, "command_id")
        with self._engine.begin() as connection:
            command = connection.execute(
                text(
                    """
                    SELECT c.run_id, c.definition_id, c.definition_version, c.status
                    FROM report_v1.report_manual_run_commands c
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE c.command_id = :command_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                    FOR UPDATE OF c
                    """
                ),
                {**self._scope_params(), "command_id": command_uuid},
            ).mappings().one_or_none()
            if command is None or command["run_id"] is None:
                raise KeyError("claimed Report manual run command not found")
            run_id = command["run_id"]
            if command["status"] != RunStatus.RUNNING.value:
                return self.get_run(str(run_id))

            connection.execute(
                text(
                    """
                    INSERT INTO report_v1.report_block_runs
                        (run_id, block_id, status, failure_code, failure_message)
                    SELECT :run_id, b.block_id, 'failed', 'REPLAY_UNAVAILABLE',
                           'The analysis block could not be replayed.'
                    FROM report_v1.report_blocks b
                    WHERE b.definition_id = :definition_id
                      AND b.definition_version = :version
                      AND b.block_type IN ('table', 'chart', 'artifact')
                      AND NOT EXISTS (
                          SELECT 1 FROM report_v1.report_block_runs br
                          WHERE br.run_id = :run_id AND br.block_id = b.block_id
                      )
                    """
                ),
                {
                    "run_id": run_id,
                    "definition_id": command["definition_id"],
                    "version": command["definition_version"],
                },
            )
            rows = connection.execute(
                text(
                    """
                    SELECT status, artifact_id, snapshot_checksum, policy_version
                    FROM report_v1.report_block_runs
                    WHERE run_id = :run_id
                    """
                ),
                {"run_id": run_id},
            ).mappings().all()
            statuses = [row["status"] for row in rows]
            if not statuses or all(status == "success" for status in statuses):
                run_status = RunStatus.SUCCESS.value
            elif any(status in {"success", "partial"} for status in statuses):
                run_status = RunStatus.PARTIAL.value
            elif all(status == "cancelled" for status in statuses):
                run_status = RunStatus.CANCELLED.value
            else:
                run_status = RunStatus.FAILED.value
            watermark = {
                str(row["artifact_id"]): row["snapshot_checksum"]
                for row in rows
                if row["artifact_id"] and row["snapshot_checksum"]
            }
            policy_versions = sorted(
                {str(row["policy_version"]) for row in rows if row["policy_version"]}
            )
            policy_version = ",".join(policy_versions) if policy_versions else "unavailable"
            serialized_watermark = json.dumps(watermark, sort_keys=True)
            connection.execute(
                text(
                    """
                    UPDATE report_v1.report_runs
                    SET status = :status, policy_version = :policy_version,
                        context_hash = :context_hash,
                        watermark = CAST(:watermark AS jsonb)
                    WHERE run_id = :run_id AND status = 'running'
                    """
                ),
                {
                    "run_id": run_id,
                    "status": run_status,
                    "policy_version": policy_version,
                    "context_hash": hashlib.sha256(serialized_watermark.encode()).hexdigest(),
                    "watermark": serialized_watermark,
                },
            )
            connection.execute(
                text(
                    """
                    UPDATE report_v1.report_manual_run_commands
                    SET status = :status
                    WHERE command_id = :command_id AND status = 'running'
                    """
                ),
                {"command_id": command_uuid, "status": run_status},
            )
        return self.get_run(str(run_id))

    def create_schedule(
        self,
        schedule_id: str,
        definition_id: str,
        version: int,
        cadence: str,
        timezone_name: str,
        next_run_at: datetime,
    ) -> dict[str, object]:
        schedule_uuid = _uuid(schedule_id, "schedule_id")
        definition_uuid = _uuid(definition_id, "definition_id")
        if cadence not in {"daily", "weekly", "monthly"}:
            raise ValueError("지원하지 않는 Report cadence입니다.")
        if timezone_name != "Asia/Seoul":
            raise ValueError("Report schedule timezone은 Asia/Seoul이어야 합니다.")
        try:
            with self._engine.begin() as connection:
                approved = connection.execute(
                    text(
                        """
                        SELECT 1 FROM report_v1.report_definition_versions v
                        JOIN report_v1.report_definitions d USING (definition_id)
                        WHERE v.definition_id = :definition_id AND v.version = :version
                          AND v.status = 'approved'
                          AND (:manage_all OR d.owner_id = :owner_id)
                        """
                    ),
                    {
                        **self._scope_params(),
                        "definition_id": definition_uuid,
                        "version": version,
                    },
                ).first()
                if approved is None:
                    raise ValueError("관리 범위의 승인된 Report definition version만 예약할 수 있습니다.")
                connection.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_schedules
                            (schedule_id, definition_id, definition_version, cadence,
                             timezone_name, next_run_at)
                        VALUES (:schedule_id, :definition_id, :version, :cadence,
                                :timezone_name, :next_run_at)
                        """
                    ),
                    {
                        "schedule_id": schedule_uuid,
                        "definition_id": definition_uuid,
                        "version": version,
                        "cadence": cadence,
                        "timezone_name": timezone_name,
                        "next_run_at": next_run_at,
                    },
                )
        except IntegrityError as error:
            raise ValueError("같은 Report schedule_id가 이미 존재합니다.") from error
        return self.get_schedule(str(schedule_uuid))

    def get_assistant_artifact(self, artifact_id: str) -> dict[str, object]:
        artifact_uuid = _uuid(artifact_id, "artifact_id")
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT a.artifact_id, a.title, a.narrative_markdown,
                           a.evidence_json, a.chart_spec_json, a.artifact_checksum,
                           q.trino_query_id
                    FROM artifact.analysis_artifacts a
                    JOIN query.query_executions q
                      ON q.query_execution_id = a.query_execution_id
                    JOIN chat.analysis_requests r ON r.request_id = a.request_id
                    WHERE a.artifact_id = :artifact_id
                      AND a.status = 'APPROVED'
                      AND r.status IN ('SUCCEEDED', 'PARTIAL')
                      AND r.user_id = :owner_id
                    """
                ),
                {"artifact_id": artifact_uuid, "owner_id": self._owner_id},
            ).mappings().one_or_none()
        if row is None:
            raise KeyError("승인된 Analysis Artifact를 찾을 수 없습니다.")
        return dict(row)

    def get_transfer_artifact(self, artifact_id: str) -> dict[str, object]:
        artifact_uuid = _uuid(artifact_id, "artifact_id")
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT a.artifact_id, a.narrative_markdown,
                           a.data_snapshot_json, a.evidence_json, a.chart_spec_json,
                           q.trino_query_id
                    FROM artifact.analysis_artifacts a
                    JOIN query.query_executions q
                      ON q.query_execution_id = a.query_execution_id
                    JOIN chat.analysis_requests r ON r.request_id = a.request_id
                    WHERE a.artifact_id = :artifact_id
                      AND a.status = 'APPROVED'
                      AND r.status IN ('SUCCEEDED', 'PARTIAL')
                      AND r.user_id = :owner_id
                    """
                ),
                {"artifact_id": artifact_uuid, "owner_id": self._owner_id},
            ).mappings().one_or_none()
        if row is None:
            raise KeyError("본인의 승인된 Analysis Artifact를 찾을 수 없습니다.")
        return dict(row)

    def get_report_artifact(
        self,
        definition_id: str,
        version: int,
        artifact_id: str,
    ) -> dict[str, object]:
        artifact_uuid = _uuid(artifact_id, "artifact_id")
        definition = self.get_version(definition_id, version)
        if not any(block.artifact_id == str(artifact_uuid) for block in definition.blocks):
            raise KeyError("보고서에 연결된 Analysis Artifact를 찾을 수 없습니다.")
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT a.artifact_id, a.title, a.narrative_markdown,
                           a.data_snapshot_json, a.evidence_json,
                           a.chart_spec_json, a.artifact_checksum,
                           q.trino_query_id
                    FROM artifact.analysis_artifacts a
                    JOIN query.query_executions q
                      ON q.query_execution_id = a.query_execution_id
                    JOIN chat.analysis_requests r ON r.request_id = a.request_id
                    WHERE a.artifact_id = :artifact_id
                      AND a.status = 'APPROVED'
                      AND r.status IN ('SUCCEEDED', 'PARTIAL')
                      AND r.user_id = :owner_id
                    """
                ),
                {"artifact_id": artifact_uuid, "owner_id": self._owner_id},
            ).mappings().one_or_none()
        if row is None:
            raise KeyError("승인된 Analysis Artifact를 찾을 수 없습니다.")
        return dict(row)

    def start_assistant_request(
        self,
        assistant_request_id: str,
        artifact_id: str,
        instruction_hash: str,
        prompt_id: str,
        prompt_version: str,
        prompt_hash: str,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO report_v1.report_assistant_requests
                        (assistant_request_id, owner_id, artifact_id, instruction_hash,
                         status, prompt_id, prompt_version, prompt_hash)
                    VALUES (:request_id, :owner_id, :artifact_id, :instruction_hash,
                            'running', :prompt_id, :prompt_version, :prompt_hash)
                    """
                ),
                {
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                    "artifact_id": _uuid(artifact_id, "artifact_id"),
                    "instruction_hash": instruction_hash,
                    "prompt_id": prompt_id,
                    "prompt_version": prompt_version,
                    "prompt_hash": prompt_hash,
                },
            )

    def complete_assistant_request(
        self,
        assistant_request_id: str,
        definition_id: str,
        version: int,
        model_version: str,
        output_hash: str,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE report_v1.report_assistant_requests
                    SET status = 'success', definition_id = :definition_id,
                        definition_version = :version, model_version = :model_version,
                        output_hash = :output_hash, completed_at = now()
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND status = 'running'
                    """
                ),
                {
                    "definition_id": _uuid(definition_id, "definition_id"),
                    "version": version,
                    "model_version": model_version,
                    "output_hash": output_hash,
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                },
            )

    def fail_assistant_request(self, assistant_request_id: str, error_code: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE report_v1.report_assistant_requests
                    SET status = 'failed', error_code = :error_code, completed_at = now()
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND status = 'running'
                    """
                ),
                {
                    "error_code": error_code,
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                },
            )

    def get_schedule(self, schedule_id: str) -> dict[str, object]:
        schedule_uuid = _uuid(schedule_id, "schedule_id")
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT s.schedule_id, s.definition_id, s.definition_version,
                           s.cadence, s.timezone_name, s.next_run_at,
                           s.enabled, s.last_run_id
                    FROM report_v1.report_schedules s
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE s.schedule_id = :schedule_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                    """
                ),
                {**self._scope_params(), "schedule_id": schedule_uuid},
            ).mappings().one_or_none()
        if row is None:
            raise KeyError("Report schedule을 찾을 수 없습니다.")
        return self._schedule_response(row)

    def list_schedules(self) -> tuple[dict[str, object], ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT s.schedule_id, s.definition_id, s.definition_version,
                           s.cadence, s.timezone_name, s.next_run_at,
                           s.enabled, s.last_run_id
                    FROM report_v1.report_schedules s
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE (:manage_all OR d.owner_id = :owner_id)
                    ORDER BY s.created_at, s.schedule_id
                    """
                ),
                self._scope_params(),
            ).mappings().all()
        return tuple(self._schedule_response(row) for row in rows)

    def list_due_schedule_ids(
        self,
        now: datetime,
        *,
        limit: int = 50,
    ) -> tuple[str, ...]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now에는 timezone offset이 필요합니다.")
        if limit < 1 or limit > 100:
            raise ValueError("Report schedule 조회 limit은 1~100이어야 합니다.")
        with self._engine.connect() as connection:
            schedule_ids = connection.execute(
                text(
                    """
                    SELECT s.schedule_id
                    FROM report_v1.report_schedules s
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE s.enabled AND s.next_run_at <= :now
                      AND (:manage_all OR d.owner_id = :owner_id)
                    ORDER BY s.next_run_at, s.schedule_id
                    LIMIT :limit
                    """
                ),
                {**self._scope_params(), "now": now, "limit": limit},
            ).scalars().all()
        return tuple(str(schedule_id) for schedule_id in schedule_ids)

    def set_schedule_enabled(
        self,
        schedule_id: str,
        enabled: bool,
    ) -> dict[str, object]:
        schedule_uuid = _uuid(schedule_id, "schedule_id")
        with self._engine.begin() as connection:
            updated = connection.execute(
                text(
                    """
                    UPDATE report_v1.report_schedules AS s
                    SET enabled = :enabled, updated_at = now()
                    FROM report_v1.report_definitions AS d
                    WHERE s.schedule_id = :schedule_id
                      AND d.definition_id = s.definition_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                    RETURNING s.schedule_id
                    """
                ),
                {
                    **self._scope_params(),
                    "schedule_id": schedule_uuid,
                    "enabled": enabled,
                },
            ).scalar_one_or_none()
        if updated is None:
            raise KeyError("Report schedule을 찾을 수 없습니다.")
        return self.get_schedule(str(updated))

    def queue_due_schedule(
        self,
        schedule_id: str,
        now: datetime,
    ) -> tuple[dict[str, object], ManualRunCommand | None]:
        schedule_uuid = _uuid(schedule_id, "schedule_id")
        command = None
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT s.definition_id, s.definition_version, s.cadence,
                           s.next_run_at, s.enabled
                    FROM report_v1.report_schedules s
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE s.schedule_id = :schedule_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                    FOR UPDATE OF s
                    """
                ),
                {**self._scope_params(), "schedule_id": schedule_uuid},
            ).mappings().one_or_none()
            if row is None:
                raise KeyError("Report schedule not found")
            if row["enabled"] and row["next_run_at"] <= now:
                scheduled_for = row["next_run_at"]
                command_row = connection.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_manual_run_commands
                            (command_id, definition_id, definition_version, as_of,
                             idempotency_key)
                        VALUES (:command_id, :definition_id, :version, :as_of,
                                :idempotency_key)
                        ON CONFLICT (definition_id, definition_version, idempotency_key)
                        DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
                        RETURNING command_id, definition_id, definition_version, as_of,
                                  idempotency_key, status
                        """
                    ),
                    {
                        "command_id": uuid4(),
                        "definition_id": row["definition_id"],
                        "version": row["definition_version"],
                        "as_of": scheduled_for,
                        "idempotency_key": f"schedule:{schedule_uuid}:{scheduled_for.isoformat()}",
                    },
                ).mappings().one()
                command = ManualRunCommand(
                    str(command_row["command_id"]),
                    str(command_row["definition_id"]),
                    command_row["definition_version"],
                    command_row["as_of"],
                    command_row["idempotency_key"],
                    RunStatus(command_row["status"]),
                )
        return self.get_schedule(str(schedule_uuid)), command

    def complete_due_schedule(
        self,
        schedule_id: str,
        scheduled_for: datetime,
        run_id: str,
    ) -> dict[str, object]:
        schedule_uuid = _uuid(schedule_id, "schedule_id")
        run_uuid = _uuid(run_id, "run_id")
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT s.cadence, s.next_run_at
                    FROM report_v1.report_schedules s
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE s.schedule_id = :schedule_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                    FOR UPDATE OF s
                    """
                ),
                {**self._scope_params(), "schedule_id": schedule_uuid},
            ).mappings().one_or_none()
            if row is None:
                raise KeyError("Report schedule not found")
            if row["next_run_at"] == scheduled_for:
                connection.execute(
                    text(
                        """
                        UPDATE report_v1.report_schedules
                        SET next_run_at = :next_run_at, last_run_id = :run_id,
                            updated_at = now()
                        WHERE schedule_id = :schedule_id
                        """
                    ),
                    {
                        "next_run_at": _advance_schedule(scheduled_for, row["cadence"]),
                        "run_id": run_uuid,
                        "schedule_id": schedule_uuid,
                    },
                )
        return self.get_schedule(str(schedule_uuid))

    @staticmethod
    def _schedule_response(row) -> dict[str, object]:
        return {
            "schedule_id": row["schedule_id"],
            "definition_id": row["definition_id"],
            "version": row["definition_version"],
            "cadence": row["cadence"],
            "timezone": row["timezone_name"],
            "next_run_at": row["next_run_at"],
            "enabled": row["enabled"],
            "last_run_id": row["last_run_id"],
        }
