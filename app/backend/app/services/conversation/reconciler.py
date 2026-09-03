"""만료 Conversation command/run과 orphan Trino query를 bounded 방식으로 복구한다."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.adapters.conversation_repository import ConversationRepository
from app.database import get_sessionmaker
from app.ports.data_platform import DataPlatformAdapter


logger = logging.getLogger("uvicorn.error")


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name}은 정수여야 합니다.") from error
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name}은 {minimum}~{maximum} 범위여야 합니다.")
    return value


class ConversationReconciler:
    """[책임] 원격 Trino 고아 쿼리를 안전하게 취소하고 DB의 만료된 stale 대화 명령을 원자적으로 종결한다.
    - 입출력: 만료 기준 시각 수신 → 원격 취소 확인 후 DB 터미널 상태로 전이된 레코드 수 통계 반환
    - 주의조건: Trino 원격 취소 실패 시 DB 상태를 성공으로 가장하지 않고 즉시 예외를 발생시켜 fail-closed
    """

    def __init__(
        self,
        repository: ConversationRepository,
        data_platform: DataPlatformAdapter,
        *,
        stale_seconds: int = 120,
        batch_limit: int = 100,
    ) -> None:
        """[책임] 고아 쿼리 취소 및 좀비 상태 대화 명령 복구를 위한 조정자 인스턴스를 초기화한다.
        - 입출력: ConversationRepository, DataPlatformAdapter, 만료 시간(초), 배치 한도 수신 → 설정 보관
        - 주의조건: stale_seconds(1~86400) 및 batch_limit(1~1000) 범위를 벗어날 경우 ValueError 발생
        """
        if not 1 <= stale_seconds <= 86_400:
            raise ValueError("stale_seconds는 1~86400이어야 합니다.")
        if not 1 <= batch_limit <= 1_000:
            raise ValueError("batch_limit은 1~1000이어야 합니다.")
        self._repository = repository
        self._data_platform = data_platform
        self._stale_seconds = stale_seconds
        self._batch_limit = batch_limit

    async def run_once(self, *, now: datetime | None = None) -> dict[str, int]:
        """[책임] 만료된 Trino 쿼리를 원격 취소하고 DB의 stale 대화 명령을 단일 트랜잭션으로 종결한다.
        - 입출력: 기준 시각 now 수신 → 취소 및 종결 처리된 레코드 수 통계 딕셔너리 반환
        - 주의조건: Trino 원격 쿼리 취소 실패 시 DB 상태를 종결하지 않고 예외를 전파하여 일관성 유지
        """
        current = now or datetime.now(timezone.utc)
        stale_before = current - timedelta(seconds=self._stale_seconds)
        orphan_queries = await self._repository.list_orphan_queries(
            stale_before=stale_before,
            limit=self._batch_limit,
        )
        cancelled: list[UUID] = []
        cancel_query_at = getattr(self._data_platform, "cancel_query_at", None)
        if orphan_queries and not callable(cancel_query_at):
            raise RuntimeError("data platform이 durable query cancellation을 지원하지 않습니다.")
        for query in orphan_queries:
            trino_query_id = query.get("trino_query_id")
            if not isinstance(trino_query_id, str) or not trino_query_id:
                raise RuntimeError("orphan RUNNING query에 Trino query ID가 없습니다.")
            cancel_uri = query.get("trino_cancel_uri")
            if not isinstance(cancel_uri, str) or not cancel_uri:
                raise RuntimeError("orphan RUNNING query에 durable cancel URI가 없습니다.")
            result: dict[str, Any] = await cancel_query_at(
                trino_query_id,
                cancel_uri,
            )
            if str(result.get("status")) not in {"CANCELLED", "FINISHED", "NOT_FOUND"}:
                raise RuntimeError("orphan Trino query cancellation이 terminal 상태가 아닙니다.")
            cancelled.append(UUID(str(query["query_execution_id"])))
        return await self._repository.reconcile_stale(
            stale_before=stale_before,
            cancelled_query_execution_ids=tuple(cancelled),
            limit=self._batch_limit,
        )


class ConversationRecoveryWorker:
    """[책임] 애플리케이션 백그라운드에서 주기적으로 stale 대화 복구 루프를 실행하는 워커.
    - 입출력: DataPlatformAdapter 수신 → 주기적 타이머 기반으로 ConversationReconciler.run_once 실행
    - 주의조건: 프로세스 종료 신호(stop event) 수신 시 진행 중인 복구 작업을 안전하게 drain 후 종료
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None
        self._status = "not_required"

    @property
    def status(self) -> str:
        """최근 recovery batch가 나타내는 process readiness 상태를 반환한다."""

        return self._status

    async def start(self, data_platform: DataPlatformAdapter) -> None:
        """[책임] 백그라운드 태스크로 주기적인 stale recovery 루프를 구동한다.
        - 입출력: DataPlatformAdapter 인스턴스 수신 → 백그라운드 asyncio 루프 태스크 시작
        - 주의조건: App DB 미구성 환경(예: CI/Mock)인 경우 실행을 건너뛰고 not_required 상태 유지
        """

        database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "").strip()
        if not database_url:
            self._status = "not_required"
            return
        poll_seconds = _bounded_int(
            "CONVERSATION_RECOVERY_POLL_SECONDS",
            30,
            1,
            3600,
        )
        stale_seconds = _bounded_int(
            "CONVERSATION_RECOVERY_STALE_SECONDS",
            120,
            1,
            86400,
        )
        batch_limit = _bounded_int(
            "CONVERSATION_RECOVERY_BATCH_LIMIT",
            100,
            1,
            1000,
        )
        reconciler = ConversationReconciler(
            ConversationRepository(get_sessionmaker(database_url)),
            data_platform,
            stale_seconds=stale_seconds,
            batch_limit=batch_limit,
        )
        self._stop = asyncio.Event()
        self._status = "starting"
        self._task = asyncio.create_task(
            self._run(reconciler, poll_seconds),
            name="conversation-recovery",
        )

    async def stop(self) -> None:
        """실행 중인 recovery loop를 깨우고 종료될 때까지 기다려 자원을 정리한다."""

        if self._task is None or self._stop is None:
            return
        self._stop.set()
        await self._task
        self._task = None
        self._stop = None
        self._status = "not_required"

    async def _run(
        self,
        reconciler: ConversationReconciler,
        poll_seconds: int,
    ) -> None:
        assert self._stop is not None
        while not self._stop.is_set():
            try:
                await reconciler.run_once()
                self._status = "ready"
            except Exception:
                self._status = "not_ready"
                logger.exception("Conversation stale recovery batch failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=poll_seconds)
            except TimeoutError:
                pass


conversation_recovery_worker = ConversationRecoveryWorker()
