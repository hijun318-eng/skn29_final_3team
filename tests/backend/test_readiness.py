from __future__ import annotations

import unittest
from pathlib import Path
from sys import path
from unittest.mock import MagicMock, patch

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.services.readiness import AppDatabaseReadiness


def current_migration_head() -> str:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


class AppDatabaseReadinessMigrationTest(unittest.TestCase):
    def test_exact_approved_template_count_must_be_one(self) -> None:
        current_head = current_migration_head()
        for count, expected in ((0, "not_ready"), (1, "ready"), (2, "not_ready")):
            with self.subTest(count=count):
                connection = MagicMock()
                connection.execute.side_effect = [
                    MagicMock(scalar_one_or_none=lambda: current_head),
                    MagicMock(scalar_one=lambda: count),
                ]
                engine = MagicMock()
                engine.connect.return_value.__enter__.return_value = connection
                with patch(
                    "app.services.readiness.create_engine",
                    return_value=engine,
                ), patch.dict(
                    "os.environ",
                    {"APP_RUNTIME_DATABASE_URL": "postgresql://readiness"},
                ):
                    result = AppDatabaseReadiness._database_probe()

                self.assertEqual(expected, result["approved_templates"])
                query = str(connection.execute.call_args_list[1].args[0])
                self.assertIn("template_id = 'weekly-room-operations'", query)
                self.assertIn("version = 'I2-v1.1.0'", query)
                self.assertIn("status = 'APPROVED'", query)

    def test_no_database_or_database_error_fail_closed(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                "not_configured",
                AppDatabaseReadiness._database_probe()["app_postgres"],
            )
        with patch(
            "app.services.readiness.create_engine",
            side_effect=RuntimeError("database unavailable"),
        ), patch.dict(
            "os.environ", {"APP_RUNTIME_DATABASE_URL": "postgresql://readiness"}
        ):
            self.assertEqual(
                {
                    "app_postgres": "not_ready",
                    "migration": "not_ready",
                    "approved_templates": "not_ready",
                },
                AppDatabaseReadiness._database_probe(),
            )

    def test_current_migration_head_is_ready(self) -> None:
        self.assertEqual(
            "ready", AppDatabaseReadiness._migration_status(current_migration_head())
        )

    def test_old_or_unknown_migration_head_is_not_ready(self) -> None:
        for version in ("20260731_03", "unknown", None):
            with self.subTest(version=version):
                self.assertEqual(
                    "not_ready", AppDatabaseReadiness._migration_status(version)
                )

    def test_multiple_migration_heads_fail_closed(self) -> None:
        with patch(
            "app.services.readiness.ScriptDirectory.from_config"
        ) as from_config:
            from_config.return_value.get_heads.return_value = ["head_a", "head_b"]
            with self.assertRaisesRegex(RuntimeError, "exactly one head"):
                AppDatabaseReadiness._migration_status("head_a")

    def test_real_dependencies_and_model_are_all_probed(self) -> None:
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        with patch("app.services.readiness.urlopen", return_value=response), patch.dict(
            "os.environ",
            {
                "DATAHUB_GMS_URL": "http://datahub",
                "TRINO_URL": "http://trino",
                "OPENAI_ENDPOINT": "http://model",
                "OPENAI_API_KEY": "token",
                "OPENAI_MODEL": "model",
            },
            clear=True,
        ):
            self.assertEqual("ready", AppDatabaseReadiness._trino_probe())
            self.assertEqual("ready", AppDatabaseReadiness._datahub_probe())
            self.assertEqual("ready", AppDatabaseReadiness._model_probe())

    def test_release_auth_readiness_requires_database_secret_and_principal_file(self) -> None:
        with patch.dict("os.environ", {"AUTH_MODE": "release"}, clear=True):
            self.assertEqual("not_ready", AppDatabaseReadiness._auth_probe())

        with patch.dict("os.environ", {"AUTH_MODE": "test"}, clear=True):
            self.assertEqual("not_required", AppDatabaseReadiness._auth_probe())

    def test_model_probe_retries_one_transient_timeout(self) -> None:
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        environment = {
            "OPENAI_ENDPOINT": "http://model",
            "OPENAI_API_KEY": "token",
            "OPENAI_MODEL": "model",
        }
        with patch(
            "app.services.readiness.urlopen",
            side_effect=[TimeoutError, response],
        ) as urlopen_mock, patch.dict("os.environ", environment, clear=True):
            self.assertEqual("ready", AppDatabaseReadiness._model_probe())
            self.assertEqual(2, urlopen_mock.call_count)

        with patch(
            "app.services.readiness.urlopen",
            side_effect=TimeoutError,
        ) as urlopen_mock, patch.dict("os.environ", environment, clear=True):
            self.assertEqual("not_ready", AppDatabaseReadiness._model_probe())
            self.assertEqual(2, urlopen_mock.call_count)


if __name__ == "__main__":
    unittest.main()
