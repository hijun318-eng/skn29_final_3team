"""actor·tool별 최근 호출 시각을 추적해 단일 프로세스 MCP 도구 호출량을 제한한다."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable


class ProcessToolRateLimiter:
    """단일 프로세스 도구 호출량을 제한하며 다중 인스턴스에서는 외부 저장소로 교체한다."""

    def __init__(
        self,
        maximum_calls: int = 30,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if maximum_calls < 1 or window_seconds <= 0:
            raise ValueError("Rate limit values must be positive")
        self._maximum_calls = maximum_calls
        self._window_seconds = window_seconds
        self._clock = clock
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, actor_id: str, tool_code: str) -> bool:
        """윈도우 밖 기록을 제거하고 한도 미만 호출만 기록·허용하며 초과 호출은 거부한다."""

        now = self._clock()
        key = (actor_id, tool_code)
        with self._lock:
            events = self._events[key]
            threshold = now - self._window_seconds
            while events and events[0] <= threshold:
                events.popleft()
            if len(events) >= self._maximum_calls:
                return False
            events.append(now)
            return True
