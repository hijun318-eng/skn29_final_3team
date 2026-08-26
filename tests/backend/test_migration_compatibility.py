from __future__ import annotations

import asyncio
import os
import selectors
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND))

from app.adapters.admin_account_repository import (  # noqa: E402
    AdminAccountRepository,
    LastActiveAdminConflict,
)
from app.contracts import CONTRACT_VERSION, RequestContext, Role  # noqa: E402
KNOWN_REVISIONS = (
    "20260729_01",
    "20260730_02",
    "20260731_03",
    "20260804_04",
    "20260804_05",
    "20260810_06",
    "20260811_07",
    "20260812_08",
    "20260812_09",
    "20260812_10",
    "20260812_11",
    "20260812_12",
    "20260813_13",
    "20260813_14",
    "20260813_15",
    "20260813_16",
    "20260813_17",
    "20260813_18",
    "20260814_19",
    "20260814_20",
    "20260814_21",
    "20260814_22",
    "20260814_23",
    "20260816_24",
    "20260816_25",
    "20260819_26",
    "20260820_27",
    "20260820_28",
    "20260825_29",
    "20260826_30",
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
        self.assertEqual(["20260826_30"], script.get_heads())
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

    def test_percent_encoded_credentials_are_valid_migration_configuration(self) -> None:
        result = alembic(
            "upgrade",
            "20260729_01",
            "--sql",
            database_url="postgresql+psycopg://migration:p%21ss@localhost/example",
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


class IsolatedPostgresUpgradeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        configured = os.getenv("MIGRATION_TEST_DATABASE_URL")
        if not configured:
            raise unittest.SkipTest("MIGRATION_TEST_DATABASE_URL is not configured")
        cls.base_url = make_url(configured)
        cls.databases: set[str] = set()
        suffix = uuid4().hex[:8]
        cls.empty_database = f"migration_empty_{suffix}"
        cls.known_database = f"migration_known_{suffix}"
        cls.databases.update({cls.empty_database, cls.known_database})
        admin = create_engine(
            cls.base_url.set(database="postgres"),
            isolation_level="AUTOCOMMIT",
        )
        with admin.connect() as connection:
            connection.exec_driver_sql(f"CREATE DATABASE {cls.empty_database}")
            connection.exec_driver_sql(f"CREATE DATABASE {cls.known_database}")
        admin.dispose()

    @classmethod
    def tearDownClass(cls) -> None:
        admin = create_engine(
            cls.base_url.set(database="postgres"),
            isolation_level="AUTOCOMMIT",
        )
        try:
            with admin.connect() as connection:
                for database in sorted(cls.databases):
                    connection.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) "
                            "FROM pg_stat_activity "
                            "WHERE datname = :database AND pid <> pg_backend_pid()"
                        ),
                        {"database": database},
                    )
                    connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database}"')
        finally:
            admin.dispose()

    @classmethod
    def create_database(cls, prefix: str) -> str:
        database = f"{prefix}_{uuid4().hex[:8]}"
        cls.databases.add(database)
        admin = create_engine(
            cls.base_url.set(database="postgres"),
            isolation_level="AUTOCOMMIT",
        )
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
        admin.dispose()
        return database

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
        self.assertEqual("20260826_30", self.revision(self.empty_database))
        engine = create_engine(self.base_url.set(database=self.empty_database))
        with engine.connect() as connection:
            widths = connection.execute(
                text(
                    "SELECT column_name, character_maximum_length "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'chat' "
                    "AND table_name = 'analysis_state_transitions' "
                    "AND column_name IN ('from_status', 'to_status')"
                )
            ).all()
            multi_turn_tables = connection.execute(
                text(
                    "SELECT table_schema, table_name "
                    "FROM information_schema.tables "
                    "WHERE (table_schema, table_name) IN "
                    "(('artifact', 'view_specs'), "
                    "('chat', 'turn_commands'), ('chat', 'turns'))"
                )
            ).all()
            conversation_columns = connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'chat' AND table_name = 'conversations' "
                    "AND column_name IN "
                    "('head_turn_id', 'turn_count', 'active_command_id', 'lease_expires_at')"
                )
            ).scalars().all()
        engine.dispose()
        self.assertEqual({("from_status", 32), ("to_status", 32)}, set(widths))
        self.assertEqual(
            {
                ("artifact", "view_specs"),
                ("chat", "turn_commands"),
                ("chat", "turns"),
            },
            set(multi_turn_tables),
        )
        self.assertEqual(
            {"active_command_id", "head_turn_id", "lease_expires_at", "turn_count"},
            set(conversation_columns),
        )

    def test_known_20260731_revision_upgrades_to_single_head(self) -> None:
        url = self.base_url.set(database=self.known_database).render_as_string(
            hide_password=False
        )

        known = alembic("upgrade", "20260731_03", database_url=url)
        self.assertEqual(0, known.returncode, known.stdout + known.stderr)
        self.assertEqual("20260731_03", self.revision(self.known_database))
        head = alembic("upgrade", "head", database_url=url)

        self.assertEqual(0, head.returncode, head.stdout + head.stderr)
        self.assertEqual("20260826_30", self.revision(self.known_database))

    def test_report_head_upgrades_to_analysis_persistence_head(self) -> None:
        database = self.create_database("migration_report")
        url = self.base_url.set(database=database).render_as_string(hide_password=False)
        report_head = alembic("upgrade", "20260804_05", database_url=url)
        self.assertEqual(0, report_head.returncode, report_head.stdout + report_head.stderr)

        head = alembic("upgrade", "head", database_url=url)

        self.assertEqual(0, head.returncode, head.stdout + head.stderr)
        self.assertEqual("20260826_30", self.revision(database))

    def test_analysis_head_roundtrips_through_context_registry_and_run_parameters(self) -> None:
        database = self.create_database("migration_context")
        url = self.base_url.set(database=database).render_as_string(hide_password=False)
        known = alembic("upgrade", "20260810_06", database_url=url)
        self.assertEqual(0, known.returncode, known.stdout + known.stderr)

        upgrade = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, upgrade.returncode, upgrade.stdout + upgrade.stderr)
        self.assertEqual("20260826_30", self.revision(database))
        downgrade = alembic("downgrade", "20260810_06", database_url=url)
        self.assertEqual(0, downgrade.returncode, downgrade.stdout + downgrade.stderr)
        self.assertEqual("20260810_06", self.revision(database))
        second_upgrade = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, second_upgrade.returncode, second_upgrade.stdout + second_upgrade.stderr)
        self.assertEqual("20260826_30", self.revision(database))

    def test_two_role_head_enforces_accounts_tools_and_append_only_audit(self) -> None:
        database = self.create_database("migration_two_role")
        url = self.base_url.set(database=database).render_as_string(hide_password=False)
        upgraded = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, upgraded.returncode, upgraded.stdout + upgraded.stderr)

        engine = create_engine(self.base_url.set(database=database))
        with engine.connect() as connection:
            account_columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'security' AND table_name = 'accounts'"
                    )
                ).scalars()
            )
            constraints = set(
                connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conname IN ("
                        "'ck_accounts_deactivated_state', "
                        "'fk_auth_sessions_account', "
                        "'ck_tool_registry_required_roles')"
                    )
                ).scalars()
            )
            triggers = set(
                connection.execute(
                    text(
                        "SELECT trigger_name FROM information_schema.triggers "
                        "WHERE event_object_schema = 'governance' "
                        "AND event_object_table = 'audit_events'"
                    )
                ).scalars()
            )
        self.assertIn("deactivated_at", account_columns)
        self.assertEqual(
            {
                "ck_accounts_deactivated_state",
                "fk_auth_sessions_account",
                "ck_tool_registry_required_roles",
            },
            constraints,
        )
        self.assertIn("audit_events_append_only", triggers)

        with engine.connect() as connection:
            with self.assertRaises(IntegrityError):
                connection.execute(
                    text(
                        "UPDATE tooling.tool_registry "
                        "SET required_roles_json = '[\"platform_admin\"]'::jsonb"
                    )
                )
                connection.commit()
            connection.rollback()

        with engine.begin() as connection:
            event_id = connection.execute(
                text(
                    "INSERT INTO governance.audit_events ("
                    "actor_role, action_code, object_type, object_id, "
                    "details_json_redacted) VALUES ("
                    "'admin', 'MIGRATION.TEST', 'MIGRATION', 'two-role', '{}'::jsonb"
                    ") RETURNING audit_event_id"
                )
            ).scalar_one()
        with engine.connect() as connection:
            with self.assertRaises(DBAPIError):
                connection.execute(
                    text(
                        "UPDATE governance.audit_events SET object_id = 'mutated' "
                        "WHERE audit_event_id = :event_id"
                    ),
                    {"event_id": event_id},
                )
                connection.commit()
            connection.rollback()
        engine.dispose()

    def test_two_concurrent_admin_demotions_serialize_without_deadlock(self) -> None:
        database = self.create_database("migration_admin_race")
        sync_url = self.base_url.set(database=database)
        rendered = sync_url.render_as_string(hide_password=False)
        upgraded = alembic("upgrade", "head", database_url=rendered)
        self.assertEqual(0, upgraded.returncode, upgraded.stdout + upgraded.stderr)

        first, second = uuid4(), uuid4()
        engine = create_engine(sync_url)
        with engine.begin() as connection:
            for subject, username in ((first, "admin-one"), (second, "admin-two")):
                connection.execute(
                    text(
                        "INSERT INTO security.accounts ("
                        "subject, username, password_salt, password_hash, "
                        "password_iterations, role, active) VALUES ("
                        ":subject, :username, :salt, :digest, 210000, 'admin', true)"
                    ),
                    {
                        "subject": subject,
                        "username": username,
                        "salt": "A" * 22,
                        "digest": "0" * 64,
                    },
                )
        engine.dispose()

        async def exercise() -> list[str]:
            async_engine = create_async_engine(
                sync_url.set(drivername="postgresql+psycopg")
            )
            factory = async_sessionmaker(async_engine, expire_on_commit=False)
            gate = asyncio.Event()
            actor = RequestContext(
                user_id=first,
                role=Role.ADMIN,
                as_of=date(2026, 8, 26),
                contract_version=CONTRACT_VERSION,
            )

            async def demote(subject) -> str:
                await gate.wait()
                try:
                    async with factory.begin() as session:
                        await AdminAccountRepository(session).update_account(
                            subject,
                            changes={"role": Role.ANALYST},
                            actor=actor,
                        )
                    return "updated"
                except LastActiveAdminConflict:
                    return "protected"

            tasks = [
                asyncio.create_task(demote(first)),
                asyncio.create_task(demote(second)),
            ]
            gate.set()
            try:
                return list(await asyncio.wait_for(asyncio.gather(*tasks), timeout=10))
            finally:
                await async_engine.dispose()

        if sys.platform == "win32":
            loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
            try:
                outcomes = loop.run_until_complete(exercise())
            finally:
                loop.close()
        else:
            outcomes = asyncio.run(exercise())
        self.assertEqual(["protected", "updated"], sorted(outcomes))

        engine = create_engine(sync_url)
        with engine.connect() as connection:
            remaining = connection.execute(
                text(
                    "SELECT count(*) FROM security.accounts "
                    "WHERE role = 'admin' AND active AND deleted_at IS NULL"
                )
            ).scalar_one()
        engine.dispose()
        self.assertEqual(1, remaining)


if __name__ == "__main__":
    unittest.main()
