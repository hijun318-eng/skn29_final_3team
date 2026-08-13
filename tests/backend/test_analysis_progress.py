from pathlib import Path
from sys import path
from uuid import UUID

import pytest


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.contracts import AnalysisStatus, PipelineStage, Role, StageOutcome
from app.services.analysis_progress import AnalysisProgressRegistry


def test_progress_is_owner_scoped_and_preserves_cancelled_terminal_state():
    registry = AnalysisProgressRegistry()
    owner = UUID("00000000-0000-0000-0000-000000000001")
    other = UUID("00000000-0000-0000-0000-000000000002")
    request_id = UUID("00000000-0000-0000-0000-000000000003")

    registry.start("progress-trace", owner, Role.HOTEL_ANALYST, request_id)
    registry.record("progress-trace", PipelineStage.ROUTER, StageOutcome.PASSED)

    with pytest.raises(KeyError):
        registry.get("progress-trace", other)

    cancelled = registry.cancel("progress-trace", owner)
    assert cancelled["cancel_requested"] is True
    assert registry.cancelled("progress-trace") is True
    assert cancelled["trace"] == ({"stage": "ROUTER", "outcome": "PASSED"},)

    registry.finish("progress-trace", AnalysisStatus.CANCELLED)
    terminal = registry.get("progress-trace", owner)
    assert terminal["status"] == "CANCELLED"
    assert terminal["request_id"] == str(request_id)
    with pytest.raises(ValueError):
        registry.cancel("progress-trace", owner)
