"""Analysis Artifact 비파괴 보관 상태의 도메인·응답 불변식을 검증한다."""

from datetime import datetime, timezone
from pathlib import Path
from sys import path
from uuid import uuid4

import pytest
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.analysis_contracts import (  # noqa: E402
    AnalysisArtifactLifecycleResponse,
    AnalysisRunResponse,
)
from src.analysis.domain import AnalysisArtifactLifecycle


def test_artifact_lifecycle_requires_complete_timezone_aware_archive_receipt() -> None:
    artifact_id = uuid4()
    owner_id = uuid4()
    archived_at = datetime(2026, 8, 31, tzinfo=timezone.utc)

    archived = AnalysisArtifactLifecycle(
        str(artifact_id), archived_at, str(owner_id)
    )
    active = AnalysisArtifactLifecycle(str(artifact_id))

    assert archived.archived is True
    assert active.archived is False
    with pytest.raises(ValueError, match="함께"):
        AnalysisArtifactLifecycle(str(artifact_id), archived_at, None)
    with pytest.raises(ValueError, match="timezone"):
        AnalysisArtifactLifecycle(
            str(artifact_id), datetime(2026, 8, 31), str(owner_id)
        )


def test_artifact_lifecycle_response_rejects_inconsistent_flag_and_receipt() -> None:
    with pytest.raises(ValidationError, match="일관"):
        AnalysisArtifactLifecycleResponse(
            artifact_id=uuid4(),
            archived=True,
            archived_at=None,
            archived_by=None,
        )


def test_analysis_run_response_rejects_malformed_archive_projection() -> None:
    base = {
        "request_id": uuid4(),
        "definition_id": uuid4(),
        "definition_version": 1,
        "status": "SUCCEEDED",
        "as_of": "2026-08-31",
        "timezone": "Asia/Seoul",
        "trace_id": "archive-contract",
        "started_at": "2026-08-31T00:00:00Z",
        "question": "검증 질문",
    }
    with pytest.raises(ValidationError, match="Artifact가 없는"):
        AnalysisRunResponse.model_validate(
            {
                **base,
                "artifact_archived": True,
                "artifact_archived_at": "2026-08-31T01:00:00Z",
                "artifact_archived_by": str(uuid4()),
            }
        )
    with pytest.raises(ValidationError, match="receipt"):
        AnalysisRunResponse.model_validate(
            {
                **base,
                "artifact_id": str(uuid4()),
                "artifact_archived": True,
                "artifact_archived_at": "2026-08-31T01:00:00Z",
                "artifact_archived_by": None,
            }
        )
