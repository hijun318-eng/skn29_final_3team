"""서버 실행의 사용자 소유권·trace·취소·종단 TTL을 lock으로 관리하고, 모호한 trace나 이미 끝난 취소를 명시적 예외로 거부한다."""

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
    """같은 사용자와 trace ID에 둘 이상의 서버 실행이 남아 있음을 나타낸다.

    API 계층은 어느 요청도 임의 선택하지 않고 이 예외를 충돌 응답으로 바꿔야 하며,
    이후 조회·취소는 고유한 request ID를 사용해야 한다.
    """


class AnalysisProgressRegistry:
    """request ID별 진행률과 trace ID 역색인을 lock 아래에서 단조롭게 갱신하는 메모리 레지스트리다.

    활성 요청 수와 terminal TTL을 제한하고, 같은 trace에 요청이 여럿이면 임의 요청을
    선택하지 않는다. 완료·취소 상태도 TTL 동안 조회할 수 있게 남긴 뒤 만료 순서대로
    제거하여 API가 오래된 진행률을 현재 상태로 오인하지 않게 한다.
    """
    def __init__(self, *, max_entries: int = 200, terminal_ttl_seconds: float = 900) -> None:
        if max_entries < 1 or terminal_ttl_seconds <= 0:
            raise ValueError("progress bounds must be positive")
        self._lock = Lock()
        self._active: dict[UUID, _ActiveAnalysis] = {}
        self._trace_index: dict[str, list[UUID]] = {}
        self._max_entries = max_entries
        self._terminal_ttl_seconds = terminal_ttl_seconds

    def start(self, trace_id: str, user_id: UUID, role: Role, request_id: UUID) -> None:
        """분석 진행 상태 레지스트리 처리를 중복 실행 방지 조건과 함께 시작한다."""
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
        """분석 진행 상태 레지스트리 레코드를 저장소의 비동기 트랜잭션 안에서 영속화한다."""
        with self._lock:
            item = self._active.get(request_id)
            if item is not None:
                item.status = AnalysisStatus.ROUTED
                item.trace.append({"stage": stage.value, "outcome": outcome.value})

    def finish(self, request_id: UUID, status: AnalysisStatus) -> None:
        """등록된 요청의 상태를 갱신하고 종단 상태이면 TTL 계산 시작 시각을 기록한다.

        알 수 없는 ``request_id``는 비동기 실행 종료 경합을 위해 멱등하게 무시한다. 실제
        제거는 TTL pruning이 담당하므로 완료 직후에도 진행 trace를 조회할 수 있다.
        """
        with self._lock:
            item = self._active.get(request_id)
            if item is not None:
                item.status = status
                if status in _TERMINAL_STATUSES:
                    item.completed_clock = monotonic()

    def cancel(self, trace_id: str, user_id: UUID) -> dict[str, object]:
        """사용자에게 속한 유일한 trace 실행에 취소 event를 설정하고 현재 snapshot을 반환한다.

        소유 실행이 없으면 ``KeyError``, 같은 trace가 둘 이상이면 ``AmbiguousTraceError``,
        이미 종단 상태이면 ``ValueError``를 발생시켜 임의 실행을 취소하지 않는다.
        """
        with self._lock:
            item = self._owned_trace(trace_id, user_id)
            return self._cancel(item)

    def cancel_request(self, request_id: UUID, user_id: UUID) -> dict[str, object]:
        """요청 ID와 사용자 소유권을 확인한 뒤 해당 실행의 취소 event를 설정한다.

        요청 부재·타 사용자 요청은 ``KeyError``로 동일하게 감추고, 종단 요청은
        ``ValueError``로 거부한다. 반환값은 취소 요청이 반영된 불변 snapshot이다.
        """
        with self._lock:
            return self._cancel(self._owned_request(request_id, user_id))

    def cancelled(self, request_id: UUID) -> bool:
        """서버가 보유한 요청의 취소 이벤트가 설정됐는지 lock 안에서 조회한다.

        등록되지 않은 요청은 취소되지 않은 것으로 반환하며, 소유권 검사는 호출 전에
        끝났다는 내부 파이프라인 계약을 전제로 외부 식별자 조회에는 사용하지 않는다.
        """
        with self._lock:
            item = self._active.get(request_id)
            return bool(item and item.cancel.is_set())

    def get(self, trace_id: str, user_id: UUID) -> dict[str, object]:
        """만료 항목을 정리한 뒤 사용자에게 속한 유일한 trace 실행의 snapshot을 반환한다.

        일치 항목이 없으면 ``KeyError``를, trace 재사용으로 둘 이상이면
        ``AmbiguousTraceError``를 발생시켜 진행 상태가 다른 요청에 잘못 연결되지 않게 한다.
        """
        with self._lock:
            item = self._owned_trace(trace_id, user_id)
            return self._snapshot(item)

    def get_request(self, request_id: UUID, user_id: UUID) -> dict[str, object]:
        """만료 정리 후 요청 ID와 사용자 소유권이 모두 일치하는 진행 snapshot을 반환한다.

        존재하지 않거나 다른 사용자에게 속한 요청은 모두 ``KeyError``로 처리해 요청 ID를
        통한 소유 자원 열거를 막는다.
        """
        with self._lock:
            return self._snapshot(self._owned_request(request_id, user_id))

    def remove(self, request_id: UUID) -> None:
        """완료된 요청과 trace 역색인을 하나의 lock 구간에서 함께 제거한다.

        존재하지 않는 ID는 멱등하게 무시하며, 두 인덱스를 동시에 정리해 만료된 요청이
        trace 조회나 새 요청의 상한 계산에 남는 것을 방지한다.
        """
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
