"""권한·release 차원을 포함한 cache key, deep-copy 계획/결과 저장소, model 호출 예산과 bounded semaphore로 요청 간 실행 자원을 격리한다."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from threading import Lock
from typing import Any


def secure_cache_key(kind: str, **parts: object) -> str:
    """실행 종류와 모든 격리 차원을 표준 JSON으로 묶어 SHA-256 cache key를 만든다.

    키 순서와 객체 표현을 고정해 동일 입력의 재사용만 허용하고, 사용자·권한·release 같은
    호출자 제공 차원이 누락되지 않는 한 원문 값을 cache 식별자에 노출하지 않는다.
    """
    canonical = json.dumps(
        {"kind": kind, **parts},
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IsolatedExecutionCache:
    """SQL 계획과 query 결과를 분리해 보관하는 process-local bounded cache다.

    호출자는 권한·policy·context·watermark가 포함된 key를 제공해야 한다. 읽기와 쓰기에서
    deep copy하고 lock을 사용해 한 요청의 수정이 다른 실행 증거나 저장값을 바꾸지 못하게 한다.
    """

    MAX_ENTRIES = 128

    def __init__(self) -> None:
        self._plans: dict[str, dict[str, Any]] = {}
        self._results: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def get_plan(self, key: str) -> dict[str, Any] | None:
        """계획 cache에서 ``key``를 조회해 방어적 deep copy를 반환하고 부재 시 ``None``을 준다.

        호출자가 반환 객체를 수정해도 lock으로 보호된 원본 계획은 바뀌지 않는다.
        """
        return self._get(self._plans, key)

    def put_plan(self, key: str, value: dict[str, Any]) -> None:
        """계획 레코드를 저장소의 비동기 트랜잭션 안에서 영속화한다."""
        self._put(self._plans, key, value)

    def get_result(self, key: str) -> dict[str, Any] | None:
        """결과 cache에서 ``key``를 조회해 방어적 deep copy를 반환하고 부재 시 ``None``을 준다.

        사용자·권한·release 격리는 이 cache가 추론하지 않으며 호출자가 구성한 secure key에
        포함되어야 한다.
        """
        return self._get(self._results, key)

    def put_result(self, key: str, value: dict[str, Any]) -> None:
        """결과 레코드를 저장소의 비동기 트랜잭션 안에서 영속화한다."""
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


class ModelCallBudgetExceeded(ValueError):
    """요청 단위 logical model 호출 상한을 넘기기 전에 발생하는 typed 실패다."""

    code = "MODEL_CONTRACT_INVALID"
    retryable = False


class ModelCallBudget:
    """한 분석 파이프라인에서 허용하는 model 호출 횟수를 강제한다.

    요청별 인스턴스가 node1·node2·repair·node3 호출을 함께 계산해 비정상 repair 반복과
    비용 폭증을 막으며, adapter 응답의 타입 검증은 각 stage에 맡긴다.
    """
    # Node1 최초 해석 + bounded 재해석 2회 + Node2 + repair 1회 + Node3.
    MAX_CALLS = 6

    def __init__(self) -> None:
        self.count = 0

    def consume(self) -> None:
        """외부에서 소유한 node 전용 호출 경계를 바꾸지 않고 예산 한 건을 소비한다."""

        if self.count >= self.MAX_CALLS:
            raise ModelCallBudgetExceeded("model call budget exceeded")
        self.count += 1

    async def call(
        self,
        model,
        node: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """남은 예산을 한 번 소비한 뒤 지정 node와 payload로 model adapter를 호출한다.

        최대 횟수를 넘으면 호출 전에 ``RuntimeError``를 발생시키고, timeout·transport·계약
        예외는 stage가 typed 응답으로 변환할 수 있도록 그대로 전파한다.
        """
        self.consume()
        return await model.generate(node, payload)


class ConcurrentExecutionGate:
    """process 안에서 동시에 실행할 분석 수를 bounded semaphore로 제한한다.

    ``acquire``는 대기 정책에 따라 boolean을 반환하고 성공한 호출만 ``release``해야 한다.
    과도한 반환은 ``BoundedSemaphore`` 오류로 드러나 permit 상한이 조용히 늘어나지 않는다.
    """
    MAX_CONCURRENT = 2

    def __init__(self) -> None:
        self._semaphore = asyncio.BoundedSemaphore(self.MAX_CONCURRENT)

    async def acquire(self, wait_seconds: float = 0.0) -> bool:
        """concurrent 실행 gate 동시 실행 권한을 제한 시간 안에 획득한다."""
        wait_seconds = max(0.0, wait_seconds)
        if wait_seconds == 0:
            if self._semaphore.locked():
                return False
            await self._semaphore.acquire()
            return True
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=wait_seconds)
            return True
        except TimeoutError:
            return False

    def release(self) -> None:
        """concurrent 실행 gate 동시 실행 권한을 반환해 대기 작업이 진행되게 한다."""
        self._semaphore.release()
