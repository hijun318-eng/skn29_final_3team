from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from app.adapters.report_repository import PostgresReportRepository


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
        return self._status

    async def start(self) -> None:
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
        self._stop = asyncio.Event()
        self._status = "starting"
        self._task = asyncio.create_task(
            self._run(repository, poll_seconds, batch_size),
            name="report-scheduler",
        )

    async def stop(self) -> None:
        if self._task is None or self._stop is None:
            return
        self._stop.set()
        await self._task
        self._task = None
        self._stop = None
        self._status = "not_required"

    async def _run(
        self,
        repository: PostgresReportRepository,
        poll_seconds: int,
        batch_size: int,
    ) -> None:
        assert self._stop is not None
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(
                    self.run_once,
                    repository,
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
    def run_once(
        repository: PostgresReportRepository,
        now: datetime,
        batch_size: int = 50,
    ) -> int:
        schedule_ids = repository.list_due_schedule_ids(now, limit=batch_size)
        executed = 0
        for schedule_id in schedule_ids:
            schedule, run = repository.run_due_schedule(schedule_id, now)
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
