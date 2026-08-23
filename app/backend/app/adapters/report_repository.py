"""definition·artifact·document·run·schedule 저장 기능을 owner-scoped PostgreSQL repository로 조립한다."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.report_artifact_repository import ReportArtifactRepositoryMixin
from app.adapters.report_definition_repository import ReportDefinitionRepositoryMixin
from app.adapters.report_document_repository import PostgresReportDocumentRepositoryMixin
from app.adapters.report_execution_repository import ReportExecutionRepositoryMixin
from app.adapters.report_repository_common import _advance_schedule
from app.adapters.report_run_repository import ReportRunRepositoryMixin
from app.adapters.report_schedule_repository import ReportScheduleRepositoryMixin
from app.database import get_sessionmaker


class PostgresReportRepository(
    ReportDefinitionRepositoryMixin,
    ReportRunRepositoryMixin,
    ReportExecutionRepositoryMixin,
    ReportArtifactRepositoryMixin,
    ReportScheduleRepositoryMixin,
    PostgresReportDocumentRepositoryMixin,
):
    """PostgresReportRepository는 소유자 범위의 PostgreSQL 보고서 저장소 레코드를 비동기 트랜잭션 안에서 저장하고 조회한다.

    Owner-scoped Report repository backed by the process-wide async pool.
    """

    def __init__(
        self,
        database_url: str,
        owner_id: UUID,
        *,
        manage_all: bool = False,
        product_release_id: str | None = None,
        permission_snapshot_id: str | None = None,
        semantic_release_id: str | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        configured_receipt = (
            product_release_id,
            permission_snapshot_id,
            semantic_release_id,
        )
        if (product_release_id or semantic_release_id) and not all(configured_receipt):
            raise ValueError("Report repository release receipt must be complete")
        self._sessionmaker = session_factory or get_sessionmaker(database_url)
        self._owner_id = owner_id
        self._manage_all = manage_all
        self._product_release_id = product_release_id
        self._permission_snapshot_id = permission_snapshot_id
        self._semantic_release_id = semantic_release_id

    async def _resolve_report_receipt(
        self,
        session: AsyncSession,
        supplied: tuple[str | None, str | None, str | None],
    ) -> tuple[str, str, str] | None:
        """명시 receipt 또는 active projection receipt를 검증해 보고서 write에 고정한다."""

        async def active_receipt() -> tuple[str, str, str]:
            active = (await session.execute(
                text(
                    """
                    SELECT pointer.product_release_id,
                           manifest.release_vector_json->>'semantic_release_id'
                               AS semantic_release_id
                    FROM governance.runtime_catalog_active_pointer pointer
                    JOIN governance.runtime_catalog_projections projection
                      ON projection.projection_id = pointer.projection_id
                    JOIN governance.product_release_manifests manifest
                      ON manifest.product_release_id = pointer.product_release_id
                     AND manifest.catalog_release_id = projection.catalog_release_id
                     AND manifest.catalog_projection_sha256 = projection.projection_sha256
                    WHERE pointer.pointer_name = 'analysis'
                    """
                )
            )).one_or_none()
            if active is None or not active[1]:
                raise ValueError("Active Report product release receipt is unavailable")
            return (
                str(active[0]),
                str(self._permission_snapshot_id),
                str(active[1]),
            )

        if any(supplied) and not all(supplied):
            raise ValueError("Report release receipt must be complete")
        if all(supplied):
            receipt = tuple(str(value) for value in supplied)
            configured = (
                self._product_release_id,
                self._permission_snapshot_id,
                self._semantic_release_id,
            )
            if all(configured) and receipt != tuple(str(value) for value in configured):
                raise ValueError("Report release receipt differs from request admission")
            if self._permission_snapshot_id and not self._product_release_id:
                if receipt != await active_receipt():
                    raise ValueError("Report release receipt is not active")
        elif all(
            (
                self._product_release_id,
                self._permission_snapshot_id,
                self._semantic_release_id,
            )
        ):
            receipt = (
                str(self._product_release_id),
                str(self._permission_snapshot_id),
                str(self._semantic_release_id),
            )
        elif self._permission_snapshot_id:
            receipt = await active_receipt()
        else:
            # Migration 이전 내부 test/legacy adapter 호출은 nullable historical row로 유지한다.
            # Production composition roots는 permission snapshot을 항상 주입한다.
            return None

        if not all(value.strip() for value in receipt):
            raise ValueError("Report release receipt values must not be blank")
        valid = (await session.execute(
            text(
                """
                SELECT 1
                FROM governance.product_release_manifests
                WHERE product_release_id = :product_release_id
                  AND release_vector_json->>'semantic_release_id' = :semantic_release_id
                """
            ),
            {
                "product_release_id": receipt[0],
                "semantic_release_id": receipt[2],
            },
        )).first()
        if valid is None:
            raise ValueError("Report product and semantic release receipt do not match")
        return receipt

    @staticmethod
    async def _bind_report_receipt(
        session: AsyncSession,
        *,
        object_id: str,
        receipt: tuple[str, str, str] | None,
    ) -> None:
        """새 Report definition/run을 불변 product release evidence에 결속한다."""

        if receipt is None:
            return
        await session.execute(
            text(
                """
                INSERT INTO governance.product_release_bindings (
                    object_kind, object_id, product_release_id,
                    permission_snapshot_id, semantic_release_id,
                    capability_release_vector_json, evidence_refs_json
                ) VALUES (
                    'REPORT', :object_id, :product_release_id,
                    :permission_snapshot_id, :semantic_release_id,
                    '{"report.lifecycle":"1.0.0"}'::jsonb, '[]'::jsonb
                )
                """
            ),
            {
                "object_id": object_id,
                "product_release_id": receipt[0],
                "permission_snapshot_id": receipt[1],
                "semantic_release_id": receipt[2],
            },
        )


__all__ = ["PostgresReportRepository", "_advance_schedule"]
