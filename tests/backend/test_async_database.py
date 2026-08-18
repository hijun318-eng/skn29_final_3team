from __future__ import annotations

import sys
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.report_repository import PostgresReportRepository  # noqa: E402
from app.database import (  # noqa: E402
    DatabaseConfigurationError,
    dispose_database,
    get_sessionmaker,
    normalize_async_database_url,
    session_scope,
)


class _Session:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.commit_error = commit_error

    async def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self) -> None:
        self.rollbacks += 1


class _Factory:
    def __init__(self, session: _Session) -> None:
        self.session = session

    @asynccontextmanager
    async def __call__(self):
        yield self.session


class _Result:
    def __init__(self, row=None) -> None:
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


class _ReportSession:
    def __init__(self, rows) -> None:
        self.rows = iter(rows)
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, statement, parameters=None):
        self.calls.append((str(statement), dict(parameters or {})))
        return _Result(next(self.rows, None))


class _ReportFactory:
    def __init__(self, session: _ReportSession) -> None:
        self.session = session

    @asynccontextmanager
    async def begin(self):
        yield self.session

    @asynccontextmanager
    async def __call__(self):
        yield self.session


class DatabaseConfigurationTest(unittest.TestCase):
    def test_postgresql_url_uses_async_psycopg_dialect(self) -> None:
        self.assertEqual(
            normalize_async_database_url(
                "postgresql+psycopg2://user:pass@db:5432/app"
            ),
            "postgresql+psycopg://user:pass@db:5432/app",
        )
        with self.assertRaises(DatabaseConfigurationError):
            normalize_async_database_url("sqlite:///tmp.db")


class AsyncDatabaseTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await dispose_database()

    async def asyncTearDown(self) -> None:
        await dispose_database()

    async def test_process_uses_one_sessionmaker_and_rejects_second_url(self) -> None:
        first = get_sessionmaker("postgresql://user:pass@db/app")
        self.assertIs(
            get_sessionmaker("postgresql+psycopg://user:pass@db/app"), first
        )
        with self.assertRaises(DatabaseConfigurationError):
            get_sessionmaker("postgresql://user:pass@db/other")

    async def test_session_scope_commits_success_and_rolls_back_failure(self) -> None:
        successful = _Session()
        with patch("app.database.get_sessionmaker", return_value=_Factory(successful)):
            async with session_scope():
                pass
        self.assertEqual((successful.commits, successful.rollbacks), (1, 0))

        failed = _Session()
        with patch("app.database.get_sessionmaker", return_value=_Factory(failed)):
            with self.assertRaises(RuntimeError):
                async with session_scope():
                    raise RuntimeError("rollback")
        self.assertEqual((failed.commits, failed.rollbacks), (0, 1))

        commit_failed = _Session(commit_error=RuntimeError("commit"))
        with patch(
            "app.database.get_sessionmaker", return_value=_Factory(commit_failed)
        ):
            with self.assertRaises(RuntimeError):
                async with session_scope():
                    pass
        self.assertEqual((commit_failed.commits, commit_failed.rollbacks), (1, 1))

    async def test_schedule_advance_requires_matching_terminal_run(self) -> None:
        scheduled_for = datetime(2026, 8, 15, tzinfo=timezone.utc)
        schedule_id = uuid4()
        run_id = uuid4()
        schedule_row = {
            "schedule_id": schedule_id,
            "definition_id": uuid4(),
            "definition_version": 3,
            "cadence": "daily",
            "timezone_name": "Asia/Seoul",
            "next_run_at": scheduled_for,
            "enabled": True,
            "last_run_id": None,
        }
        session = _ReportSession(
            [
                {"cadence": "daily", "next_run_at": scheduled_for},
                None,
                schedule_row,
            ]
        )
        repository = PostgresReportRepository(
            "postgresql://unused/unused",
            uuid4(),
            session_factory=_ReportFactory(session),
        )

        result = await repository.complete_due_schedule(
            str(schedule_id), scheduled_for, str(run_id)
        )

        update_sql, update_parameters = session.calls[1]
        self.assertIn(
            "r.status IN ('success', 'partial', 'failed', 'cancelled')", update_sql
        )
        self.assertIn("r.definition_id = s.definition_id", update_sql)
        self.assertIn("r.definition_version = s.definition_version", update_sql)
        self.assertIn("s.next_run_at = :scheduled_for", update_sql)
        self.assertEqual(update_parameters["run_id"], run_id)
        self.assertEqual(result["schedule_id"], schedule_id)


if __name__ == "__main__":
    unittest.main()
