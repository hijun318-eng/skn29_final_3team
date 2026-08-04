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


if __name__ == "__main__":
    unittest.main()
