from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event, Lock
from time import monotonic
from uuid import UUID

from app.contracts import AnalysisStatus, PipelineStage, Role, StageOutcome


@dataclass
class _ActiveAnalysis:
    trace_id: str
    user_id: UUID
    role: Role
    request_id: UUID
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_clock: float = field(default_factory=monotonic)
    trace: list[dict[str, str]] = field(default_factory=list)
    cancel: Event = field(default_factory=Event)
    status: AnalysisStatus = AnalysisStatus.RECEIVED
    completed_clock: float | None = None


class AmbiguousTraceError(LookupError):
    """A correlation id matched more than one server-owned execution."""


class AnalysisProgressRegistry:
    def __init__(self, *, max_entries: int = 200, terminal_ttl_seconds: float = 900) -> None:
        if max_entries < 1 or terminal_ttl_seconds <= 0:
            raise ValueError("progress bounds must be positive")
        self._lock = Lock()
        self._active: dict[UUID, _ActiveAnalysis] = {}
        self._trace_index: dict[str, list[UUID]] = {}
        self._max_entries = max_entries
        self._terminal_ttl_seconds = terminal_ttl_seconds

    def start(self, trace_id: str, user_id: UUID, role: Role, request_id: UUID) -> None:
        with self._lock:
            self._prune()
            while len(self._active) >= self._max_entries:
                self._evict_oldest()
            self._active[request_id] = _ActiveAnalysis(
                trace_id,
                user_id,
                role,
                request_id,
            )
            self._trace_index.setdefault(trace_id, []).append(request_id)

    def record(
        self,
        request_id: UUID,
        stage: PipelineStage,
        outcome: StageOutcome = StageOutcome.PASSED,
    ) -> None:
        with self._lock:
            item = self._active.get(request_id)
            if item is not None:
                item.status = AnalysisStatus.ROUTED
                item.trace.append({"stage": stage.value, "outcome": outcome.value})

    def finish(self, request_id: UUID, status: AnalysisStatus) -> None:
        with self._lock:
            item = self._active.get(request_id)
            if item is not None:
                item.status = status
                if status in _TERMINAL_STATUSES:
                    item.completed_clock = monotonic()

    def cancel(self, trace_id: str, user_id: UUID) -> dict[str, object]:
        with self._lock:
            item = self._owned_trace(trace_id, user_id)
            return self._cancel(item)

    def cancel_request(self, request_id: UUID, user_id: UUID) -> dict[str, object]:
        with self._lock:
            return self._cancel(self._owned_request(request_id, user_id))

    def cancelled(self, request_id: UUID) -> bool:
        with self._lock:
            item = self._active.get(request_id)
            return bool(item and item.cancel.is_set())

    def get(self, trace_id: str, user_id: UUID) -> dict[str, object]:
        with self._lock:
            item = self._owned_trace(trace_id, user_id)
            return self._snapshot(item)

    def get_request(self, request_id: UUID, user_id: UUID) -> dict[str, object]:
        with self._lock:
            return self._snapshot(self._owned_request(request_id, user_id))

    def remove(self, request_id: UUID) -> None:
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
        if item.status in {
            AnalysisStatus.SUCCEEDED,
            AnalysisStatus.BLOCKED,
            AnalysisStatus.PARTIAL,
            AnalysisStatus.FAILED,
            AnalysisStatus.CANCELLED,
        }:
            raise ValueError("analysis is already terminal")
        item.cancel.set()
        return AnalysisProgressRegistry._snapshot(item)

    def _prune(self) -> None:
        now = monotonic()
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
            "elapsed_seconds": round(max(0.0, monotonic() - item.started_clock), 1),
            "cancel_requested": item.cancel.is_set(),
            "trace": tuple(item.trace),
        }


analysis_progress = AnalysisProgressRegistry()


_TERMINAL_STATUSES = {
    AnalysisStatus.SUCCEEDED,
    AnalysisStatus.BLOCKED,
    AnalysisStatus.PARTIAL,
    AnalysisStatus.FAILED,
    AnalysisStatus.CANCELLED,
}
