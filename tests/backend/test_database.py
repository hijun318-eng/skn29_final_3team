from __future__ import annotations

from pathlib import Path
from sys import path
import unittest
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.database import normalize_async_database_url, session_scope  # noqa: E402


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _Factory:
    def __init__(self, session: _Session) -> None:
        self.session = session

    def __call__(self) -> _Session:
        return self.session


class DatabaseLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def test_postgres_urls_use_psycopg_async_dialect(self) -> None:
        self.assertEqual(
            "postgresql+psycopg://user:pass@db:5432/app",
            normalize_async_database_url("postgresql://user:pass@db:5432/app"),
        )
        self.assertEqual(
            "postgresql+psycopg://user:pass@db:5432/app",
            normalize_async_database_url(
                "postgresql+psycopg://user:pass@db:5432/app"
            ),
        )

    async def test_session_scope_commits_success_and_rolls_back_failure(self) -> None:
        committed = _Session()
        with patch("app.database.get_sessionmaker", return_value=_Factory(committed)):
            async with session_scope("postgresql://unused") as session:
                self.assertIs(session, committed)
        self.assertEqual(1, committed.commits)
        self.assertEqual(0, committed.rollbacks)

        rolled_back = _Session()
        with patch("app.database.get_sessionmaker", return_value=_Factory(rolled_back)):
            with self.assertRaisesRegex(RuntimeError, "rollback"):
                async with session_scope("postgresql://unused"):
                    raise RuntimeError("rollback")
        self.assertEqual(0, rolled_back.commits)
        self.assertEqual(1, rolled_back.rollbacks)
