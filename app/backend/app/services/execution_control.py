from __future__ import annotations

import copy
import hashlib
import json
from threading import BoundedSemaphore, Lock
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
    """Keep SQL plans and query results in separate bounded stores."""

    MAX_ENTRIES = 128

    def __init__(self) -> None:
        self._plans: dict[str, dict[str, Any]] = {}
        self._results: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def get_plan(self, key: str) -> dict[str, Any] | None:
        return self._get(self._plans, key)

    def put_plan(self, key: str, value: dict[str, Any]) -> None:
        self._put(self._plans, key, value)

    def get_result(self, key: str) -> dict[str, Any] | None:
        return self._get(self._results, key)

    def put_result(self, key: str, value: dict[str, Any]) -> None:
        self._put(self._results, key, value)

    def _get(self, store: dict[str, dict[str, Any]], key: str) -> dict[str, Any] | None:
        with self._lock:
            value = store.get(key)
            return copy.deepcopy(value) if value is not None else None

    def _put(self, store: dict[str, dict[str, Any]], key: str, value: dict[str, Any]) -> None:
        with self._lock:
            if len(store) >= self.MAX_ENTRIES:
                store.pop(next(iter(store)))
            store[key] = copy.deepcopy(value)


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
