from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from src.report.domain import DefinitionStatus, ReportBlock, ReportDefinitionVersion, ReportRun


@lru_cache(maxsize=None)
def _engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def _uuid(value: str, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(f"{field}는 UUID 형식이어야 합니다.") from error


class PostgresReportRepository:
    """REPORT-v1.0.0 proposal의 application PostgreSQL 저장소."""

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
                                 artifact_id, query_id, columns)
                            VALUES (:definition_id, :version, :block_id, :title,
                                    :artifact_id, :query_id, :columns)
                            """
                        ),
                        {
                            "definition_id": definition_id,
                            "version": draft.version,
                            "block_id": _uuid(block.block_id, "block_id"),
                            "title": block.title,
                            "artifact_id": _uuid(block.artifact_id, "artifact_id"),
                            "query_id": block.query_id,
                            "columns": block.columns,
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
                    SELECT block_id, title, artifact_id, query_id, columns
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
                        str(block["artifact_id"]),
                        block["columns"],
                        block["query_id"],
                    )
                    for block in blocks
                ),
                approved_at=row["approved_at"],
            )

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
