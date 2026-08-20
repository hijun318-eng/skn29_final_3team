from pathlib import Path
from sys import path
from uuid import UUID
from unittest.mock import patch

import pytest


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.contracts import AnalysisStatus, PipelineStage, Role, StageOutcome
from app.services.analysis.progress import AmbiguousTraceError, AnalysisProgressRegistry


def test_progress_is_owner_scoped_and_preserves_cancelled_terminal_state():
    registry = AnalysisProgressRegistry()
    owner = UUID("00000000-0000-0000-0000-000000000001")
    other = UUID("00000000-0000-0000-0000-000000000002")
    request_id = UUID("00000000-0000-0000-0000-000000000003")

    registry.start("progress-trace", owner, Role.ANALYST, request_id)
    registry.record(request_id, PipelineStage.ROUTER, StageOutcome.PASSED)

    with pytest.raises(KeyError):
        registry.get("progress-trace", other)

    cancelled = registry.cancel("progress-trace", owner)
    assert cancelled["cancel_requested"] is True
    assert registry.cancelled(request_id) is True
    assert cancelled["trace"] == ({"stage": "ROUTER", "outcome": "PASSED"},)

    registry.finish(request_id, AnalysisStatus.CANCELLED)
    terminal = registry.get("progress-trace", owner)
    assert terminal["status"] == "CANCELLED"
    assert terminal["request_id"] == str(request_id)
    with pytest.raises(ValueError):
        registry.cancel("progress-trace", owner)


def test_same_trace_never_overwrites_server_owned_requests():
    registry = AnalysisProgressRegistry()
    owner = UUID("00000000-0000-0000-0000-000000000001")
    first = UUID("00000000-0000-0000-0000-000000000003")
    second = UUID("00000000-0000-0000-0000-000000000004")

    registry.start("shared-correlation", owner, Role.ANALYST, first)
    registry.start("shared-correlation", owner, Role.ANALYST, second)
    registry.record(first, PipelineStage.ROUTER)
    registry.record(second, PipelineStage.CONTEXT)

    assert registry.get_request(first, owner)["trace"] == (
        {"stage": "ROUTER", "outcome": "PASSED"},
    )
    assert registry.get_request(second, owner)["trace"] == (
        {"stage": "CONTEXT", "outcome": "PASSED"},
    )
    with pytest.raises(AmbiguousTraceError):
        registry.get("shared-correlation", owner)


def test_progress_registry_enforces_size_bound_without_cross_request_mutation():
    registry = AnalysisProgressRegistry(max_entries=1)
    owner = UUID("00000000-0000-0000-0000-000000000001")
    first = UUID("00000000-0000-0000-0000-000000000003")
    second = UUID("00000000-0000-0000-0000-000000000004")

    registry.start("first", owner, Role.ANALYST, first)
    registry.finish(first, AnalysisStatus.SUCCEEDED)
    registry.start("second", owner, Role.ANALYST, second)

    with pytest.raises(KeyError):
        registry.get_request(first, owner)
    assert registry.get_request(second, owner)["request_id"] == str(second)


def test_terminal_progress_expires_from_completion_not_start_time():
    registry = AnalysisProgressRegistry(terminal_ttl_seconds=10)
    owner = UUID("00000000-0000-0000-0000-000000000001")
    request_id = UUID("00000000-0000-0000-0000-000000000003")

    registry.start("long-running", owner, Role.ANALYST, request_id)
    registry.finish(request_id, AnalysisStatus.SUCCEEDED)
    registry._active[request_id].completed_clock = 100
    with patch("app.services.analysis.progress.monotonic", side_effect=(105, 105, 111)):
        assert registry.get_request(request_id, owner)["status"] == "SUCCEEDED"
        with pytest.raises(KeyError):
            registry.get_request(request_id, owner)
