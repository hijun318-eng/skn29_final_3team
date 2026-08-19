"""백그라운드 비동기 보고서 스케줄러(ReportScheduler) 모듈.

[핵심 목적]
주기적으로 데이터베이스를 폴링하여 실행 시점이 도래한(`due`) 보고서 스케줄을 감지하고,
`ReportExecutionService`를 통해 멱등 실행 및 다음 실행 예정 시각 갱신(`CAS`)을 수행합니다.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from app.adapters.report_repository import PostgresReportRepository
from app.services.report.execution import AnalysisDefinitionReplay, ReportExecutionService

logger = logging.getLogger("uvicorn.error")


def _enabled() -> bool:
    value = os.getenv("REPORT_SCHEDULER_ENABLED", "0").strip().lower()
    if value not in {"0", "1", "false", "true"}:
        raise RuntimeError("REPORT_SCHEDULER_ENABLED 환경변수는 0, 1, false, true 중 하나여야 합니다.")
    return value in {"1", "true"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} 은 정수여야 합니다.") from error
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} 은 {minimum}과 {maximum} 사이의 값이어야 합니다.")
    return value


class ReportScheduler:
    """백그라운드에서 예약된 보고서 일정을 감지하고 실행하는 비동기 워커 클래스."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None
        self._status = "not_required"

    @property
    def status(self) -> str:
        """워커의 최근 준비/실행 상태를 반환합니다."""
        return self._status

    async def start(self, controller, execution_gate) -> None:
        """스케줄러 백그라운드 태스크를 시작합니다."""
        if not _enabled():
            self._status = "not_required"
            return
        database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "")
        if not database_url:
            self._status = "not_ready"
            raise RuntimeError("Report 스케줄러 실행을 위해 APP_RUNTIME_DATABASE_URL이 필요합니다.")
        poll_seconds = _bounded_int("REPORT_SCHEDULER_POLL_SECONDS", 15, 1, 3600)
        batch_size = _bounded_int("REPORT_SCHEDULER_BATCH_SIZE", 50, 1, 100)
        repository = PostgresReportRepository(
            database_url,
            UUID(int=0),
            manage_all=True,
        )

        execution_service = ReportExecutionService(
            repository,
            AnalysisDefinitionReplay(
                database_url,
                controller,
                execution_gate,
                queue_wait_seconds=float(
                    os.getenv("ANALYSIS_QUEUE_WAIT_SECONDS", "0")
                ),
            ),
        )
        self._stop = asyncio.Event()
        self._status = "starting"
        self._task = asyncio.create_task(
            self._run(execution_service, poll_seconds, batch_size),
            name="report-scheduler",
        )

    async def stop(self) -> None:
        """실행 중인 스케줄러 태스크에 종료 신호를 보내고 정상 종료될 때까지 대기합니다."""
        if self._task is None or self._stop is None:
            return
        self._stop.set()
        await self._task
        self._task = None
        self._stop = None
        self._status = "not_required"

    async def _run(
        self,
        execution_service: ReportExecutionService,
        poll_seconds: int,
        batch_size: int,
    ) -> None:
        assert self._stop is not None
        while not self._stop.is_set():
            try:
                await self.run_once(
                    execution_service,
                    datetime.now(timezone.utc),
                    batch_size,
                )
                self._status = "ready"
            except Exception:
                self._status = "not_ready"
                logger.exception("보고서 스케줄러 폴링 실행 중 오류가 발생했습니다.")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=poll_seconds)
            except TimeoutError:
                pass

    @staticmethod
    async def run_once(
        execution_service: ReportExecutionService,
        now: datetime,
        batch_size: int = 50,
    ) -> int:
        """도래한 스케줄 목록을 조회하여 1회 폴링 배치를 실행합니다."""
        schedule_ids = await execution_service.repository.list_due_schedule_ids(
            now, limit=batch_size
        )
        executed = 0
        for schedule_id in schedule_ids:
            schedule, run = await execution_service.run_due_schedule(schedule_id, now)
            if run is None:
                continue
            executed += 1
            logger.info(
                "Report schedule executed schedule_id=%s run_id=%s status=%s next_run_at=%s",
                schedule_id,
                run.run_id,
                run.status.value,
                schedule["next_run_at"],
            )
        return executed


report_scheduler = ReportScheduler()
