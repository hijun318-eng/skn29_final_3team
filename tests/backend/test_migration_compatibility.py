from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
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
        self.assertEqual(["20260829_58"], script.get_heads())
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
        self.assertEqual("20260829_58", script.get_current_head())

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
        self.assertEqual("20260829_58", self.revision(self.empty_database))
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
        self.assertEqual("20260829_58", self.revision(self.known_database))

    def test_report_head_upgrades_to_analysis_persistence_head(self) -> None:
        database = self.create_database("migration_report")
        url = self.base_url.set(database=database).render_as_string(hide_password=False)
        report_head = alembic("upgrade", "20260804_05", database_url=url)
        self.assertEqual(0, report_head.returncode, report_head.stdout + report_head.stderr)

        head = alembic("upgrade", "head", database_url=url)

        self.assertEqual(0, head.returncode, head.stdout + head.stderr)
        self.assertEqual("20260829_58", self.revision(database))

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
        self.assertEqual("20260829_58", self.revision(database))

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
        self.assertEqual("20260829_58", self.revision(database))

    def test_analysis_head_roundtrips_through_context_registry_and_run_parameters(self) -> None:
        database = self.create_database("migration_context")
        url = self.base_url.set(database=database).render_as_string(hide_password=False)
        known = alembic("upgrade", "20260810_06", database_url=url)
        self.assertEqual(0, known.returncode, known.stdout + known.stderr)

        upgrade = alembic("upgrade", "head", database_url=url)
        self.assertEqual(0, upgrade.returncode, upgrade.stdout + upgrade.stderr)
        self.assertEqual("20260829_58", self.revision(database))
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
        self.assertEqual("20260829_58", self.revision(database))

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
        self.assertEqual("20260829_58", self.revision(database))

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
        self.assertEqual("20260829_58", self.revision(database))


if __name__ == "__main__":
    unittest.main()
