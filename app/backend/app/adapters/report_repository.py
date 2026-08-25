"""definition·artifact·document·run·schedule 저장 기능을 owner-scoped PostgreSQL repository로 조립한다."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.report_artifact_repository import ReportArtifactRepositoryMixin
from app.adapters.report_assistant_operations_repository import ReportAssistantOperationsRepositoryMixin
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
    ReportAssistantOperationsRepositoryMixin,
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
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._sessionmaker = session_factory or get_sessionmaker(database_url)
        self._owner_id = owner_id
        self._manage_all = manage_all


__all__ = ["PostgresReportRepository", "_advance_schedule"]
