"""보고서 run의 생성·완료·실패와 source query lineage를 최신순 조회 계약으로 영속화한다."""

from __future__ import annotations

from dataclasses import replace
import json

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.adapters.report_repository_common import _uuid
from src.report.domain import (
    BlockFailureCode,
    BlockRunStatus,
    ReportBlockRun,
    ReportRun,
    RunStatus,
)


class ReportRunRepositoryMixin:
    """승인 definition에 대한 Report run과 block lineage를 한 transaction으로 저장한다.

    run 생성과 조회에는 소유자 또는 ``manage_all`` scope를 적용하며, block 조회는 저장된
    definition version의 배치에 속한 항목만 복원한다. 중복 run ID와 비승인 definition은
    ``ValueError``로 거부한다.
    """
    async def add_run(self, run: ReportRun) -> ReportRun:
        """실행 레코드를 저장소의 비동기 트랜잭션 안에서 영속화한다."""
        run_id = _uuid(run.run_id, "run_id")
        definition_id = _uuid(run.definition_id, "definition_id")
        try:
            async with self._sessionmaker.begin() as session:
                approved = (await session.execute(
                    text(
                        """
                        SELECT v.product_release_id, v.permission_snapshot_id,
                               v.semantic_release_id
                        FROM report_v1.report_definition_versions v
                        JOIN report_v1.report_definitions d USING (definition_id)
                        WHERE v.definition_id = :definition_id
                          AND v.version = :version AND v.status = 'approved'
                          AND d.archived_at IS NULL
                          AND (:manage_all OR d.owner_id = :owner_id)
                        FOR KEY SHARE OF d
                        """
                    ),
                    {
                        **self._scope_params(),
                        "definition_id": definition_id,
                        "version": run.definition_version,
                    },
                )).mappings().one_or_none()
                if approved is None:
                    raise ValueError("승인된 Report definition version만 실행할 수 있습니다.")
                definition_receipt_values = (
                    approved["product_release_id"],
                    approved["permission_snapshot_id"],
                    approved["semantic_release_id"],
                )
                if any(definition_receipt_values) and not all(definition_receipt_values):
                    raise ValueError("Stored Report definition receipt is incomplete")
                definition_receipt = (
                    tuple(str(value) for value in definition_receipt_values)
                    if all(definition_receipt_values)
                    else None
                )
                supplied_receipt = (
                    run.product_release_id,
                    run.permission_snapshot_id,
                    run.semantic_release_id,
                )
                if any(supplied_receipt) and not all(supplied_receipt):
                    raise ValueError("Report run release receipt must be complete")
                if all(supplied_receipt):
                    supplied_receipt = tuple(str(value) for value in supplied_receipt)
                    if supplied_receipt != definition_receipt:
                        raise ValueError(
                            "Report run release receipt does not match its definition"
                        )
                receipt = definition_receipt
                if receipt is None:
                    current_receipt = await self._resolve_report_receipt(
                        session, (None, None, None)
                    )
                    if current_receipt is not None:
                        raise ValueError("Legacy Report definition has no release receipt")
                await session.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_runs
                            (run_id, definition_id, definition_version, as_of,
                             policy_version, context_hash, watermark, status,
                             product_release_id, permission_snapshot_id,
                             semantic_release_id)
                        VALUES (:run_id, :definition_id, :definition_version, :as_of,
                                :policy_version, :context_hash,
                                CAST(:watermark AS jsonb), :status,
                                :product_release_id, :permission_snapshot_id,
                                :semantic_release_id)
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
                        "product_release_id": receipt[0] if receipt else None,
                        "permission_snapshot_id": receipt[1] if receipt else None,
                        "semantic_release_id": receipt[2] if receipt else None,
                    },
                )
                for block in run.blocks:
                    await session.execute(
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
                await self._bind_report_receipt(
                    session,
                    object_id=f"run:{run_id}",
                    receipt=receipt,
                )
        except IntegrityError as error:
            raise ValueError("같은 Report run_id를 다시 저장할 수 없습니다.") from error
        if receipt is None:
            return run
        return replace(
            run,
            product_release_id=receipt[0],
            permission_snapshot_id=receipt[1],
            semantic_release_id=receipt[2],
        )

    async def list_runs(self, definition_id: str | None = None) -> tuple[ReportRun, ...]:
        """owner scope의 run ID를 선택적 definition UUID로 좁혀 생성 순서대로 복원한다."""
        parameters = self._scope_params()
        filter_sql = ""
        if definition_id is not None:
            parameters["definition_id"] = _uuid(definition_id, "definition_id")
            filter_sql = "AND r.definition_id = :definition_id"
        async with self._sessionmaker() as session:
            run_ids = (await session.execute(
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
            )).scalars().all()
        return tuple([await self.get_run(str(run_id)) for run_id in run_ids])

    async def get_run(self, run_id: str) -> ReportRun:
        """접근 가능한 run과 definition 배치 순의 block 실행 lineage를 반환한다.

        run에는 policy·context hash·watermark와 block별 artifact/query/checksum 또는 실패 근거가
        포함된다. UUID 오류는 ``ValueError``이고 누락·비소유 run은 동일한 ``KeyError``다.
        """
        run_uuid = _uuid(run_id, "run_id")
        async with self._sessionmaker() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT r.run_id, r.definition_id, r.definition_version, r.as_of,
                           r.policy_version, r.context_hash, r.watermark, r.status,
                           r.product_release_id, r.permission_snapshot_id,
                           r.semantic_release_id
                    FROM report_v1.report_runs r
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE r.run_id = :run_id
                      AND (:manage_all OR d.owner_id = :owner_id)
                    """
                ),
                {**self._scope_params(), "run_id": run_uuid},
            )).mappings().one_or_none()
            if row is None:
                raise KeyError("Report run을 찾을 수 없습니다.")
            blocks = (await session.execute(
                text(
                    """
                    SELECT br.block_id, br.artifact_id, br.query_id,
                           br.snapshot_checksum, br.status, br.request_id,
                           br.failure_code, br.failure_message
                    FROM report_v1.report_block_runs br
                    JOIN report_v1.report_blocks b
                      ON b.definition_id = :definition_id
                     AND b.definition_version = :definition_version
                     AND b.block_id = br.block_id
                    WHERE br.run_id = :run_id
                    ORDER BY b.y, b.x, b.block_id
                    """
                ),
                {
                    "run_id": run_uuid,
                    "definition_id": row["definition_id"],
                    "definition_version": row["definition_version"],
                },
            )).mappings()
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
                product_release_id=row["product_release_id"],
                permission_snapshot_id=row["permission_snapshot_id"],
                semantic_release_id=row["semantic_release_id"],
            )
