"""분석 정의·run 시작·조회·evidence mixin을 owner-scoped PostgreSQL 저장소로 조립한다."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.analysis_definition_repository import (
    AnalysisDefinitionRepositoryMixin,
)
from app.adapters.analysis_artifact_lifecycle_repository import (
    AnalysisArtifactLifecycleRepositoryMixin,
)
from app.adapters.analysis_evidence_repository import AnalysisEvidenceRepositoryMixin
from app.adapters.analysis_repository_common import AnalysisRepositoryUnavailable
from app.adapters.analysis_run_read_repository import AnalysisRunReadRepositoryMixin
from app.adapters.analysis_run_start_repository import AnalysisRunStartRepositoryMixin
from app.database import get_sessionmaker


class PostgresAnalysisRepository(
    AnalysisDefinitionRepositoryMixin,
    AnalysisRunStartRepositoryMixin,
    AnalysisEvidenceRepositoryMixin,
    AnalysisRunReadRepositoryMixin,
    AnalysisArtifactLifecycleRepositoryMixin,
):
    """PostgresAnalysisRepository는 소유자 범위의 PostgreSQL 분석 저장소 레코드를 비동기 트랜잭션 안에서 저장하고 조회한다.

    Persist owner-scoped analysis definitions, runs, evidence, and artifacts.
    """

    def __init__(
        self,
        database_url: str,
        owner_id: UUID,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._sessionmaker = session_factory or get_sessionmaker(database_url)
        self._owner_id = owner_id


__all__ = ["AnalysisRepositoryUnavailable", "PostgresAnalysisRepository"]
