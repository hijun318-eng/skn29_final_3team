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


def test_composite_agent_plan_preserves_real_objectives_across_analysis_start():
    registry = AnalysisProgressRegistry()
    owner = UUID("00000000-0000-0000-0000-000000000001")
    request_id = UUID("00000000-0000-0000-0000-000000000003")
    tasks = (
        ("INTERNAL_GUIDELINE", "관련 내부 운영 보고서를 검색한다."),
        ("ML_PREDICTION", "GRAND 호텔의 7일 객실 수요를 예측한다."),
        ("ANALYSIS_WORKFLOW", "8월 호텔별 총 운영 매출을 비교한다."),
    )

    registry.start_agent_plan(
        "composite-trace",
        owner,
        Role.ANALYST,
        request_id,
        tasks,
    )
    registry.record_agent(request_id, "INTERNAL_GUIDELINE", "RUNNING")
    registry.record_agent(request_id, "INTERNAL_GUIDELINE", "SUCCEEDED")
    registry.record_agent(request_id, "ML_PREDICTION", "RUNNING")

    # 대표 Analysis Agent가 같은 요청으로 progress를 시작해도 Supervisor 계획은 유지된다.
    registry.start("composite-trace", owner, Role.ANALYST, request_id)
    snapshot = registry.get_request(request_id, owner)
    assert snapshot["agent_tasks"] == (
        {
            "agent": "INTERNAL_GUIDELINE",
            "objective": "관련 내부 운영 보고서를 검색한다.",
            "status": "SUCCEEDED",
        },
        {
            "agent": "ML_PREDICTION",
            "objective": "GRAND 호텔의 7일 객실 수요를 예측한다.",
            "status": "RUNNING",
        },
        {
            "agent": "ANALYSIS_WORKFLOW",
            "objective": "8월 호텔별 총 운영 매출을 비교한다.",
            "status": "PENDING",
        },
    )

    registry.finish(request_id, AnalysisStatus.SUCCEEDED)
    registry.record_agent(request_id, "ML_PREDICTION", "SUCCEEDED")
    assert registry.get_request(request_id, owner)["status"] == "SUCCEEDED"


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
