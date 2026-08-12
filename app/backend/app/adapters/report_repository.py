from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from src.report.domain import (
    AnalysisBinding,
    AnalysisReplayResult,
    BlockRunStatus,
    BlockType,
    DefinitionStatus,
    ManualRunCommand,
    ReportBlock,
    ReportBlockRun,
    ReportCommand,
    ReportDefinitionVersion,
    ReportRun,
    ReportSchedule,
    RunStatus,
    ScheduleFrequency,
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

    def _validate_artifact_block(self, connection, block: ReportBlock) -> None:
        if block.type is BlockType.TEXT:
            return
        if not block.artifact_id:
            raise ValueError("table/chart block에는 Artifact가 필요합니다.")
        artifact = connection.execute(
            text(
                """
                SELECT q.trino_query_id
                FROM artifact.analysis_artifacts a
                JOIN chat.analysis_requests r ON r.request_id = a.request_id
                JOIN query.query_executions q
                  ON q.query_execution_id = a.query_execution_id
                JOIN analysis_v1.analysis_run_links l ON l.request_id = a.request_id
                JOIN analysis_v1.analysis_definitions d
                  ON d.definition_id = l.definition_id
                 AND d.version = l.definition_version
                WHERE a.artifact_id = :artifact_id
                  AND a.status = 'APPROVED'
                  AND r.user_id = :owner_id
                  AND d.owner_id = :owner_id
                """
            ),
            {
                "artifact_id": _uuid(block.artifact_id, "artifact_id"),
                "owner_id": self._owner_id,
            },
        ).scalar_one_or_none()
        if artifact is None:
            raise ValueError("본인 소유의 재실행 가능한 Artifact만 Report에 포함할 수 있습니다.")
        if block.query_id and block.query_id != artifact:
            raise ValueError("Artifact와 query_id가 일치하지 않습니다.")

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
                    self._validate_artifact_block(connection, block)
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
                self._validate_artifact_block(connection, block)
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

    def save_schedule(self, schedule: ReportSchedule) -> ReportSchedule:
        definition_id = _uuid(schedule.definition_id, "definition_id")
        if schedule.enabled:
            self.assert_schedule_activatable(schedule.definition_id, schedule.version)
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
                {"definition_id": definition_id, "version": schedule.version, "owner_id": self._owner_id},
            ).first()
            if approved is None:
                raise ValueError("승인된 Report definition version만 예약할 수 있습니다.")
            connection.execute(
                text(
                    """
                    INSERT INTO report_v1.report_schedules
                        (schedule_id, definition_id, definition_version, frequency,
                         hour, minute, weekday, day_of_month, timezone_name,
                         enabled, next_run_at)
                    VALUES (:schedule_id, :definition_id, :version, :frequency,
                            :hour, :minute, :weekday, :day_of_month, :timezone,
                            :enabled, :next_run_at)
                    ON CONFLICT (definition_id, definition_version) DO UPDATE SET
                        frequency = EXCLUDED.frequency, hour = EXCLUDED.hour,
                        minute = EXCLUDED.minute, weekday = EXCLUDED.weekday,
                        day_of_month = EXCLUDED.day_of_month,
                        enabled = EXCLUDED.enabled, next_run_at = EXCLUDED.next_run_at,
                        updated_at = now()
                    """
                ),
                {
                    "schedule_id": _uuid(schedule.schedule_id, "schedule_id"),
                    "definition_id": definition_id,
                    "version": schedule.version,
                    "frequency": schedule.frequency.value,
                    "hour": schedule.hour,
                    "minute": schedule.minute,
                    "weekday": schedule.weekday,
                    "day_of_month": schedule.day_of_month,
                    "timezone": schedule.timezone,
                    "enabled": schedule.enabled,
                    "next_run_at": schedule.next_run_at,
                },
            )
        return schedule

    def assert_schedule_activatable(self, definition_id: str, version: int) -> None:
        definition_uuid = _uuid(definition_id, "definition_id")
        with self._engine.connect() as connection:
            successful_manual_run = connection.execute(
                text(
                    """
                    SELECT 1
                    FROM report_v1.report_manual_run_commands c
                    JOIN report_v1.report_runs r ON r.run_id = c.run_id
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE c.definition_id = :definition_id
                      AND c.definition_version = :version
                      AND c.trigger_type = 'MANUAL'
                      AND c.status = 'success'
                      AND r.status = 'success'
                      AND d.owner_id = :owner_id
                    LIMIT 1
                    """
                ),
                {
                    "definition_id": definition_uuid,
                    "version": version,
                    "owner_id": self._owner_id,
                },
            ).first()
            if successful_manual_run is None:
                raise ValueError("스케줄 활성화 전에 성공한 수동 실행이 필요합니다.")
            missing_binding = connection.execute(
                text(
                    """
                    SELECT b.block_id
                    FROM report_v1.report_blocks b
                    WHERE b.definition_id = :definition_id
                      AND b.definition_version = :version
                      AND b.block_type <> 'text'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM artifact.analysis_artifacts a
                          JOIN analysis_v1.analysis_run_links l
                            ON l.request_id = a.request_id
                          JOIN analysis_v1.analysis_definitions ad
                            ON ad.definition_id = l.definition_id
                           AND ad.version = l.definition_version
                          JOIN governance.audit_events e
                            ON e.request_id = a.request_id
                           AND e.action_code = 'ANALYSIS_ACCESS_COMPLETED'
                          JOIN context.context_packages cp
                            ON cp.request_id = a.request_id
                           AND cp.user_scope_json ->> 'entitlement_hash'
                               = e.details_json_redacted ->> 'entitlement_hash'
                          WHERE a.artifact_id = b.artifact_id
                            AND a.status = 'APPROVED'
                            AND ad.owner_id = :owner_id
                            AND e.details_json_redacted ->> 'request_status'
                                IN ('SUCCEEDED', 'PARTIAL')
                            AND e.details_json_redacted ?& ARRAY[
                                'access_profile', 'allowed_domains', 'policy_version',
                                'entitlement_hash', 'datahub_actor', 'trino_role'
                            ]
                      )
                    LIMIT 1
                    """
                ),
                {
                    "definition_id": definition_uuid,
                    "version": version,
                    "owner_id": self._owner_id,
                },
            ).first()
        if missing_binding is not None:
            raise ValueError("스케줄 활성화 전에 모든 block의 재실행 binding이 필요합니다.")

    @staticmethod
    def _schedule(row) -> ReportSchedule:
        return ReportSchedule(
            str(row["schedule_id"]), str(row["definition_id"]), row["definition_version"],
            ScheduleFrequency(row["frequency"]), row["hour"], row["minute"],
            row["timezone_name"], row["weekday"], row["day_of_month"],
            row["enabled"], row["next_run_at"],
        )

    def list_schedules(self) -> tuple[ReportSchedule, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT s.* FROM report_v1.report_schedules s
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE d.owner_id = :owner_id ORDER BY s.created_at, s.schedule_id
                    """
                ),
                {"owner_id": self._owner_id},
            ).mappings()
            return tuple(self._schedule(row) for row in rows)

    def queue_due_schedules(self, current: datetime) -> tuple[ManualRunCommand, ...]:
        commands = []
        with self._engine.begin() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT s.* FROM report_v1.report_schedules s
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE d.owner_id = :owner_id AND s.enabled
                      AND s.next_run_at <= :current
                    ORDER BY s.next_run_at FOR UPDATE OF s SKIP LOCKED
                    """
                ),
                {"owner_id": self._owner_id, "current": current},
            ).mappings().all()
            for row in rows:
                schedule = self._schedule(row)
                idempotency_key = f"schedule:{schedule.schedule_id}:{schedule.next_run_at.isoformat()}"
                command_row = connection.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_manual_run_commands
                            (command_id, definition_id, definition_version, as_of,
                             idempotency_key, trigger_type, schedule_id)
                        VALUES (:command_id, :definition_id, :version, :as_of,
                                :idempotency_key, 'SCHEDULE', :schedule_id)
                        ON CONFLICT (definition_id, definition_version, idempotency_key)
                        DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
                        RETURNING command_id, definition_id, definition_version,
                                  as_of, idempotency_key, status
                        """
                    ),
                    {
                        "command_id": uuid4(),
                        "definition_id": row["definition_id"],
                        "version": row["definition_version"],
                        "as_of": row["next_run_at"],
                        "idempotency_key": idempotency_key,
                        "schedule_id": row["schedule_id"],
                    },
                ).mappings().one()
                commands.append(ManualRunCommand(
                    str(command_row["command_id"]), str(command_row["definition_id"]),
                    command_row["definition_version"], command_row["as_of"],
                    command_row["idempotency_key"], RunStatus(command_row["status"]),
                ))
                connection.execute(
                    text("UPDATE report_v1.report_schedules SET next_run_at = :next_run_at, updated_at = now() WHERE schedule_id = :schedule_id"),
                    {
                        "schedule_id": row["schedule_id"],
                        "next_run_at": schedule.next_after(schedule.next_run_at),
                    },
                )
        return tuple(commands)


class PostgresReportWorkerRepository:
    """Trusted worker persistence; HTTP owner scoping is intentionally not exposed here."""

    def __init__(self, database_url: str) -> None:
        self._engine = _engine(database_url)

    def enqueue_due_schedules(self, current: datetime) -> int:
        queued = 0
        with self._engine.begin() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT * FROM report_v1.report_schedules
                    WHERE enabled AND next_run_at <= :current
                    ORDER BY next_run_at FOR UPDATE SKIP LOCKED
                    """
                ),
                {"current": current},
            ).mappings().all()
            for row in rows:
                schedule = PostgresReportRepository._schedule(row)
                result = connection.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_manual_run_commands
                            (command_id, definition_id, definition_version, as_of,
                             idempotency_key, trigger_type, schedule_id)
                        VALUES (:command_id, :definition_id, :version, :as_of,
                                :idempotency_key, 'SCHEDULE', :schedule_id)
                        ON CONFLICT (definition_id, definition_version, idempotency_key)
                        DO NOTHING
                        """
                    ),
                    {
                        "command_id": uuid4(),
                        "definition_id": row["definition_id"],
                        "version": row["definition_version"],
                        "as_of": row["next_run_at"],
                        "idempotency_key": f"schedule:{schedule.schedule_id}:{schedule.next_run_at.isoformat()}",
                        "schedule_id": row["schedule_id"],
                    },
                )
                queued += result.rowcount
                connection.execute(
                    text(
                        """
                        UPDATE report_v1.report_schedules
                        SET next_run_at = :next_run_at, updated_at = now()
                        WHERE schedule_id = :schedule_id
                        """
                    ),
                    {
                        "schedule_id": row["schedule_id"],
                        "next_run_at": schedule.next_after(schedule.next_run_at),
                    },
                )
        return queued

    def claim_next(self) -> ReportCommand | None:
        with self._engine.begin() as connection:
            # ponytail: 30-minute lease avoids a permanent stuck command; add heartbeats if runs exceed it.
            connection.execute(
                text(
                    """
                    UPDATE report_v1.report_manual_run_commands
                    SET status = 'queued', claimed_at = NULL
                    WHERE status = 'running' AND claimed_at < now() - interval '30 minutes'
                    """
                )
            )
            row = connection.execute(
                text(
                    """
                    WITH candidate AS (
                        SELECT command_id
                        FROM report_v1.report_manual_run_commands
                        WHERE status = 'queued'
                        ORDER BY created_at, command_id
                        FOR UPDATE SKIP LOCKED LIMIT 1
                    )
                    UPDATE report_v1.report_manual_run_commands c
                    SET status = 'running', claimed_at = now()
                    FROM candidate
                    WHERE c.command_id = candidate.command_id
                    RETURNING c.command_id, c.definition_id, c.definition_version,
                              c.as_of, c.trigger_type
                    """
                )
            ).mappings().one_or_none()
            if row is None:
                return None
            owner_id = connection.execute(
                text("SELECT owner_id FROM report_v1.report_definitions WHERE definition_id = :definition_id"),
                {"definition_id": row["definition_id"]},
            ).scalar_one()
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
                {"definition_id": row["definition_id"], "version": row["definition_version"]},
            ).mappings()
            return ReportCommand(
                str(row["command_id"]), str(row["definition_id"]),
                row["definition_version"], owner_id, row["as_of"], row["trigger_type"],
                tuple(
                    ReportBlock(
                        str(block["block_id"]), block["title"],
                        str(block["artifact_id"]) if block["artifact_id"] else None,
                        block["columns"], block["query_id"], BlockType(block["block_type"]),
                        block["x"], block["y"], block["w"], block["h"], block["content"],
                    )
                    for block in blocks
                ),
            )

    def analysis_binding(self, artifact_id: str) -> AnalysisBinding:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT l.definition_id, l.definition_version, d.owner_id,
                           e.actor_role, d.question_text_redacted, d.parameters_json,
                           e.details_json_redacted ->> 'access_profile' AS access_profile,
                           ARRAY(
                               SELECT jsonb_array_elements_text(
                                   e.details_json_redacted -> 'allowed_domains'
                               )
                           ) AS allowed_domains,
                           e.details_json_redacted ->> 'policy_version' AS policy_version,
                           e.details_json_redacted ->> 'entitlement_hash' AS entitlement_hash,
                           e.details_json_redacted ->> 'datahub_actor' AS datahub_principal,
                           e.details_json_redacted ->> 'trino_role' AS trino_principal
                    FROM artifact.analysis_artifacts a
                    JOIN analysis_v1.analysis_run_links l ON l.request_id = a.request_id
                    JOIN analysis_v1.analysis_definitions d
                      ON d.definition_id = l.definition_id
                     AND d.version = l.definition_version
                    JOIN governance.audit_events e
                      ON e.request_id = a.request_id
                     AND e.action_code = 'ANALYSIS_ACCESS_COMPLETED'
                    JOIN context.context_packages cp
                      ON cp.request_id = a.request_id
                     AND cp.user_scope_json ->> 'entitlement_hash'
                         = e.details_json_redacted ->> 'entitlement_hash'
                    WHERE a.artifact_id = :artifact_id
                      AND a.status = 'APPROVED'
                      AND e.details_json_redacted ->> 'request_status'
                          IN ('SUCCEEDED', 'PARTIAL')
                      AND e.details_json_redacted ?& ARRAY[
                          'access_profile', 'allowed_domains', 'policy_version',
                          'entitlement_hash', 'datahub_actor', 'trino_role'
                      ]
                    ORDER BY e.created_at DESC
                    LIMIT 1
                    """
                ),
                {"artifact_id": _uuid(artifact_id, "artifact_id")},
            ).mappings().one_or_none()
        if row is None:
            from app.services.report_worker import ReportAccessBindingError

            raise ReportAccessBindingError(
                "Report block Artifact에 검증된 Context/access binding이 없습니다."
            )
        return AnalysisBinding(
            str(row["definition_id"]), row["definition_version"], row["owner_id"],
            row["actor_role"], row["question_text_redacted"], row["parameters_json"],
            row["access_profile"], tuple(row["allowed_domains"]), row["policy_version"],
            row["entitlement_hash"], row["datahub_principal"], row["trino_principal"],
        )

    def analysis_result(self, request_id: UUID) -> AnalysisReplayResult:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT a.artifact_id, a.artifact_checksum, a.evidence_json,
                           q.trino_query_id, q.source_cutoff_json
                    FROM artifact.analysis_artifacts a
                    JOIN query.query_executions q
                      ON q.query_execution_id = a.query_execution_id
                    WHERE a.request_id = :request_id AND a.status = 'APPROVED'
                    ORDER BY a.created_at DESC LIMIT 1
                    """
                ),
                {"request_id": request_id},
            ).mappings().one_or_none()
        if row is None or not row["trino_query_id"] or not row["artifact_checksum"]:
            raise KeyError("Analysis 재실행 결과 Artifact가 없습니다.")
        evidence = row["evidence_json"] or {}
        return AnalysisReplayResult(
            str(row["artifact_id"]), row["trino_query_id"], row["artifact_checksum"],
            evidence.get("context_hash", "unknown"),
            evidence.get("policy_version", "policy-v1"),
            row["source_cutoff_json"] or {},
        )

    def artifact_result(self, artifact_id: str) -> AnalysisReplayResult:
        with self._engine.connect() as connection:
            request_id = connection.execute(
                text("SELECT request_id FROM artifact.analysis_artifacts WHERE artifact_id = :artifact_id"),
                {"artifact_id": _uuid(artifact_id, "artifact_id")},
            ).scalar_one_or_none()
        if request_id is None:
            raise KeyError("Report block Artifact를 찾을 수 없습니다.")
        return self.analysis_result(request_id)

    def complete(self, command: ReportCommand, run: ReportRun) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO report_v1.report_runs
                        (run_id, definition_id, definition_version, as_of,
                         policy_version, context_hash, watermark, status)
                    VALUES (:run_id, :definition_id, :version, :as_of,
                            :policy_version, :context_hash, CAST(:watermark AS jsonb), :status)
                    """
                ),
                {
                    "run_id": _uuid(run.run_id, "run_id"),
                    "definition_id": _uuid(run.definition_id, "definition_id"),
                    "version": run.definition_version,
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
                                :checksum, :status)
                        """
                    ),
                    {
                        "run_id": _uuid(run.run_id, "run_id"),
                        "block_id": _uuid(block.block_id, "block_id"),
                        "artifact_id": _uuid(block.artifact_id, "artifact_id"),
                        "query_id": block.query_id,
                        "checksum": block.snapshot_checksum,
                        "status": block.status.value,
                    },
                )
            result = connection.execute(
                text(
                    """
                    UPDATE report_v1.report_manual_run_commands
                    SET status = :status, run_id = :run_id, completed_at = now()
                    WHERE command_id = :command_id AND status = 'running'
                    """
                ),
                {"status": run.status.value, "run_id": _uuid(run.run_id, "run_id"), "command_id": _uuid(command.command_id, "command_id")},
            )
            if result.rowcount != 1:
                raise ValueError("claim된 Report command만 완료할 수 있습니다.")

    def fail(self, command_id: str, message: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE report_v1.report_manual_run_commands
                    SET status = 'failed', completed_at = now(),
                        error_message_redacted = :message
                    WHERE command_id = :command_id AND status = 'running'
                    """
                ),
                {"command_id": _uuid(command_id, "command_id"), "message": message[:500]},
            )
