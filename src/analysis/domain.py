"""원본 분석 산출물을 변경하지 않는 사용자별 보관 lifecycle 값 객체다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AnalysisArtifactLifecycle:
    """한 사용자에게 귀속된 Analysis Artifact의 현재 보관 상태를 표현한다.

    ``artifact.analysis_artifacts.status``는 승인·증거 상태이므로 보관 여부와 섞지 않는다.
    보관 시각과 actor는 항상 함께 존재하며, 복원된 산출물은 둘 다 ``None``이다.
    """

    artifact_id: str
    archived_at: datetime | None = None
    archived_by: str | None = None

    def __post_init__(self) -> None:
        try:
            canonical_artifact_id = str(UUID(self.artifact_id))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("Analysis Artifact ID는 UUID 형식이어야 합니다.") from error
        object.__setattr__(self, "artifact_id", canonical_artifact_id)

        if (self.archived_at is None) != (self.archived_by is None):
            raise ValueError("Analysis Artifact 보관 시각과 actor는 함께 있어야 합니다.")
        if self.archived_at is not None:
            if self.archived_at.tzinfo is None or self.archived_at.utcoffset() is None:
                raise ValueError("Analysis Artifact 보관 시각에는 timezone이 필요합니다.")
            try:
                canonical_actor = str(UUID(str(self.archived_by)))
            except (TypeError, ValueError, AttributeError) as error:
                raise ValueError("Analysis Artifact 보관 actor는 UUID 형식이어야 합니다.") from error
            object.__setattr__(self, "archived_by", canonical_actor)

    @property
    def archived(self) -> bool:
        """현재 보관함에 있으면 ``True``를 반환한다."""

        return self.archived_at is not None
