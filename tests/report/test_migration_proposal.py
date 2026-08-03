import unittest
from pathlib import Path


class MigrationProposalTest(unittest.TestCase):
    def test_proposal_contains_versioned_definition_run_and_block_tables(self):
        sql = Path("src/report/migration_proposal.sql").read_text(encoding="utf-8")
        for table in (
            "report_definitions", "report_definition_versions", "report_blocks",
            "report_runs", "report_block_runs",
        ):
            self.assertIn(f"CREATE TABLE {table}", sql)
        self.assertIn("PRIMARY KEY (definition_id, version)", sql)
        self.assertIn("definition_version integer NOT NULL", sql)
        self.assertNotIn("DROP TABLE", sql.upper())
        self.assertNotIn("ALTER TABLE", sql.upper())


if __name__ == "__main__":
    unittest.main()