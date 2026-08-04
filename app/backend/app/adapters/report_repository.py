from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from src.report.domain import (
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


class PostgresReportRepository:
    """Owner-scoped REPORT-v1.1 application PostgreSQL 저장소."""

    def __init__(self, database_url: str, owner_id: UUID) -> None:
        self._engine = _engine(database_url)
        self._owner_id = owner_id

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
                if owner != self._owner_id:
                    raise ValueError("다른 사용자의 Report definition입니다.")
                connection.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_definition_versions
                            (definition_id, version, status, title)
                        VALUES (:definition_id, :version, 'draft', :title)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "version": draft.version,
                        "title": draft.title,
                    },
                )
                for block in draft.blocks:
                    connection.execute(
                        text(
                            """
                            INSERT INTO report_v1.report_blocks
                                (definition_id, definition_version, block_id, title,
                                 artifact_id, query_id, columns, block_type, x, y, w, h, content)
                            VALUES (:definition_id, :version, :block_id, :title,
                                    :artifact_id, :query_id, :columns, :block_type,
                                    :x, :y, :w, :h, :content)
                            """
                        ),
                        {
                            "definition_id": definition_id,
                            "version": draft.version,
                            "block_id": _uuid(block.block_id, "block_id"),
                            "title": block.title,
                            "artifact_id": (
                                _uuid(block.artifact_id, "artifact_id")
                                if block.artifact_id else None
                            ),
                            "query_id": block.query_id,
                            "columns": block.columns,
                            "block_type": block.type.value,
                            "x": block.x,
                            "y": block.y,
                            "w": block.w,
                            "h": block.h,
                            "content": block.content,
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
                    SELECT v.definition_id, v.version, v.status, v.title, v.approved_at
                    FROM report_v1.report_definition_versions v
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE v.definition_id = :definition_id AND v.version = :version
                      AND d.owner_id = :owner_id
                    """
                ),
                {
                    "definition_id": definition_uuid,
                    "version": version,
                    "owner_id": self._owner_id,
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
                    ORDER BY block_id
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
            )

    def list_definitions(self) -> tuple[ReportDefinitionVersion, ...]:
        with self._engine.connect() as connection:
            keys = connection.execute(
                text(
                    """
                    SELECT v.definition_id, v.version
                    FROM report_v1.report_definition_versions v
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE d.owner_id = :owner_id
                    ORDER BY v.definition_id, v.version
                    """
                ),
                {"owner_id": self._owner_id},
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
                      AND d.owner_id = :owner_id AND v.status = 'draft'
                    """
                ),
                {
                    "definition_id": definition_uuid,
                    "version": version,
                    "owner_id": self._owner_id,
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
                          AND d.owner_id = :owner_id
                        """
                    ),
                    {
                        "definition_id": definition_uuid,
                        "version": version,
                        "owner_id": self._owner_id,
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
                      AND d.owner_id = :owner_id
                    FOR UPDATE
                    """
                ),
                {"definition_id": definition_uuid, "version": version, "owner_id": self._owner_id},
            ).scalar_one_or_none()
            if status is None:
                raise KeyError("Report definition version을 찾을 수 없습니다.")
            if status != DefinitionStatus.DRAFT.value:
                raise ValueError("draft Report version만 block layout을 교체할 수 있습니다.")
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
                connection.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_blocks
                            (definition_id, definition_version, block_id, title,
                             artifact_id, query_id, columns, block_type, x, y, w, h, content)
                        VALUES (:definition_id, :version, :block_id, :title,
                                :artifact_id, :query_id, :columns, :block_type,
                                :x, :y, :w, :h, :content)
                        """
                    ),
                    {
                        "definition_id": definition_uuid,
                        "version": version,
                        "block_id": _uuid(block.block_id, "block_id"),
                        "title": block.title,
                        "artifact_id": _uuid(block.artifact_id, "artifact_id") if block.artifact_id else None,
                        "query_id": block.query_id,
                        "columns": block.columns,
                        "block_type": block.type.value,
                        "x": block.x,
                        "y": block.y,
                        "w": block.w,
                        "h": block.h,
                        "content": block.content,
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
                          AND d.owner_id = :owner_id
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "version": run.definition_version,
                        "owner_id": self._owner_id,
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
        parameters: dict[str, object] = {"owner_id": self._owner_id}
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
                    WHERE d.owner_id = :owner_id {filter_sql}
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
                    WHERE r.run_id = :run_id AND d.owner_id = :owner_id
                    """
                ),
                {"run_id": run_uuid, "owner_id": self._owner_id},
            ).mappings().one_or_none()
            if row is None:
                raise KeyError("Report run을 찾을 수 없습니다.")
            blocks = connection.execute(
                text(
                    """
                    SELECT block_id, artifact_id, query_id, snapshot_checksum, status
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
                        str(block["artifact_id"]),
                        block["query_id"],
                        block["snapshot_checksum"],
                        BlockRunStatus(block["status"]),
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
                      AND v.status = 'approved' AND d.owner_id = :owner_id
                    """
                ),
                {"definition_id": definition_uuid, "version": version, "owner_id": self._owner_id},
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
