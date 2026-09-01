from __future__ import annotations

import ast
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
MIGRATION = (
    BACKEND
    / "migrations"
    / "versions"
    / "20260831_63_mcp_tool_rate_limits.py"
)


class McpToolRateLimitMigrationTest(unittest.TestCase):
    def test_revision_is_linear_child_of_62_in_alembic_graph(self) -> None:
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "migrations"))
        script = ScriptDirectory.from_config(config)

        revision = script.get_revision("20260831_63")
        self.assertIsNotNone(revision)
        self.assertEqual("20260831_62", revision.down_revision)

        assignments: dict[str, object] = {}
        for node in ast.parse(MIGRATION.read_text(encoding="utf-8")).body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in {"revision", "down_revision"}
            ):
                assignments[node.targets[0].id] = ast.literal_eval(node.value)
        self.assertEqual(
            {"revision": "20260831_63", "down_revision": "20260831_62"},
            assignments,
        )

    def test_upgrade_uses_composite_key_expiry_index_and_table_scoped_privileges(self) -> None:
        statements: list[str] = []
        with patch.dict("os.environ", {"APP_DB_USER": "runtime_app"}, clear=True):
            namespace = runpy.run_path(str(MIGRATION))
            with patch.object(namespace["op"], "execute", side_effect=statements.append):
                namespace["upgrade"]()

        normalized = " ".join(" ".join(statements).upper().split())
        self.assertIn("CREATE TABLE TOOLING.TOOL_RATE_LIMIT_WINDOWS", normalized)
        self.assertIn(
            "PRIMARY KEY (PRINCIPAL_SUBJECT, TOOL_ID, WINDOW_START)",
            normalized,
        )
        self.assertIn("REFERENCES TOOLING.TOOL_REGISTRY(TOOL_ID)", normalized)
        self.assertIn("IDX_TOOL_RATE_LIMIT_WINDOWS_EXPIRES", normalized)
        self.assertIn(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON TOOLING.TOOL_RATE_LIMIT_WINDOWS TO "RUNTIME_APP"',
            normalized,
        )
        self.assertNotIn("ON ALL TABLES", normalized)

    def test_downgrade_refuses_to_drop_preserved_rows_before_revoke(self) -> None:
        statements: list[str] = []
        with patch.dict("os.environ", {"APP_DB_USER": "runtime_app"}, clear=True):
            namespace = runpy.run_path(str(MIGRATION))
            with patch.object(namespace["op"], "execute", side_effect=statements.append):
                namespace["downgrade"]()

        normalized = [" ".join(statement.upper().split()) for statement in statements]
        program = "; ".join(normalized)
        lock_at = program.index(
            "LOCK TABLE TOOLING.TOOL_RATE_LIMIT_WINDOWS IN SHARE ROW EXCLUSIVE MODE"
        )
        emptiness_check_at = program.index(
            "IF EXISTS (SELECT 1 FROM TOOLING.TOOL_RATE_LIMIT_WINDOWS)"
        )
        revoke_at = program.index(
            "REVOKE SELECT, INSERT, UPDATE, DELETE "
            "ON TOOLING.TOOL_RATE_LIMIT_WINDOWS FROM"
        )
        drop_at = program.index("DROP TABLE TOOLING.TOOL_RATE_LIMIT_WINDOWS")

        self.assertLess(lock_at, emptiness_check_at)
        self.assertLess(emptiness_check_at, revoke_at)
        self.assertLess(revoke_at, drop_at)
        self.assertIn("MUST BE PRESERVED BEFORE DOWNGRADE", program)


if __name__ == "__main__":
    unittest.main()
