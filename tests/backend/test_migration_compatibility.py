from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
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
    "20260822_29",
    "20260822_30",
    "20260822_31",
    "20260822_32",
    "20260822_33",
    "20260823_34",
    "20260823_35",
    "20260825_36",
    "20260826_37",
    "20260826_38",
    "20260826_39",
    "20260826_40",
    "20260826_41",
    "20260826_42",
    "20260826_43",
    "20260826_44",
    "20260826_45",
    "20260826_46",
    "20260828_47",
    "20260828_48",
    "20260828_49",
    "20260828_50",
    "20260828_51",
    "20260828_52",
    "20260828_53",
    "20260828_54",
    "20260828_55",
    "20260827_41",
    "20260828_56",
    "20260829_57",
    "20260829_58",
    "20260830_59",
    "20260831_60",
    "20260831_61",
    "20260831_62",
    "20260831_63",
    "20260831_64",
)
LEGACY_REVISION_UNSUPPORTED = "LEGACY_REVISION_UNSUPPORTED"


def alembic(*arguments: str, database_url: str = "sqlite://") -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["APP_DATABASE_URL"] = database_url
    environment["APP_DB_USER"] = make_url(database_url).username or "migration_test"
    environment["APP_CATALOG_PUBLISHER_USER"] = environment["APP_DB_USER"]
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
        self.assertEqual(["20260831_64"], script.get_heads())
        self.assertEqual(
            set(KNOWN_REVISIONS),
            {item.revision for item in script.walk_revisions()},
        )

    def test_deployed_seung_head_is_a_reconciled_compatibility_ancestor(self) -> None:
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "migrations"))
        script = ScriptDirectory.from_config(config)

        legacy = script.get_revision("20260827_41")
        reconciliation = script.get_revision("20260828_56")

        self.assertIsNotNone(legacy)
        self.assertIsNotNone(reconciliation)
        self.assertEqual("20260828_55", legacy.down_revision)
        self.assertEqual("20260827_41", reconciliation.down_revision)
        self.assertEqual("20260831_64", script.get_current_head())

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


class SeungHeadReconciliationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.namespace = runpy.run_path(
            str(
                BACKEND
                / "migrations"
                / "versions"
                / "20260828_56_seung_head_reconciliation.py"
            )
        )

    def test_source_fingerprint_accepts_only_complete_legacy_or_current_state(self) -> None:
        source_state = self.namespace["_source_state"]
        states = source_state.__globals__

        with patch.dict(
            states,
            {"_schema_sentinels": lambda: {"a": lambda: False, "b": lambda: False}},
        ):
            self.assertEqual("SEUNG_LEGACY", source_state())
        with patch.dict(
            states,
            {"_schema_sentinels": lambda: {"a": lambda: True, "b": lambda: True}},
        ):
            self.assertEqual("DAESUNG_CURRENT", source_state())
        with patch.dict(
            states,
            {"_schema_sentinels": lambda: {"a": lambda: True, "b": lambda: False}},
        ):
            with self.assertRaisesRegex(
                RuntimeError, "SEUNG_DAESUNG_RECONCILIATION_AMBIGUOUS"
            ):
                source_state()

    def test_reconciliation_does_not_replay_equivalent_report_assistant_ddl(self) -> None:
        revisions = set(self.namespace["_DAESUNG_ONLY_REVISIONS"])

        self.assertNotIn("20260826_37_report_assistant_sessions", revisions)
        self.assertNotIn("20260828_54_report_page_break_blocks", revisions)
        self.assertEqual(
            {
                "20260822_29_capability_evidence_contract",
                "20260822_30_conversation_safety_foundation",
                "20260822_31_runtime_catalog_projection",
                "20260822_32_report_release_receipts",
                "20260822_33_bounded_multi_turn_focus",
                "20260823_34_phase10_runtime_query_terminal_grants",
                "20260823_35_phase10_runtime_audit_grants",
                "20260825_36_catalog_publisher_role",
                "20260826_45_runtime_context_receipts",
                "20260826_46_database_auth_accounts",
                "20260828_47_query_generation_mode_compiler",
                "20260828_48_rag_integration",
                "20260828_49_ml_prediction_audit",
                "20260828_55_admin_control_plane",
            },
            revisions,
        )


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
        self.assertEqual("20260831_64", self.revision(self.empty_database))
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
        engine.dispose()
        self.assertEqual({("from_status", 32), ("to_status", 32)}, set(widths))

    def test_known_20260731_revision_upgrades_to_single_head(self) -> None:
        url = self.base_url.set(database=self.known_database).render_as_string(
            hide_password=False
        )

        known = alembic("upgrade", "20260731_03", database_url=url)
        self.assertEqual(0, known.returncode, known.stdout + known.stderr)
        self.assertEqual("20260731_03", self.revision(self.known_database))
        head = alembic("upgrade", "head", database_url=url)

        self.assertEqual(0, head.returncode, head.stdout + head.stderr)
        self.assertEqual("20260831_64", self.revision(self.known_database))

    def test_report_head_upgrades_to_analysis_persistence_head(self) -> None:
        database = self.create_database("migration_report")
        url = self.base_url.set(database=database).render_as_string(hide_password=False)
        report_head = alembic("upgrade", "20260804_05", database_url=url)
        self.assertEqual(0, report_head.returncode, report_head.stdout + report_head.stderr)

        head = alembic("upgrade", "head", database_url=url)

        self.assertEqual(0, head.returncode, head.stdout + head.stderr)
        self.assertEqual("20260831_64", self.revision(database))

    def test_report_assistant_message_contract_roundtrips_and_replays(self) -> None:
        database = self.create_database("migration_assistant_scope")
        url = self.base_url.set(database=database).render_as_string(hide_password=False)
        previous = alembic("upgrade", "20260829_58", database_url=url)
        self.assertEqual(0, previous.returncode, previous.stdout + previous.stderr)

        upgraded = alembic("upgrade", "20260830_59", database_url=url)
        self.assertEqual(0, upgraded.returncode, upgraded.stdout + upgraded.stderr)
        self.assertEqual("20260830_59", self.revision(database))
        engine = create_engine(self.base_url.set(database=database))
        with engine.connect() as connection:
            column = connection.execute(
                text(
                    """
                    SELECT is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'report_v1'
                      AND table_name = 'report_assistant_requests'
                      AND column_name = 'operation_scope'
                    """
                )
            ).one()
            constraint = connection.execute(
                text(
                    """
                    SELECT pg_get_constraintdef(c.oid)
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = 'report_v1'
                      AND t.relname = 'report_assistant_requests'
                      AND c.conname = 'report_assistant_operation_scope_check'
                    """
                )
            ).scalar_one()
            message_column = connection.execute(
                text(
                    """
                    SELECT is_nullable, column_default, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'report_v1'
                      AND table_name = 'report_assistant_requests'
                      AND column_name = 'message_revision'
                    """
                )
            ).one()
            message_constraint = connection.execute(
                text(
                    """
                    SELECT pg_get_constraintdef(c.oid)
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = 'report_v1'
                      AND t.relname = 'report_assistant_requests'
                      AND c.conname = 'report_assistant_message_revision_check'
                    """
                )
            ).scalar_one()
        self.assertEqual("NO", column[0])
        self.assertIn("'full_report'", str(column[1]))
        self.assertIn("report_title", str(constraint))
        self.assertEqual("NO", message_column[0])
        self.assertIn("0", str(message_column[1]))
        self.assertEqual("bigint", message_column[2])
        self.assertIn("message_revision >= 0", str(message_constraint))

        downgraded = alembic("downgrade", "20260829_58", database_url=url)
        self.assertEqual(0, downgraded.returncode, downgraded.stdout + downgraded.stderr)
        with engine.connect() as connection:
            remaining = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM information_schema.columns
                    WHERE table_schema = 'report_v1'
                      AND table_name = 'report_assistant_requests'
                      AND column_name IN ('operation_scope', 'message_revision')
                    """
                )
            ).scalar_one()
        self.assertEqual(0, remaining)
        engine.dispose()

        replayed = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, replayed.returncode, replayed.stdout + replayed.stderr)
        self.assertEqual("20260831_64", self.revision(database))

    def test_rag_candidate_registers_disabled_and_roundtrips(self) -> None:
        database = self.create_database("migration_rag_candidate")
        url = self.base_url.set(database=database).render_as_string(hide_password=False)
        previous = alembic("upgrade", "20260828_47", database_url=url)
        self.assertEqual(0, previous.returncode, previous.stdout + previous.stderr)

        candidate = alembic("upgrade", "20260828_48", database_url=url)
        self.assertEqual(0, candidate.returncode, candidate.stdout + candidate.stderr)
        engine = create_engine(self.base_url.set(database=database))
        with engine.connect() as connection:
            registered = connection.execute(
                text(
                    "SELECT tool_code, semantic_version, is_enabled "
                    "FROM tooling.tool_registry "
                    "WHERE tool_id = '8edce655-e454-5b76-b56f-5e49aa2884d4'"
                )
            ).one()
        self.assertEqual(("rag.answer", "1.1.0", False), tuple(registered))

        downgraded = alembic("downgrade", "20260828_47", database_url=url)
        self.assertEqual(0, downgraded.returncode, downgraded.stdout + downgraded.stderr)
        with engine.connect() as connection:
            remaining = connection.execute(
                text(
                    "SELECT count(*) FROM tooling.tool_registry "
                    "WHERE tool_id = '8edce655-e454-5b76-b56f-5e49aa2884d4'"
                )
            ).scalar_one()
        engine.dispose()
        self.assertEqual(0, remaining)

        replayed = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, replayed.returncode, replayed.stdout + replayed.stderr)
        self.assertEqual("20260831_64", self.revision(database))

    def test_database_auth_accounts_roundtrips_from_previous_head(self) -> None:
        database = self.create_database("migration_auth_accounts")
        url = self.base_url.set(database=database).render_as_string(hide_password=False)
        previous = alembic("upgrade", "20260826_45", database_url=url)
        self.assertEqual(0, previous.returncode, previous.stdout + previous.stderr)

        upgraded = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, upgraded.returncode, upgraded.stdout + upgraded.stderr)
        engine = create_engine(self.base_url.set(database=database))
        stale_subject = "00000000-0000-0000-0000-000000000099"
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO security.auth_accounts (
                        username, password_salt, password_hash,
                        password_iterations, subject, role
                    ) VALUES (
                        'stale', :salt, :digest, 210000, :subject, 'analyst'
                    )
                    """
                ),
                {"salt": "A" * 22, "digest": "0" * 64, "subject": stale_subject},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO security.auth_sessions (
                        token_sha256, subject, role, issued_at, expires_at
                    ) VALUES (
                        :token, :subject, 'analyst', now() - interval '1 minute',
                        now() + interval '1 hour'
                    )
                    """
                ),
                {"token": "a" * 64, "subject": stale_subject},
            )
        if str(BACKEND) not in sys.path:
            sys.path.insert(0, str(BACKEND))
        from app.contracts import Role
        from app.provision_auth_accounts import AccountDefinition, _provision

        definitions = (
            AccountDefinition("analyst", Role.ANALYST, uuid4()),
            AccountDefinition("admin", Role.PLATFORM_ADMIN, uuid4()),
        )
        verifiers = {
            "analyst": ("A" * 22, "1" * 64, 210_000),
            "admin": ("B" * 22, "2" * 64, 210_000),
        }
        with patch.dict(os.environ, {"APP_DATABASE_URL": url}, clear=False):
            provisioned = _provision(definitions, verifiers, replace=True)
        self.assertEqual(2, provisioned["account_count"])
        self.assertEqual(1, provisioned["revoked_sessions"])

        with engine.connect() as connection:
            columns = connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'security'
                      AND table_name = 'auth_accounts'
                    """
                )
            ).scalars().all()
            accounts = connection.execute(
                text(
                    "SELECT username, role FROM security.auth_accounts "
                    "ORDER BY username"
                )
            ).all()
            active_sessions = connection.execute(
                text(
                    "SELECT count(*) FROM security.auth_sessions "
                    "WHERE revoked_at IS NULL"
                )
            ).scalar_one()
        self.assertEqual(
            {
                "username", "password_salt", "password_hash",
                "password_iterations", "subject", "role", "active",
                "created_at", "updated_at", "deactivated_at", "deleted_at",
            },
            set(columns),
        )
        self.assertEqual(
            [("admin", "platform_admin"), ("analyst", "analyst")],
            accounts,
        )
        self.assertEqual(0, active_sessions)
        with self.assertRaises(DBAPIError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO security.auth_accounts (
                        username, password_salt, password_hash,
                        password_iterations, subject, role
                    ) VALUES (
                        'invalid account', :salt, :digest, 210000,
                        '00000000-0000-0000-0000-000000000046', 'analyst'
                    )
                    """
                ),
                {"salt": "A" * 22, "digest": "0" * 64},
            )
        engine.dispose()

        downgraded = alembic("downgrade", "20260826_45", database_url=url)
        self.assertEqual(0, downgraded.returncode, downgraded.stdout + downgraded.stderr)
        engine = create_engine(self.base_url.set(database=database))
        with engine.connect() as connection:
            relations = connection.execute(
                text(
                    "SELECT to_regclass('security.auth_accounts'), "
                    "to_regclass('security.auth_sessions')"
                )
            ).one()
        engine.dispose()
        self.assertEqual((None, "security.auth_sessions"), tuple(relations))

        replayed = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, replayed.returncode, replayed.stdout + replayed.stderr)
        self.assertEqual("20260831_64", self.revision(database))

    def test_analysis_head_roundtrips_through_context_registry_and_run_parameters(self) -> None:
        database = self.create_database("migration_context")
        url = self.base_url.set(database=database).render_as_string(hide_password=False)
        known = alembic("upgrade", "20260810_06", database_url=url)
        self.assertEqual(0, known.returncode, known.stdout + known.stderr)

        upgrade = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, upgrade.returncode, upgrade.stdout + upgrade.stderr)
        self.assertEqual("20260831_64", self.revision(database))
        downgrade = alembic("downgrade", "20260810_06", database_url=url)
        self.assertEqual(0, downgrade.returncode, downgrade.stdout + downgrade.stderr)
        self.assertEqual("20260810_06", self.revision(database))
        engine = create_engine(self.base_url.set(database=database))
        with engine.connect() as connection:
            rolled_back = connection.execute(
                text(
                    """
                    SELECT to_regclass('chat.turns'),
                           to_regclass('chat.turn_commands'),
                           to_regclass('artifact.view_specs'),
                           to_regclass('governance.phase_20260822_30_preexisting_objects'),
                           EXISTS (
                               SELECT 1 FROM information_schema.columns
                               WHERE table_schema = 'chat'
                                 AND table_name = 'conversations'
                                 AND column_name = 'head_turn_id'
                           ),
                           EXISTS (
                               SELECT 1 FROM information_schema.columns
                               WHERE table_schema = 'query'
                                 AND table_name = 'query_executions'
                                 AND column_name = 'trino_cancel_uri'
                           )
                    """
                )
            ).one()
        engine.dispose()
        self.assertEqual((None, None, None, None, False, False), tuple(rolled_back))
        second_upgrade = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, second_upgrade.returncode, second_upgrade.stdout + second_upgrade.stderr)
        self.assertEqual("20260831_64", self.revision(database))

    def test_approved_semantic_snapshot_59_60_roundtrip_and_db_guards(self) -> None:
        database = self.create_database("migration_semantic_snapshot")
        url = self.base_url.set(database=database).render_as_string(
            hide_password=False
        )
        previous = alembic("upgrade", "20260830_59", database_url=url)
        self.assertEqual(0, previous.returncode, previous.stdout + previous.stderr)
        self.assertEqual("20260830_59", self.revision(database))
        upgraded = alembic("upgrade", "20260831_60", database_url=url)
        self.assertEqual(0, upgraded.returncode, upgraded.stdout + upgraded.stderr)
        self.assertEqual("20260831_60", self.revision(database))

        engine = create_engine(self.base_url.set(database=database))
        owner_id = uuid4()
        request_one, request_two = uuid4(), uuid4()
        query_one, query_two = uuid4(), uuid4()
        artifact_one, artifact_two = uuid4(), uuid4()
        snapshot_id = uuid4()
        product_release = (
            "ANSWERVICE-LEGACY-UNVERIFIED-v1:"
            "d3ad30ebad6b36f0c0347df769096c886031fd59d3afd1d34feb88e98e7dcdb6"
        )
        permission_release = "legacy-unverified"
        semantic_release = "legacy-unverified"

        def seed_terminal_lineage(
            connection,
            request_id,
            query_execution_id,
            artifact_id,
            suffix: str,
        ) -> None:
            connection.execute(
                text(
                    """
                    INSERT INTO chat.analysis_requests (
                        request_id, request_type, user_id, user_role,
                        question_text_redacted, question_hash, ambiguity_status,
                        sql_policy_version, status, trace_id, started_at, completed_at,
                        product_release_id, permission_snapshot_id, semantic_release_id
                    ) VALUES (
                        :request_id, 'CHAT', :owner_id, 'analyst', 'approved request',
                        :question_hash, 'CLEAR', 'policy-v1', 'SUCCEEDED', :trace_id,
                        now(), now(), :product_release, :permission_release,
                        :semantic_release
                    )
                    """
                ),
                {
                    "request_id": request_id,
                    "owner_id": owner_id,
                    "question_hash": suffix * 64,
                    "trace_id": uuid4().hex,
                    "product_release": product_release,
                    "permission_release": permission_release,
                    "semantic_release": semantic_release,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO query.query_executions (
                        query_execution_id, request_id, attempt_no, generation_mode,
                        generated_sql_redacted, sql_hash, ast_validation_json,
                        join_validation_json, permission_validation_json, explain_json,
                        validation_status, trino_query_id, execution_status, row_count,
                        scan_bytes, result_checksum, source_urns_json, source_cutoff_json
                    ) VALUES (
                        :query_execution_id, :request_id, 1, 'LLM', 'SELECT 1',
                        :sql_hash, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                        'ALLOWED', :trino_query_id, 'SUCCEEDED', 1, 1,
                        :result_checksum, '[]'::jsonb, '{}'::jsonb
                    )
                    """
                ),
                {
                    "query_execution_id": query_execution_id,
                    "request_id": request_id,
                    "sql_hash": suffix * 64,
                    "trino_query_id": f"semantic-snapshot-{suffix}",
                    "result_checksum": suffix * 64,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO artifact.analysis_artifacts (
                        artifact_id, request_id, query_execution_id, artifact_type,
                        title, data_snapshot_json, chart_spec_json, narrative_markdown,
                        evidence_json, freshness_status, status, artifact_checksum,
                        product_release_id, permission_snapshot_id, semantic_release_id
                    ) VALUES (
                        :artifact_id, :request_id, :query_execution_id, 'TABLE',
                        'Approved result', '{"columns":[],"rows":[]}'::jsonb,
                        '{"chart_type":"table"}'::jsonb, 'Approved result',
                        '{"policy_version":"policy-v1"}'::jsonb, 'FRESH',
                        'APPROVED', :artifact_checksum, :product_release,
                        :permission_release, :semantic_release
                    )
                    """
                ),
                {
                    "artifact_id": artifact_id,
                    "request_id": request_id,
                    "query_execution_id": query_execution_id,
                    "artifact_checksum": suffix * 64,
                    "product_release": product_release,
                    "permission_release": permission_release,
                    "semantic_release": semantic_release,
                },
            )

        with engine.begin() as connection:
            seed_terminal_lineage(
                connection, request_one, query_one, artifact_one, "a"
            )
            seed_terminal_lineage(
                connection, request_two, query_two, artifact_two, "b"
            )

        def snapshot_json(
            source_request_id,
            query_execution_id,
            artifact_id,
            *,
            semantic: str = semantic_release,
        ) -> dict[str, object]:
            plan_identity = {
                "version": "ANSWERVICE-ANALYSIS-PLAN-v4",
                "operation": "aggregate",
                "output_metric_ids": ["reviewed_measure"],
                "dependency_metric_ids": ["reviewed_measure"],
                "dimension_fields": [],
                "filter_fields": [],
                "time_mode": "range",
                "time_fields": [
                    {
                        "asset_fqn": "serving.semantic.measure_events",
                        "column": "recorded_on",
                    }
                ],
                "time_bucket": "none",
                "period_parameters": [
                    {
                        "start_parameter": "window_start",
                        "end_parameter": "window_end",
                    }
                ],
                "snapshot_parameter": None,
                "result_limit": None,
                "query_strategy": "VIEW_REUSE",
                "joins": [],
                "context_package_hash": "d" * 64,
            }
            plan = {
                **plan_identity,
                "checksum": hashlib.sha256(
                    json.dumps(
                        plan_identity,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest(),
            }
            payload = {
                "schema_version": "ANSWERVICE-APPROVED-SEMANTIC-REQUEST-v1",
                "snapshot_id": str(snapshot_id),
                "execution_as_of": "2026-08-31",
                "timezone": "Asia/Seoul",
                "analysis_plan": plan,
                "parameter_bindings": [
                    {
                        "name": "window_start",
                        "value_type": "date",
                        "value": "2026-08-01",
                    },
                    {
                        "name": "window_end",
                        "value_type": "date",
                        "value": "2026-08-31",
                    },
                ],
                "dimension_member_receipts": [],
                "release_receipt": {
                    "product_release_id": product_release,
                    "permission_snapshot_id": permission_release,
                    "semantic_release_id": semantic,
                    "context_release": semantic,
                    "policy_version": "policy-v1",
                    "catalog_checksum": "1" * 64,
                    "canonical_checksum": "2" * 64,
                    "runtime_projection_checksum": "3" * 64,
                },
                "lineage": {
                    "source_request_id": str(source_request_id),
                    "query_execution_id": str(query_execution_id),
                    "artifact_id": str(artifact_id),
                },
            }
            return {
                **payload,
                "snapshot_hash": hashlib.sha256(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest(),
            }

        insert_snapshot = text(
            """
            INSERT INTO analysis_v1.approved_semantic_request_snapshots (
                snapshot_id, source_request_id, owner_id, query_execution_id,
                artifact_id, schema_version, snapshot_json, snapshot_hash,
                product_release_id, permission_snapshot_id, semantic_release_id
            ) VALUES (
                :snapshot_id, :source_request_id, :owner_id, :query_execution_id,
                :artifact_id, 'ANSWERVICE-APPROVED-SEMANTIC-REQUEST-v1',
                CAST(:snapshot_json AS jsonb), :snapshot_hash, :product_release,
                :permission_release, :semantic_release
            )
            """
        )

        def insert_parameters(
            source_request_id,
            query_execution_id,
            artifact_id,
            payload: dict[str, object],
            *,
            owner=owner_id,
            semantic: str = semantic_release,
        ) -> dict[str, object]:
            return {
                "snapshot_id": snapshot_id,
                "source_request_id": source_request_id,
                "owner_id": owner,
                "query_execution_id": query_execution_id,
                "artifact_id": artifact_id,
                "snapshot_json": json.dumps(payload),
                "snapshot_hash": str(payload.get("snapshot_hash") or "c" * 64),
                "product_release": product_release,
                "permission_release": permission_release,
                "semantic_release": semantic,
            }

        with engine.connect() as connection:
            transaction = connection.begin()
            with self.assertRaises(DBAPIError):
                connection.execute(
                    insert_snapshot,
                    insert_parameters(
                        request_one, query_one, artifact_one, {}
                    ),
                )
            transaction.rollback()

        required_top_level = (
            "analysis_plan",
            "parameter_bindings",
            "dimension_member_receipts",
            "lineage",
            "release_receipt",
        )
        required_release = (
            "context_release",
            "policy_version",
            "catalog_checksum",
            "canonical_checksum",
            "runtime_projection_checksum",
        )
        for top_level_key, release_key in (
            *((key, None) for key in required_top_level),
            *((None, key) for key in required_release),
        ):
            missing_payload = snapshot_json(
                request_one, query_one, artifact_one
            )
            if top_level_key is not None:
                missing_payload.pop(top_level_key)
            else:
                missing_payload["release_receipt"].pop(release_key)
            with engine.connect() as connection:
                transaction = connection.begin()
                with self.assertRaises(DBAPIError):
                    connection.execute(
                        insert_snapshot,
                        insert_parameters(
                            request_one,
                            query_one,
                            artifact_one,
                            missing_payload,
                        ),
                    )
                transaction.rollback()

        invalid_receipts = []
        invalid_timezone = snapshot_json(request_one, query_one, artifact_one)
        invalid_timezone["timezone"] = "UTC"
        invalid_receipts.append(invalid_timezone)
        for key, value in (
            ("context_release", ""),
            ("policy_version", " "),
            ("catalog_checksum", "not-a-checksum"),
        ):
            invalid_payload = snapshot_json(
                request_one, query_one, artifact_one
            )
            invalid_payload["release_receipt"][key] = value
            invalid_receipts.append(invalid_payload)
        for invalid_payload in invalid_receipts:
            with engine.connect() as connection:
                transaction = connection.begin()
                with self.assertRaises(DBAPIError):
                    connection.execute(
                        insert_snapshot,
                        insert_parameters(
                            request_one,
                            query_one,
                            artifact_one,
                            invalid_payload,
                        ),
                    )
                transaction.rollback()

        with engine.begin() as connection:
            connection.execute(
                insert_snapshot,
                insert_parameters(
                    request_one,
                    query_one,
                    artifact_one,
                    snapshot_json(request_one, query_one, artifact_one),
                ),
            )

        for statement in (
            text(
                "UPDATE analysis_v1.approved_semantic_request_snapshots "
                "SET snapshot_hash = :snapshot_hash WHERE snapshot_id = :snapshot_id"
            ),
            text(
                "DELETE FROM analysis_v1.approved_semantic_request_snapshots "
                "WHERE snapshot_id = :snapshot_id"
            ),
        ):
            with engine.connect() as connection:
                transaction = connection.begin()
                with self.assertRaises(DBAPIError):
                    connection.execute(
                        statement,
                        {"snapshot_hash": "d" * 64, "snapshot_id": snapshot_id},
                    )
                transaction.rollback()

        for parameters in (
            insert_parameters(
                request_one,
                query_two,
                artifact_two,
                snapshot_json(request_one, query_two, artifact_two),
            ),
            insert_parameters(
                request_two,
                query_two,
                artifact_two,
                snapshot_json(
                    request_two, query_two, artifact_two, semantic="different-release"
                ),
                owner=uuid4(),
                semantic="different-release",
            ),
        ):
            parameters["snapshot_id"] = uuid4()
            payload = json.loads(str(parameters["snapshot_json"]))
            payload["snapshot_id"] = str(parameters["snapshot_id"])
            parameters["snapshot_json"] = json.dumps(payload)
            with engine.connect() as connection:
                transaction = connection.begin()
                with self.assertRaises(DBAPIError):
                    connection.execute(insert_snapshot, parameters)
                transaction.rollback()
        engine.dispose()

        downgraded = alembic("downgrade", "20260830_59", database_url=url)
        self.assertEqual(0, downgraded.returncode, downgraded.stdout + downgraded.stderr)
        self.assertEqual("20260830_59", self.revision(database))
        reupgraded = alembic("upgrade", "20260831_60", database_url=url)
        self.assertEqual(0, reupgraded.returncode, reupgraded.stdout + reupgraded.stderr)
        self.assertEqual("20260831_60", self.revision(database))

    def test_mcp_output_schema_60_61_roundtrips_without_registry_expansion(self) -> None:
        """MCP schema closure가 기존 Tool 한 건만 바꾸고 안전하게 왕복한다."""

        database = self.create_database("migration_mcp_schema")
        url = self.base_url.set(database=database).render_as_string(
            hide_password=False
        )
        previous = alembic("upgrade", "20260831_60", database_url=url)
        self.assertEqual(0, previous.returncode, previous.stdout + previous.stderr)

        def registry_receipt() -> tuple[object, ...]:
            engine = create_engine(self.base_url.set(database=database))
            try:
                with engine.connect() as connection:
                    row = connection.execute(
                        text(
                            "SELECT semantic_version, transport, timeout_seconds, "
                            "required_roles_json, is_enabled, output_schema_json "
                            "FROM tooling.tool_registry "
                            "WHERE tool_code = 'analysis.get_run'"
                        )
                    ).one()
                    count = connection.execute(
                        text("SELECT count(*) FROM tooling.tool_registry")
                    ).scalar_one()
                return (*tuple(row), count)
            finally:
                engine.dispose()

        before = registry_receipt()
        self.assertNotIn("additionalProperties", before[5])
        upgraded = alembic("upgrade", "20260831_61", database_url=url)
        self.assertEqual(0, upgraded.returncode, upgraded.stdout + upgraded.stderr)
        after = registry_receipt()
        self.assertEqual(before[:5], after[:5])
        self.assertFalse(after[5]["additionalProperties"])
        self.assertEqual(before[6], after[6])

        downgraded = alembic("downgrade", "20260831_60", database_url=url)
        self.assertEqual(0, downgraded.returncode, downgraded.stdout + downgraded.stderr)
        self.assertNotIn("additionalProperties", registry_receipt()[5])
        replayed = alembic("upgrade", "20260831_61", database_url=url)
        self.assertEqual(0, replayed.returncode, replayed.stdout + replayed.stderr)
        self.assertFalse(registry_receipt()[5]["additionalProperties"])

    def test_mcp_candidate_upgrade_waits_for_concurrent_rag_run_and_fails_closed(
        self,
    ) -> None:
        """64는 registry lock 뒤 새 historical run을 보고 63에서 원자 중단한다."""

        database = self.create_database("migration_mcp_candidate_race")
        admin = create_engine(
            self.base_url.set(database="postgres"),
            isolation_level="AUTOCOMMIT",
        )
        try:
            with admin.connect() as connection:
                connection.exec_driver_sql(
                    f'ALTER DATABASE "{database}" '
                    "SET default_transaction_isolation TO 'repeatable read'"
                )
        finally:
            admin.dispose()

        database_url = self.base_url.set(database=database)
        probe = create_engine(database_url)
        try:
            with probe.connect() as connection:
                isolation = connection.execute(
                    text("SHOW transaction_isolation")
                ).scalar_one()
            self.assertEqual("repeatable read", isolation)
        finally:
            probe.dispose()

        url = database_url.render_as_string(hide_password=False)
        previous = alembic("upgrade", "20260831_63", database_url=url)
        self.assertEqual(0, previous.returncode, previous.stdout + previous.stderr)
        self.assertEqual("20260831_63", self.revision(database))

        rag_tool_id = "8edce655-e454-5b76-b56f-5e49aa2884d4"
        tool_run_id = uuid4()
        application_name = f"migration-rag-race-{uuid4().hex}"
        session_engine = create_engine(database_url)
        observer = create_engine(database_url, isolation_level="AUTOCOMMIT")
        session_a = session_engine.connect()
        session_a_transaction = session_a.begin()
        process: subprocess.Popen[str] | None = None
        try:
            session_a.execute(
                text(
                    "INSERT INTO tooling.tool_runs "
                    "(tool_run_id, tool_id, caller_user_id, caller_role, trace_id, "
                    "input_hash, status, latency_ms, output_ref_json) "
                    "VALUES (:run_id, CAST(:tool_id AS uuid), :caller_id, 'analyst', "
                    "'migration-rag-race', :input_hash, 'SUCCEEDED', 0, '{}'::jsonb)"
                ),
                {
                    "run_id": tool_run_id,
                    "tool_id": rag_tool_id,
                    "caller_id": uuid4(),
                    "input_hash": "b" * 64,
                },
            )

            environment = os.environ.copy()
            migration_url = database_url.update_query_dict(
                {
                    "application_name": application_name,
                    "options": "-c lock_timeout=12s -c statement_timeout=20s",
                }
            ).render_as_string(hide_password=False)
            environment["APP_DATABASE_URL"] = migration_url
            environment["APP_DB_USER"] = (
                make_url(migration_url).username or "migration_test"
            )
            environment["APP_CATALOG_PUBLISHER_USER"] = environment["APP_DB_USER"]
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "alembic",
                    "upgrade",
                    "20260831_64",
                ],
                cwd=BACKEND,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            deadline = time.monotonic() + 8
            blocked = None
            last_state = None
            premature_output = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    premature_output = process.communicate()
                    break
                with observer.connect() as connection:
                    last_state = connection.execute(
                        text(
                            """
                            SELECT activity.pid,
                                   activity.wait_event_type,
                                   activity.wait_event
                            FROM pg_stat_activity activity
                            WHERE activity.datname = current_database()
                              AND activity.application_name = :application_name
                            """
                        ),
                        {"application_name": application_name},
                    ).mappings().one_or_none()
                if (
                    last_state is not None
                    and last_state["wait_event_type"] == "Lock"
                ):
                    blocked = last_state
                    break
                time.sleep(0.05)

            self.assertIsNone(
                premature_output,
                f"migration exited before registry lock wait: {premature_output}",
            )
            self.assertIsNotNone(
                blocked,
                f"migration did not reach the bounded registry lock wait: {last_state}",
            )
            self.assertIsNone(process.poll())

            session_a_transaction.commit()
            stdout, stderr = process.communicate(timeout=12)
            self.assertNotEqual(0, process.returncode, stdout + stderr)
            self.assertIn(
                "rag.answer historical runs must be preserved",
                stdout + stderr,
            )
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)
            if session_a_transaction.is_active:
                session_a_transaction.rollback()
            session_a.close()
            observer.dispose()
            session_engine.dispose()

        self.assertEqual("20260831_63", self.revision(database))
        verification = create_engine(database_url)
        try:
            with verification.connect() as connection:
                preserved = connection.execute(
                    text(
                        """
                        SELECT (
                                   SELECT semantic_version
                                   FROM tooling.tool_registry
                                   WHERE tool_id = CAST(:rag_tool_id AS uuid)
                               ),
                               EXISTS (
                                   SELECT 1 FROM tooling.tool_runs
                                   WHERE tool_run_id = :tool_run_id
                               ),
                               EXISTS (
                                   SELECT 1 FROM tooling.tool_registry
                                   WHERE tool_code = 'analysis.run'
                               ),
                               EXISTS (
                                   SELECT 1 FROM tooling.tool_registry
                                   WHERE tool_code = 'ml.predict'
                               )
                        """
                    ),
                    {"rag_tool_id": rag_tool_id, "tool_run_id": tool_run_id},
                ).one()
        finally:
            verification.dispose()
        self.assertEqual(("1.1.0", True, False, False), tuple(preserved))

    def test_mcp_candidate_downgrade_refuses_child_rows_atomically(self) -> None:
        """64 downgrade 거부 시 revision, registry receipt, child row를 보존한다."""

        database = self.create_database("migration_mcp_candidate_children")
        url = self.base_url.set(database=database).render_as_string(
            hide_password=False
        )
        upgraded = alembic("upgrade", "20260831_64", database_url=url)
        self.assertEqual(0, upgraded.returncode, upgraded.stdout + upgraded.stderr)

        analysis_tool_id = "399e1d6e-54d9-5061-b3ee-555dc3666c45"
        rag_tool_id = "8edce655-e454-5b76-b56f-5e49aa2884d4"
        ml_tool_id = "3002d1d6-f681-5b5d-b0b6-0de795fb4c5c"
        engine = create_engine(self.base_url.set(database=database))

        def registry_receipt() -> tuple[tuple[object, ...], ...]:
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT tool_id::text, tool_code, semantic_version, description, "
                        "input_schema_json::text, output_schema_json::text, transport, "
                        "timeout_seconds, required_roles_json::text, is_enabled "
                        "FROM tooling.tool_registry "
                        "WHERE tool_id IN (CAST(:analysis AS uuid), CAST(:rag AS uuid), "
                        "CAST(:ml AS uuid)) ORDER BY tool_id"
                    ),
                    {
                        "analysis": analysis_tool_id,
                        "rag": rag_tool_id,
                        "ml": ml_tool_id,
                    },
                ).all()
            return tuple(tuple(row) for row in rows)

        before = registry_receipt()
        self.assertEqual(3, len(before))
        tool_run_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tooling.tool_runs "
                    "(tool_run_id, tool_id, caller_user_id, caller_role, trace_id, "
                    "input_hash, status, latency_ms, output_ref_json) "
                    "VALUES (:run_id, CAST(:tool_id AS uuid), :caller_id, 'analyst', "
                    "'migration-child-run', :input_hash, 'SUCCEEDED', 0, '{}'::jsonb)"
                ),
                {
                    "run_id": tool_run_id,
                    "tool_id": analysis_tool_id,
                    "caller_id": uuid4(),
                    "input_hash": "a" * 64,
                },
            )

        refused_run = alembic("downgrade", "20260831_63", database_url=url)
        self.assertNotEqual(0, refused_run.returncode)
        self.assertIn(
            "analysis.run candidate runs must be preserved",
            refused_run.stdout + refused_run.stderr,
        )
        self.assertEqual("20260831_64", self.revision(database))
        self.assertEqual(before, registry_receipt())
        with engine.connect() as connection:
            preserved_run = connection.execute(
                text(
                    "SELECT count(*) FROM tooling.tool_runs "
                    "WHERE tool_run_id = :run_id"
                ),
                {"run_id": tool_run_id},
            ).scalar_one()
        self.assertEqual(1, preserved_run)

        principal_subject = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM tooling.tool_runs WHERE tool_run_id = :run_id"),
                {"run_id": tool_run_id},
            )
            connection.execute(
                text(
                    "INSERT INTO tooling.tool_rate_limit_windows "
                    "(principal_subject, tool_id, window_start, request_count, expires_at) "
                    "VALUES (:subject, CAST(:tool_id AS uuid), date_trunc('minute', now()), "
                    "1, date_trunc('minute', now()) + interval '10 minutes')"
                ),
                {"subject": principal_subject, "tool_id": ml_tool_id},
            )

        refused_quota = alembic("downgrade", "20260831_63", database_url=url)
        self.assertNotEqual(0, refused_quota.returncode)
        self.assertIn(
            "ml.predict candidate quota state must be preserved",
            refused_quota.stdout + refused_quota.stderr,
        )
        self.assertEqual("20260831_64", self.revision(database))
        self.assertEqual(before, registry_receipt())
        with engine.connect() as connection:
            preserved_quota = connection.execute(
                text(
                    "SELECT count(*) FROM tooling.tool_rate_limit_windows "
                    "WHERE principal_subject = :subject "
                    "AND tool_id = CAST(:tool_id AS uuid)"
                ),
                {"subject": principal_subject, "tool_id": ml_tool_id},
            ).scalar_one()
        engine.dispose()
        self.assertEqual(1, preserved_quota)

    def test_phase1_downgrade_preserves_preexisting_manual_conversation_objects(self) -> None:
        database = self.create_database("migration_conversation_legacy")
        url = self.base_url.set(database=database).render_as_string(hide_password=False)
        before_phase1 = alembic("upgrade", "20260822_29", database_url=url)
        self.assertEqual(0, before_phase1.returncode, before_phase1.stdout + before_phase1.stderr)
        engine = create_engine(self.base_url.set(database=database))
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE artifact.view_specs (
                        view_spec_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                        artifact_id uuid NOT NULL REFERENCES artifact.analysis_artifacts(artifact_id),
                        view_type varchar(32) NOT NULL,
                        spec_json jsonb NOT NULL,
                        created_at timestamptz NOT NULL DEFAULT now()
                    );
                    CREATE TABLE chat.turns (
                        turn_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                        conversation_id uuid NOT NULL REFERENCES chat.conversations(conversation_id),
                        turn_index integer NOT NULL,
                        user_message text NOT NULL,
                        route varchar(32) NOT NULL,
                        source_turn_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
                        request_id uuid REFERENCES chat.analysis_requests(request_id),
                        artifact_id uuid REFERENCES artifact.analysis_artifacts(artifact_id),
                        view_spec_id uuid REFERENCES artifact.view_specs(view_spec_id),
                        report_definition_id uuid REFERENCES report.report_definitions(report_definition_id),
                        resolved_slots jsonb NOT NULL DEFAULT '{}'::jsonb,
                        created_at timestamptz NOT NULL DEFAULT now(),
                        UNIQUE (conversation_id, turn_index)
                    );
                    CREATE TABLE chat.turn_commands (
                        command_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                        conversation_id uuid NOT NULL REFERENCES chat.conversations(conversation_id),
                        idempotency_key varchar(128) NOT NULL,
                        canonical_input_hash char(64) NOT NULL,
                        status varchar(32) NOT NULL,
                        turn_id uuid REFERENCES chat.turns(turn_id),
                        error_response jsonb,
                        created_at timestamptz NOT NULL DEFAULT now(),
                        UNIQUE (conversation_id, idempotency_key)
                    );
                    ALTER TABLE chat.conversations
                        ADD COLUMN head_turn_id uuid REFERENCES chat.turns(turn_id),
                        ADD COLUMN turn_count integer NOT NULL DEFAULT 0,
                        ADD COLUMN active_command_id uuid REFERENCES chat.turn_commands(command_id),
                        ADD COLUMN lease_expires_at timestamptz;
                    ALTER TABLE query.query_executions
                        ADD COLUMN trino_cancel_uri text;
                    CREATE INDEX idx_chat_turns_conv
                        ON chat.turns(conversation_id, turn_index);
                    CREATE INDEX idx_view_specs_artifact
                        ON artifact.view_specs(artifact_id);
                    INSERT INTO chat.conversations (
                        conversation_id, owner_user_id, title, status,
                        created_at, updated_at, turn_count
                    ) VALUES (
                        '00000000-0000-0000-0000-000000000101',
                        '00000000-0000-0000-0000-000000000102',
                        'legacy migration conversation', 'ACTIVE',
                        TIMESTAMPTZ '2026-08-18 01:50:37+09',
                        TIMESTAMPTZ '2026-08-18 01:51:05+09', 1
                    );
                    INSERT INTO chat.turns (
                        turn_id, conversation_id, turn_index, user_message,
                        route, source_turn_ids, resolved_slots
                    ) VALUES (
                        '00000000-0000-0000-0000-000000000103',
                        '00000000-0000-0000-0000-000000000101',
                        0, 'legacy request', 'ANALYSIS', '[]'::jsonb, '{}'::jsonb
                    );
                    INSERT INTO chat.turn_commands (
                        command_id, conversation_id, idempotency_key,
                        canonical_input_hash, status, turn_id
                    ) VALUES (
                        '00000000-0000-0000-0000-000000000104',
                        '00000000-0000-0000-0000-000000000101',
                        'legacy-command', repeat('a', 64), 'COMPLETED',
                        '00000000-0000-0000-0000-000000000103'
                    );
                    UPDATE chat.conversations
                    SET head_turn_id = '00000000-0000-0000-0000-000000000103'
                    WHERE conversation_id = '00000000-0000-0000-0000-000000000101'
                    """
                )
            )
        engine.dispose()

        upgraded = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, upgraded.returncode, upgraded.stdout + upgraded.stderr)
        legacy_release = (
            "ANSWERVICE-LEGACY-UNVERIFIED-v1:"
            "d3ad30ebad6b36f0c0347df769096c886031fd59d3afd1d34feb88e98e7dcdb6"
        )
        with engine.connect() as connection:
            backfilled = connection.execute(
                text(
                    """
                    SELECT conversation.product_release_id,
                           conversation.permission_snapshot_id,
                           conversation.semantic_release_id,
                           conversation.wall_clock_anchor::text,
                           turn.product_release_id,
                           turn.permission_snapshot_id,
                           turn.semantic_release_id,
                           turn.terminal_status,
                           command.effective_subject_id::text,
                           command.product_release_id,
                           EXISTS (
                               SELECT 1
                               FROM governance.product_release_manifests manifest
                               WHERE manifest.product_release_id = :legacy_release
                           )
                    FROM chat.conversations conversation
                    JOIN chat.turns turn
                      ON turn.conversation_id = conversation.conversation_id
                    JOIN chat.turn_commands command
                      ON command.conversation_id = conversation.conversation_id
                    WHERE conversation.conversation_id =
                        '00000000-0000-0000-0000-000000000101'
                    """
                ),
                {"legacy_release": legacy_release},
            ).one()
        self.assertEqual(
            (
                legacy_release,
                "legacy-unverified",
                "legacy-unverified",
                "2026-08-18",
                legacy_release,
                "legacy-unverified",
                "legacy-unverified",
                "SUCCEEDED",
                "00000000-0000-0000-0000-000000000102",
                legacy_release,
                True,
            ),
            tuple(backfilled),
        )
        downgraded = alembic("downgrade", "20260822_29", database_url=url)
        self.assertEqual(0, downgraded.returncode, downgraded.stdout + downgraded.stderr)

        engine = create_engine(self.base_url.set(database=database))
        with engine.connect() as connection:
            preserved = connection.execute(
                text(
                    """
                    SELECT to_regclass('chat.turns') IS NOT NULL,
                           to_regclass('chat.turn_commands') IS NOT NULL,
                           to_regclass('artifact.view_specs') IS NOT NULL,
                           to_regclass('chat.idx_chat_turns_conv') IS NOT NULL,
                           to_regclass('artifact.idx_view_specs_artifact') IS NOT NULL,
                           EXISTS (
                               SELECT 1 FROM information_schema.columns
                               WHERE table_schema = 'chat'
                                 AND table_name = 'conversations'
                                 AND column_name = 'head_turn_id'
                           ),
                           NOT EXISTS (
                               SELECT 1 FROM information_schema.columns
                               WHERE table_schema = 'chat'
                                 AND table_name = 'turn_commands'
                                 AND column_name = 'product_release_id'
                           ),
                           EXISTS (
                               SELECT 1 FROM information_schema.columns
                               WHERE table_schema = 'query'
                                 AND table_name = 'query_executions'
                                 AND column_name = 'trino_cancel_uri'
                           )
                    """
                )
            ).one()
        engine.dispose()
        self.assertEqual(
            (True, True, True, True, True, True, True, True),
            tuple(preserved),
        )

        second_upgrade = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, second_upgrade.returncode, second_upgrade.stdout + second_upgrade.stderr)
        self.assertEqual("20260831_64", self.revision(database))

    def test_capability_evidence_contract_roundtrips_and_is_immutable(self) -> None:
        database = self.create_database("migration_evidence")
        url = self.base_url.set(database=database).render_as_string(hide_password=False)
        upgrade = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, upgrade.returncode, upgrade.stdout + upgrade.stderr)

        engine = create_engine(self.base_url.set(database=database))
        release_id = "ANSWERVICE-PRODUCT-RELEASE-v1:" + "9" * 64
        image_receipts = [{"component": "backend", "digest": "sha256:" + "4" * 64}]
        release_vector = {
            "data_release_id": "data-v1",
            "semantic_release_id": "semantic-v1",
            "prompt_release_id": "prompt-v1",
            "policy_release_id": "policy-v1",
            "runtime_release_id": "runtime-v1",
        }
        manifest = {
            "schema_version": "ProductReleaseEvidenceManifest.v1",
            "product_release_id": release_id,
            "manifest_sha256": "1" * 64,
            "created_at": "2026-08-22T00:00:00Z",
            "evidence": {
                "source": {
                    "commit_sha": "2" * 40,
                    "dirty": True,
                    "dirty_patch_sha256": "3" * 64,
                },
                "images": image_receipts,
                "migration": {"revision": "20260822_29", "chain_sha256": "5" * 64},
                "model": {
                    "release_id": "MODEL-RELEASE-v1.32.0",
                    "manifest_sha256": "6" * 64,
                },
                "catalog": {
                    "release_id": "catalog-v1",
                    "manifest_sha256": "7" * 64,
                    "projection_sha256": "8" * 64,
                },
                "release_vector": release_vector,
            },
        }
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO governance.product_release_manifests (
                        product_release_id, contract_version, manifest_sha256,
                        manifest_json, source_commit_sha, source_dirty,
                        dirty_patch_sha256, image_digests_json, migration_revision,
                        migration_chain_sha256, model_release_id,
                        model_manifest_sha256, catalog_release_id,
                        catalog_manifest_sha256, catalog_projection_sha256,
                        release_vector_json, created_at
                    ) VALUES (
                        :release_id, 'ProductReleaseEvidenceManifest.v1', :manifest_sha,
                        CAST(:manifest AS jsonb), :source_commit, true,
                        :patch_sha, CAST(:images AS jsonb), '20260822_29',
                        :migration_sha, 'MODEL-RELEASE-v1.32.0',
                        :model_sha, 'catalog-v1', :catalog_sha, :projection_sha,
                        CAST(:release_vector AS jsonb), now()
                    )
                    """
                ),
                {
                    "release_id": release_id,
                    "manifest_sha": "1" * 64,
                    "manifest": json.dumps(manifest),
                    "source_commit": "2" * 40,
                    "patch_sha": "3" * 64,
                    "images": json.dumps(image_receipts),
                    "migration_sha": "5" * 64,
                    "model_sha": "6" * 64,
                    "catalog_sha": "7" * 64,
                    "projection_sha": "8" * 64,
                    "release_vector": json.dumps(release_vector),
                },
            )
            for object_kind in (
                "CONVERSATION", "TURN", "CONTEXT", "RUN", "ARTIFACT", "VIEW", "REPORT"
            ):
                connection.execute(
                    text(
                        """
                        INSERT INTO governance.product_release_bindings (
                            object_kind, object_id, product_release_id,
                            permission_snapshot_id, semantic_release_id,
                            capability_release_vector_json, evidence_refs_json
                        ) VALUES (
                            :kind, :object_id, :release_id, 'permission-v1',
                            'semantic-v1', '{"analysis.run":"1.0.0"}'::jsonb, '[]'::jsonb
                        )
                        """
                    ),
                    {"kind": object_kind, "object_id": object_kind.lower(), "release_id": release_id},
                )
        with engine.connect() as connection:
            count = connection.execute(
                text("SELECT count(*) FROM governance.product_release_bindings")
            ).scalar_one()
            self.assertEqual(7, count)
            with self.assertRaises(DBAPIError):
                connection.execute(
                    text(
                        "UPDATE governance.product_release_bindings "
                        "SET semantic_release_id = 'changed' WHERE object_kind = 'RUN'"
                    )
                )
        engine.dispose()

        downgrade = alembic("downgrade", "20260820_28", database_url=url)
        self.assertEqual(0, downgrade.returncode, downgrade.stdout + downgrade.stderr)
        self.assertEqual("20260820_28", self.revision(database))
        second_upgrade = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, second_upgrade.returncode, second_upgrade.stdout + second_upgrade.stderr)
        self.assertEqual("20260831_64", self.revision(database))


if __name__ == "__main__":
    unittest.main()
