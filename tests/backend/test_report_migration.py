from __future__ import annotations

import ast
from pathlib import Path
import unittest


MIGRATIONS = Path(__file__).resolve().parents[2] / "app" / "backend" / "migrations" / "versions"


class ReportMigrationTest(unittest.TestCase):
    def test_report_registration_is_one_new_migration_after_existing_head(self):
        source = (MIGRATIONS / "20260804_04_report_registration.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        values = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"revision", "down_revision"}
        }

        self.assertEqual(
            {"revision": "20260804_04", "down_revision": "20260731_03"},
            values,
        )
        for table in (
            "report_definitions",
            "report_definition_versions",
            "report_blocks",
            "report_runs",
            "report_block_runs",
        ):
            self.assertIn(f"CREATE TABLE report_v1.{table}", source)
        self.assertIn("report_approved_version_immutable", source)
        self.assertIn("report_approved_blocks_immutable", source)
        self.assertIn("report_run_requires_approved_definition", source)
        self.assertNotIn("worker", source.lower())
        self.assertNotIn("schedule", source.lower())

    def test_report_v11_is_a_new_additive_migration_after_report_v1(self):
        source = (MIGRATIONS / "20260804_05_report_v11_registration.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        values = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"revision", "down_revision"}
        }
        self.assertEqual(
            {"revision": "20260804_05", "down_revision": "20260804_04"},
            values,
        )
        for field in ("block_type", " x smallint", " y smallint", " w smallint", " h smallint", "content text"):
            self.assertIn(field, source)
        self.assertIn("columns = w", source)
        self.assertIn("x + w <= 12", source)
        self.assertIn("report_block_artifact_check", source)
        self.assertIn("CREATE TABLE report_v1.report_manual_run_commands", source)
        self.assertIn("report_manual_command_requires_approved_definition", source)
        self.assertIn("UNIQUE (definition_id, definition_version, idempotency_key)", source)
        self.assertIn("CHECK (btrim(idempotency_key) <> '')", source)
        self.assertIn("GRANT DELETE ON report_v1.report_blocks", source)
        self.assertIn("GRANT SELECT, INSERT, UPDATE ON report_v1.report_manual_run_commands", source)
        self.assertNotIn("worker", source.lower())
        self.assertNotIn("schedule", source.lower())


if __name__ == "__main__":
    unittest.main()
