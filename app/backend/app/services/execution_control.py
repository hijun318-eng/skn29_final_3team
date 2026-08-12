from __future__ import annotations

import copy
import hashlib
import json
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Any


def secure_cache_key(kind: str, **parts: object) -> str:
    canonical = json.dumps(
        {"kind": kind, **parts},
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IsolatedExecutionCache:
    """Keep short-lived SQL plans and 24-hour results in separate stores."""

    MAX_ENTRIES = 128
    PLAN_TTL_SECONDS = 60 * 60
    RESULT_TTL_SECONDS = 24 * 60 * 60

    def __init__(self, clock=monotonic) -> None:
        self._plans: dict[str, tuple[float, dict[str, Any]]] = {}
        self._results: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = Lock()
        self._clock = clock

    def get_plan(self, key: str) -> dict[str, Any] | None:
        return self._get(self._plans, key)

    def put_plan(self, key: str, value: dict[str, Any]) -> None:
        self._put(self._plans, key, value, self.PLAN_TTL_SECONDS)

    def get_result(self, key: str) -> dict[str, Any] | None:
        return self._get(self._results, key)

    def put_result(self, key: str, value: dict[str, Any]) -> None:
        self._put(self._results, key, value, self.RESULT_TTL_SECONDS)

    def _get(
        self, store: dict[str, tuple[float, dict[str, Any]]], key: str
    ) -> dict[str, Any] | None:
        with self._lock:
            item = store.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= self._clock():
                del store[key]
                return None
            return copy.deepcopy(value)

    def _put(
        self,
        store: dict[str, tuple[float, dict[str, Any]]],
        key: str,
        value: dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        with self._lock:
            now = self._clock()
            for expired in [name for name, item in store.items() if item[0] <= now]:
                del store[expired]
            if len(store) >= self.MAX_ENTRIES:
                store.pop(next(iter(store)))
            store[key] = (now + ttl_seconds, copy.deepcopy(value))


class ModelCallBudget:
    MAX_CALLS = 4

    def __init__(self) -> None:
        self.count = 0

    def call(self, model, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.count >= self.MAX_CALLS:
            raise RuntimeError("model call budget exceeded")
        self.count += 1
        return model.generate(node, payload)


class ConcurrentExecutionGate:
    MAX_CONCURRENT = 2

    def __init__(self) -> None:
        self._semaphore = BoundedSemaphore(self.MAX_CONCURRENT)

    def acquire(self, wait_seconds: float = 0.0) -> bool:
        return self._semaphore.acquire(timeout=max(0.0, wait_seconds))

    def release(self) -> None:
        self._semaphore.release()
