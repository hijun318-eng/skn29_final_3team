from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from sys import path
import unittest
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.services.report_scheduler import ReportScheduler, _enabled  # noqa: E402
from src.report.domain import RunStatus  # noqa: E402


class _Run:
    run_id = "run-1"
    status = RunStatus.SUCCESS


class _Repository:
    def __init__(self) -> None:
        self.executed: list[tuple[str, datetime]] = []

    async def list_due_schedule_ids(self, now: datetime, *, limit: int):
        self.query = (now, limit)
        return ("schedule-1", "schedule-2")

    async def run_due_schedule(self, schedule_id: str, now: datetime):
        self.executed.append((schedule_id, now))
        if schedule_id == "schedule-2":
            return {"next_run_at": now}, None
        return {"next_run_at": now}, _Run()


class _ExecutionService:
    def __init__(self) -> None:
        self.repository = _Repository()

    async def run_due_schedule(self, schedule_id: str, now: datetime):
        return await self.repository.run_due_schedule(schedule_id, now)


class ReportSchedulerTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_uses_server_instant_and_only_counts_executed_runs(self) -> None:
        execution_service = _ExecutionService()
        now = datetime(2026, 8, 13, 9, tzinfo=timezone.utc)

        executed = await ReportScheduler.run_once(execution_service, now, 10)

        self.assertEqual(1, executed)
        self.assertEqual((now, 10), execution_service.repository.query)
        self.assertEqual(
            [("schedule-1", now), ("schedule-2", now)],
            execution_service.repository.executed,
        )

    def test_enabled_setting_is_strict(self) -> None:
        for value, expected in (("0", False), ("false", False), ("1", True), ("true", True)):
            with self.subTest(value=value), patch.dict(
                "os.environ", {"REPORT_SCHEDULER_ENABLED": value}, clear=True
            ):
                self.assertEqual(expected, _enabled())
        with patch.dict(
            "os.environ", {"REPORT_SCHEDULER_ENABLED": "sometimes"}, clear=True
        ), self.assertRaisesRegex(RuntimeError, "REPORT_SCHEDULER_ENABLED"):
            _enabled()


if __name__ == "__main__":
    unittest.main()
