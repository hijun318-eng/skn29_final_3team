"""환경 상한으로 제어되는 비동기 poller가 DB의 due schedule을 실행하며, terminal evidence가 확인된 run만 다음 시각으로 전진시킨다."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from app.adapters.report_repository import PostgresReportRepository
from app.services.report_execution import ReportExecutionService


logger = logging.getLogger("uvicorn.error")


def _enabled() -> bool:
    value = os.getenv("REPORT_SCHEDULER_ENABLED", "0").strip().lower()
    if value not in {"0", "1", "false", "true"}:
        raise RuntimeError("REPORT_SCHEDULER_ENABLED must be 0, 1, false, or true")
    return value in {"1", "true"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


class ReportScheduler:
    """DB 일정을 서버 시각으로 실행하는 단일-process polling worker."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None
        self._status = "not_required"

    @property
    def status(self) -> str:
        """polling worker의 최근 준비 상태를 읽기 전용 문자열로 반환한다.

        비활성·준비·실패 상태는 health/readiness 보고용이며, 이 값 자체가 DB 작업 성공을
        보장하지 않으므로 scheduler 실행 권한이나 완료 증거로 사용하지 않는다.
        """
        return self._status

    async def start(self, controller, execution_gate) -> None:
        """보고서 스케줄러 처리를 중복 실행 방지 조건과 함께 시작한다."""
        if not _enabled():
            self._status = "not_required"
            return
        database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "")
        if not database_url:
            self._status = "not_ready"
            raise RuntimeError("APP_RUNTIME_DATABASE_URL is required by Report scheduler")
        poll_seconds = _bounded_int("REPORT_SCHEDULER_POLL_SECONDS", 15, 1, 3600)
        batch_size = _bounded_int("REPORT_SCHEDULER_BATCH_SIZE", 50, 1, 100)
        repository = PostgresReportRepository(
            database_url,
            UUID(int=0),
            manage_all=True,
        )
        from app.services.report_execution import AnalysisDefinitionReplay

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
        """polling worker에 종료 event를 보내 현재 iteration이 끝날 때까지 기다린다.

        시작되지 않은 worker에는 멱등하게 반환한다. task 종료 후 참조와 event를 비우고
        readiness 상태를 ``not_required``로 되돌려 재시작 가능한 상태를 만든다.
        """
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
                logger.exception("Report scheduler poll failed")
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
        """한 polling 시각에 due인 schedule ID를 상한 내에서 조회하고 순차 실행한다.

        terminal ``ReportRun``이 반환된 항목만 실행 수에 포함한다. repository나 실행 오류는
        숨기지 않고 상위 worker로 전파해 scheduler 상태가 ``not_ready``로 바뀌고 로그에 남게 한다.
        """
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
