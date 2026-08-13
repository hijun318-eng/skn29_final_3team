from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event, Lock
from time import monotonic
from uuid import UUID

from app.contracts import AnalysisStatus, PipelineStage, Role, StageOutcome


@dataclass
class _ActiveAnalysis:
    user_id: UUID
    role: Role
    request_id: UUID
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_clock: float = field(default_factory=monotonic)
    trace: list[dict[str, str]] = field(default_factory=list)
    cancel: Event = field(default_factory=Event)
    status: AnalysisStatus = AnalysisStatus.RECEIVED


class AnalysisProgressRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active: dict[str, _ActiveAnalysis] = {}

    def start(self, trace_id: str, user_id: UUID, role: Role, request_id: UUID) -> None:
        with self._lock:
            if len(self._active) >= 200:
                terminal = {
                    AnalysisStatus.SUCCEEDED,
                    AnalysisStatus.BLOCKED,
                    AnalysisStatus.PARTIAL,
                    AnalysisStatus.FAILED,
                    AnalysisStatus.CANCELLED,
                }
                stale = next(
                    (key for key, value in self._active.items() if value.status in terminal),
                    next(iter(self._active)),
                )
                self._active.pop(stale, None)
            self._active[trace_id] = _ActiveAnalysis(user_id, role, request_id)

    def record(
        self,
        trace_id: str,
        stage: PipelineStage,
        outcome: StageOutcome = StageOutcome.PASSED,
    ) -> None:
        with self._lock:
            item = self._active.get(trace_id)
            if item is not None:
                item.status = AnalysisStatus.ROUTED
                item.trace.append({"stage": stage.value, "outcome": outcome.value})

    def finish(self, trace_id: str, status: AnalysisStatus) -> None:
        with self._lock:
            item = self._active.get(trace_id)
            if item is not None:
                item.status = status

    def cancel(self, trace_id: str, user_id: UUID) -> dict[str, object]:
        with self._lock:
            item = self._owned(trace_id, user_id)
            if item.status in {
                AnalysisStatus.SUCCEEDED,
                AnalysisStatus.BLOCKED,
                AnalysisStatus.PARTIAL,
                AnalysisStatus.FAILED,
                AnalysisStatus.CANCELLED,
            }:
                raise ValueError("analysis is already terminal")
            item.cancel.set()
            return self._snapshot(trace_id, item)

    def cancelled(self, trace_id: str) -> bool:
        with self._lock:
            item = self._active.get(trace_id)
            return bool(item and item.cancel.is_set())

    def get(self, trace_id: str, user_id: UUID) -> dict[str, object]:
        with self._lock:
            return self._snapshot(trace_id, self._owned(trace_id, user_id))

    def remove(self, trace_id: str) -> None:
        with self._lock:
            self._active.pop(trace_id, None)

    def _owned(self, trace_id: str, user_id: UUID) -> _ActiveAnalysis:
        item = self._active.get(trace_id)
        if item is None or item.user_id != user_id:
            raise KeyError(trace_id)
        return item

    @staticmethod
    def _snapshot(trace_id: str, item: _ActiveAnalysis) -> dict[str, object]:
        return {
            "trace_id": trace_id,
            "request_id": str(item.request_id),
            "status": item.status.value,
            "started_at": item.started_at.isoformat(),
            "elapsed_seconds": round(max(0.0, monotonic() - item.started_clock), 1),
            "cancel_requested": item.cancel.is_set(),
            "trace": tuple(item.trace),
        }


analysis_progress = AnalysisProgressRegistry()
