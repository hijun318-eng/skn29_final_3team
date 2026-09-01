"""보고서 실행 요청의 권한 snapshot·상태·재생 lineage를 transaction 경계에서 기록한다."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import text

from app.adapters.report_repository_common import _uuid
from src.report.domain import (
    BlockFailureCode,
    BlockRunStatus,
    BlockType,
    ManualRunCommand,
    ReportBlockRun,
    ReportRun,
    RunStatus,
)


class ReportExecutionRepositoryMixin:
    """보고서 수동 실행 command와 block replay 결과를 소유자 범위에서 영속화한다.

    command claim은 row lock으로 한 run만 생성하고, block 기록과 최종 집계는 승인
    definition version에 고정된 lineage를 사용한다. ``_manage_all``이 아니면 조합 저장소의
    ``_owner_id``가 소유한 보고서만 접근한다.
    """
    async def queue_manual_run(
        self,
        definition_id: str,
        version: int,
        as_of: datetime,
        idempotency_key: str,
    ) -> ManualRunCommand:
        """수동 실행 작업을 멱등성·소유권 조건을 확인한 뒤 실행 대기 상태로 전환한다."""
        if not idempotency_key.strip():
            raise ValueError("idempotency_key는 비어 있을 수 없습니다.")
        definition_uuid = _uuid(definition_id, "definition_id")
        async with self._sessionmaker.begin() as session:
            approved = (await session.execute(
                text(
                    """
                    SELECT 1 FROM report_v1.report_definition_versions v
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE v.definition_id = :definition_id AND v.version = :version
                      AND v.status = 'approved'
                      AND d.archived_at IS NULL
                      AND (:manage_all OR d.owner_id = :owner_id)
                    FOR KEY SHARE OF d
                    """
                ),
                {
                    **self._scope_params(),
                    "definition_id": definition_uuid,
                    "version": version,
                },
            )).first()
            if approved is None:
                raise ValueError("승인된 Report definition version만 실행할 수 있습니다.")
            row = (await session.execute(
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
            )).mappings().one()
        return ManualRunCommand(
            str(row["command_id"]),
            str(row["definition_id"]),
            row["definition_version"],
            row["as_of"],
            row["idempotency_key"],
            RunStatus(row["status"]),
        )

    async def claim_manual_run(self, command_id: str) -> dict[str, object]:
        """수동 실행 작업을 멱등성·소유권 조건을 확인한 뒤 실행 대기 상태로 전환한다.

        Atomically claim a command and return immutable replay inputs.
        """
        command_uuid = _uuid(command_id, "command_id")
        async with self._sessionmaker.begin() as session:
            command = (await session.execute(
                text(
                    """
                    SELECT c.definition_id, c.definition_version, c.as_of, c.run_id,
                           c.status, d.owner_id, v.product_release_id,
                           v.permission_snapshot_id, v.semantic_release_id
                    FROM report_v1.report_manual_run_commands c
                    JOIN report_v1.report_definitions d USING (definition_id)
                    JOIN report_v1.report_definition_versions v
                      ON v.definition_id = c.definition_id
                     AND v.version = c.definition_version
                    WHERE c.command_id = :command_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                      AND d.archived_at IS NULL
                    FOR UPDATE OF c, d
                    """
                ),
                {**self._scope_params(), "command_id": command_uuid},
            )).mappings().one_or_none()
            if command is None:
                raise KeyError("Report manual run command not found")
            if command["run_id"] is not None:
                return {
                    "claimed": False,
                    "run_id": str(command["run_id"]),
                    "status": command["status"],
                    "blocks": (),
                }

            blocks = (await session.execute(
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
            )).mappings().all()
            run_id = uuid4()
            empty_watermark = json.dumps({}, sort_keys=True)
            receipt_values = (
                command["product_release_id"],
                command["permission_snapshot_id"],
                command["semantic_release_id"],
            )
            if any(receipt_values) and not all(receipt_values):
                raise ValueError("Stored Report definition receipt is incomplete")
            receipt = (
                tuple(str(value) for value in receipt_values)
                if all(receipt_values)
                else None
            )
            await session.execute(
                text(
                    """
                    INSERT INTO report_v1.report_runs
                        (run_id, definition_id, definition_version, as_of,
                         policy_version, context_hash, watermark, status,
                         product_release_id, permission_snapshot_id,
                         semantic_release_id)
                    VALUES (:run_id, :definition_id, :version, :as_of,
                            'pending', :context_hash, CAST(:watermark AS jsonb),
                            'running', :product_release_id,
                            :permission_snapshot_id, :semantic_release_id)
                    """
                ),
                {
                    "run_id": run_id,
                    "definition_id": command["definition_id"],
                    "version": command["definition_version"],
                    "as_of": command["as_of"],
                    "context_hash": hashlib.sha256(empty_watermark.encode()).hexdigest(),
                    "watermark": empty_watermark,
                    "product_release_id": receipt[0] if receipt else None,
                    "permission_snapshot_id": receipt[1] if receipt else None,
                    "semantic_release_id": receipt[2] if receipt else None,
                },
            )
            await self._bind_report_receipt(
                session,
                object_id=f"run:{run_id}",
                receipt=receipt,
            )
            await session.execute(
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
                "product_release_id": receipt[0] if receipt else None,
                "permission_snapshot_id": receipt[1] if receipt else None,
                "semantic_release_id": receipt[2] if receipt else None,
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

    async def record_block_run(
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
        """블록 실행 레코드를 저장소의 비동기 트랜잭션 안에서 영속화한다."""
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
        async with self._sessionmaker.begin() as session:
            inserted = await session.execute(
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
                existing = (await session.execute(
                    text(
                        "SELECT 1 FROM report_v1.report_block_runs "
                        "WHERE run_id = :run_id AND block_id = :block_id"
                    ),
                    {"run_id": run_uuid, "block_id": block_uuid},
                )).first()
                if existing is None:
                    raise KeyError("running Report block not found")

    async def finish_manual_run(self, command_id: str) -> ReportRun:
        """claim된 command의 모든 data block을 채운 뒤 run과 command를 함께 종결한다.

        누락 block은 ``REPLAY_UNAVAILABLE`` 실패로 기록하고 block 상태에서 terminal run
        상태·artifact watermark·policy version을 계산한다. 소유 범위 밖이거나 미claim
        command면 ``KeyError``이고, 이미 종결된 command는 저장된 run을 그대로 반환한다.
        """
        command_uuid = _uuid(command_id, "command_id")
        async with self._sessionmaker.begin() as session:
            command = (await session.execute(
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
            )).mappings().one_or_none()
            if command is None or command["run_id"] is None:
                raise KeyError("claimed Report manual run command not found")
            run_id = command["run_id"]
            if command["status"] != RunStatus.RUNNING.value:
                return await self.get_run(str(run_id))

            await session.execute(
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
            rows = (await session.execute(
                text(
                    """
                    SELECT status, artifact_id, snapshot_checksum, policy_version
                    FROM report_v1.report_block_runs
                    WHERE run_id = :run_id
                    """
                ),
                {"run_id": run_id},
            )).mappings().all()
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
            await session.execute(
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
            await session.execute(
                text(
                    """
                    UPDATE report_v1.report_manual_run_commands
                    SET status = :status
                    WHERE command_id = :command_id AND status = 'running'
                    """
                ),
                {"command_id": command_uuid, "status": run_status},
            )
        return await self.get_run(str(run_id))
