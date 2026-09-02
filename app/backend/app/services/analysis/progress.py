"""분석 요청의 실시간 진행 상태, 스레드 안전 취소(Cancellation), TTL 캐시 레지스트리 모듈.

[핵심 목적]
동시 다발적으로 유입되는 분석 요청의:
1. 단계별(Stage) 진행 상황 및 트레이스 기록
2. 사용자 소유권(User Ownership) 기반의 안전한 진행률 조회 및 취소(Cancel) 제어
3. 완료된 요청에 대한 TTL(기본 900초) 기반 자동 메모리 청소(Pruning)
를 스레드 락(`threading.Lock`) 하에서 안전하게 관리합니다.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event, Lock
from time import monotonic
from uuid import UUID

from app.contracts import AnalysisStatus, PipelineStage, Role, StageOutcome


def _get_monotonic() -> float:
    shim = sys.modules.get("app.services.analysis_progress")
    func = getattr(shim, "monotonic", monotonic) if shim else monotonic
    return func()


@dataclass
class _ActiveAnalysis:
    """활성 상태의 분석 요청 정보를 보존하는 내부 데이터 클래스."""

    trace_id: str
    user_id: UUID
    role: Role
    request_id: UUID
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_clock: float = field(default_factory=_get_monotonic)
    trace: list[dict[str, str]] = field(default_factory=list)
    agent_tasks: list[dict[str, str]] = field(default_factory=list)
    cancel: Event = field(default_factory=Event)
    status: AnalysisStatus = AnalysisStatus.RECEIVED
    completed_clock: float | None = None


class AmbiguousTraceError(LookupError):
    """동일한 trace_id에 대해 사용자의 활성 요청이 2개 이상 존재하여 식별이 모호할 때 발생하는 예외."""


class AnalysisProgressRegistry:
    """분석 진행 상태를 메모리 상에서 원자적으로 추적 및 관리하는 레지스트리 클래스."""

    def __init__(self, *, max_entries: int = 200, terminal_ttl_seconds: float = 900) -> None:
        if max_entries < 1 or terminal_ttl_seconds <= 0:
            raise ValueError("레지스트리 용량과 TTL은 양수여야 합니다.")
        self._lock = Lock()
        self._active: dict[UUID, _ActiveAnalysis] = {}
        self._trace_index: dict[str, list[UUID]] = {}
        self._max_entries = max_entries
        self._terminal_ttl_seconds = terminal_ttl_seconds

    def start(self, trace_id: str, user_id: UUID, role: Role, request_id: UUID) -> None:
        """신규 분석 요청을 레지스트리에 등록합니다."""
        with self._lock:
            self._prune()
            existing = self._active.get(request_id)
            if existing is not None:
                if (
                    existing.trace_id != trace_id
                    or existing.user_id != user_id
                    or existing.role != role
                ):
                    raise ValueError("같은 요청 ID의 진행 상태 소유권이 일치하지 않습니다.")
                return
            while len(self._active) >= self._max_entries:
                self._evict_oldest()
            self._active[request_id] = _ActiveAnalysis(
                trace_id,
                user_id,
                role,
                request_id,
            )
            self._trace_index.setdefault(trace_id, []).append(request_id)

    def start_agent_plan(
        self,
        trace_id: str,
        user_id: UUID,
        role: Role,
        request_id: UUID,
        tasks: tuple[tuple[str, str], ...],
    ) -> None:
        """검증된 Supervisor 계획의 Agent와 작업 목적을 진행 상태에 결속한다."""

        allowed_agents = {
            "ANALYSIS_WORKFLOW",
            "INTERNAL_GUIDELINE",
            "ML_PREDICTION",
        }
        if (
            not 2 <= len(tasks) <= 3
            or len({agent for agent, _ in tasks}) != len(tasks)
            or any(
                agent not in allowed_agents
                or not isinstance(objective, str)
                or not 1 <= len(objective.strip()) <= 240
                for agent, objective in tasks
            )
        ):
            raise ValueError("Supervisor Agent 진행 계획이 올바르지 않습니다.")
        self.start(trace_id, user_id, role, request_id)
        with self._lock:
            item = self._active[request_id]
            item.agent_tasks = [
                {
                    "agent": agent,
                    "objective": objective.strip(),
                    "status": "PENDING",
                }
                for agent, objective in tasks
            ]

    def record_agent(self, request_id: UUID, agent: str, status: str) -> None:
        """Supervisor 계획에 있는 Agent 하나의 실제 실행 상태를 갱신한다."""

        if status not in {"RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"}:
            raise ValueError("Agent 진행 상태가 올바르지 않습니다.")
        with self._lock:
            item = self._active.get(request_id)
            if item is None:
                return
            task = next(
                (candidate for candidate in item.agent_tasks if candidate["agent"] == agent),
                None,
            )
            if task is None:
                raise ValueError("Supervisor 계획에 없는 Agent 상태입니다.")
            task["status"] = status
            if item.status not in _TERMINAL_STATUSES:
                item.status = AnalysisStatus.ROUTED

    def record(
        self,
        request_id: UUID,
        stage: PipelineStage,
        outcome: StageOutcome = StageOutcome.PASSED,
    ) -> None:
        """파이프라인 특정 단계의 완료 상태를 기록합니다."""
        with self._lock:
            item = self._active.get(request_id)
            if item is not None:
                item.status = AnalysisStatus.ROUTED
                item.trace.append({"stage": stage.value, "outcome": outcome.value})

    def finish(self, request_id: UUID, status: AnalysisStatus) -> None:
        """요청의 최종 완료 상태(SUCCEEDED, FAILED 등)를 기록하고 TTL 타이머를 시작합니다."""
        with self._lock:
            item = self._active.get(request_id)
            if item is not None:
                item.status = status
                if status in _TERMINAL_STATUSES:
                    item.completed_clock = _get_monotonic()

    def cancel(self, trace_id: str, user_id: UUID) -> dict[str, object]:
        """trace_id를 기반으로 사용자 소유의 분석 요청에 취소 이벤트를 설정합니다."""
        with self._lock:
            item = self._owned_trace(trace_id, user_id)
            return self._cancel(item)

    def cancel_request(self, request_id: UUID, user_id: UUID) -> dict[str, object]:
        """request_id를 기반으로 사용자 소유의 분석 요청에 취소 이벤트를 설정합니다."""
        with self._lock:
            return self._cancel(self._owned_request(request_id, user_id))

    def cancelled(self, request_id: UUID) -> bool:
        """해당 요청에 취소 요청이 인입되었는지 확인합니다."""
        with self._lock:
            item = self._active.get(request_id)
            return bool(item and item.cancel.is_set())

    def get(self, trace_id: str, user_id: UUID) -> dict[str, object]:
        """trace_id로 진행 상황 스냅샷을 조회합니다."""
        with self._lock:
            item = self._owned_trace(trace_id, user_id)
            return self._snapshot(item)

    def get_request(self, request_id: UUID, user_id: UUID) -> dict[str, object]:
        """request_id로 진행 상황 스냅샷을 조회합니다."""
        with self._lock:
            return self._snapshot(self._owned_request(request_id, user_id))

    def remove(self, request_id: UUID) -> None:
        """완료된 요청을 레지스트리에서 즉시 제거합니다."""
        with self._lock:
            self._evict(request_id)

    def _owned_request(self, request_id: UUID, user_id: UUID) -> _ActiveAnalysis:
        self._prune()
        item = self._active.get(request_id)
        if item is None or item.user_id != user_id:
            raise KeyError(request_id)
        return item

    def _owned_trace(self, trace_id: str, user_id: UUID) -> _ActiveAnalysis:
        self._prune()
        matches = [
            self._active[request_id]
            for request_id in self._trace_index.get(trace_id, ())
            if request_id in self._active
            and self._active[request_id].user_id == user_id
        ]
        if not matches:
            raise KeyError(trace_id)
        if len(matches) > 1:
            raise AmbiguousTraceError(trace_id)
        return matches[0]

    @staticmethod
    def _cancel(item: _ActiveAnalysis) -> dict[str, object]:
        if item.status in _TERMINAL_STATUSES:
            raise ValueError("이미 종료된 분석 요청은 취소할 수 없습니다.")
        item.cancel.set()
        return AnalysisProgressRegistry._snapshot(item)

    def _prune(self) -> None:
        now = _get_monotonic()
        for request_id, item in tuple(self._active.items()):
            if (
                item.status in _TERMINAL_STATUSES
                and item.completed_clock is not None
                and now - item.completed_clock >= self._terminal_ttl_seconds
            ):
                self._evict(request_id)

    def _evict_oldest(self) -> None:
        terminal = [
            (request_id, item)
            for request_id, item in self._active.items()
            if item.status in _TERMINAL_STATUSES
        ]
        candidates = terminal or list(self._active.items())
        request_id, _ = min(candidates, key=lambda pair: pair[1].started_clock)
        self._evict(request_id)

    def _evict(self, request_id: UUID) -> None:
        item = self._active.pop(request_id, None)
        if item is None:
            return
        indexed = self._trace_index.get(item.trace_id, [])
        self._trace_index[item.trace_id] = [value for value in indexed if value != request_id]
        if not self._trace_index[item.trace_id]:
            self._trace_index.pop(item.trace_id, None)

    @staticmethod
    def _snapshot(item: _ActiveAnalysis) -> dict[str, object]:
        return {
            "trace_id": item.trace_id,
            "request_id": str(item.request_id),
            "status": item.status.value,
            "started_at": item.started_at.isoformat(),
            "elapsed_seconds": round(max(0.0, _get_monotonic() - item.started_clock), 1),
            "cancel_requested": item.cancel.is_set(),
            "trace": tuple(item.trace),
            "agent_tasks": tuple(dict(task) for task in item.agent_tasks),
        }


analysis_progress = AnalysisProgressRegistry()

_TERMINAL_STATUSES = {
    AnalysisStatus.SUCCEEDED,
    AnalysisStatus.BLOCKED,
    AnalysisStatus.PARTIAL,
    AnalysisStatus.FAILED,
    AnalysisStatus.CANCELLED,
}
