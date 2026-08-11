from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
KNOWN_REVISIONS = (
    "20260729_01",
    "20260730_02",
    "20260731_03",
    "20260804_04",
    "20260804_05",
)
LEGACY_REVISION_UNSUPPORTED = "LEGACY_REVISION_UNSUPPORTED"


def alembic(*arguments: str, database_url: str = "sqlite://") -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["APP_DATABASE_URL"] = database_url
    environment["APP_DB_USER"] = make_url(database_url).username or "migration_test"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


class MigrationGraphTest(unittest.TestCase):
    def test_graph_has_one_root_one_head_and_only_known_revisions(self) -> None:
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "migrations"))
        script = ScriptDirectory.from_config(config)

        self.assertEqual(["20260729_01"], script.get_bases())
        self.assertEqual(["20260804_05"], script.get_heads())
        self.assertEqual(
            set(KNOWN_REVISIONS),
            {item.revision for item in script.walk_revisions()},
        )

    def test_unknown_revision_is_native_nonzero_before_database_start(self) -> None:
        result = alembic("upgrade", "20260803_03", "--sql")

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "Can't locate revision identified by '20260803_03'",
            result.stdout + result.stderr,
        )
        self.assertEqual(LEGACY_REVISION_UNSUPPORTED, "LEGACY_REVISION_UNSUPPORTED")


class IsolatedPostgresUpgradeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        configured = os.getenv("MIGRATION_TEST_DATABASE_URL")
        if not configured:
            raise unittest.SkipTest("MIGRATION_TEST_DATABASE_URL is not configured")
        cls.base_url = make_url(configured)
        suffix = uuid4().hex[:8]
        cls.empty_database = f"migration_empty_{suffix}"
        cls.known_database = f"migration_known_{suffix}"
        admin = create_engine(
            cls.base_url.set(database="postgres"),
            isolation_level="AUTOCOMMIT",
        )
        with admin.connect() as connection:
            connection.exec_driver_sql(f"CREATE DATABASE {cls.empty_database}")
            connection.exec_driver_sql(f"CREATE DATABASE {cls.known_database}")
        admin.dispose()

    def revision(self, database: str) -> str:
        engine = create_engine(self.base_url.set(database=database))
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM governance.alembic_version")
            ).scalar_one()
        engine.dispose()
        return str(revision)

    def test_empty_database_upgrades_to_single_head(self) -> None:
        url = self.base_url.set(database=self.empty_database).render_as_string(
            hide_password=False
        )

        result = alembic("upgrade", "head", database_url=url)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("20260804_05", self.revision(self.empty_database))

    def test_known_20260731_revision_upgrades_to_single_head(self) -> None:
        url = self.base_url.set(database=self.known_database).render_as_string(
            hide_password=False
        )

        known = alembic("upgrade", "20260731_03", database_url=url)
        self.assertEqual(0, known.returncode, known.stdout + known.stderr)
        self.assertEqual("20260731_03", self.revision(self.known_database))
        head = alembic("upgrade", "head", database_url=url)

        self.assertEqual(0, head.returncode, head.stdout + head.stderr)
        self.assertEqual("20260804_05", self.revision(self.known_database))


if __name__ == "__main__":
    unittest.main()
