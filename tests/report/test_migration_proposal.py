import unittest
import hashlib
from pathlib import Path


class MigrationProposalTest(unittest.TestCase):
    def test_proposal_contains_versioned_definition_run_and_block_tables(self):
        path = Path("src/report/migration_proposal.sql")
        sql = path.read_text(encoding="utf-8")
        self.assertEqual(
            "41be161684d3534304b69caf5190544394a80c250cc569b4f2388c2822d28679",
            hashlib.sha256(path.read_bytes()).hexdigest(),
            "REPORT-v1.0.0 migration proposal은 수정할 수 없습니다.",
        )
        for table in (
            "report_definitions", "report_definition_versions", "report_blocks",
            "report_runs", "report_block_runs",
        ):
            self.assertIn(f"CREATE TABLE {table}", sql)
        self.assertIn("PRIMARY KEY (definition_id, version)", sql)
        self.assertIn("definition_version integer NOT NULL", sql)
        self.assertNotIn("DROP TABLE", sql.upper())
        self.assertNotIn("ALTER TABLE", sql.upper())

    def test_v1_1_proposal_is_additive_and_keeps_client_results_out(self):
        sql = Path("src/report/migration_proposal_v1_1.sql").read_text(encoding="utf-8")
        for column in ("block_type", " x smallint", " y smallint", " w smallint", " h smallint", "content text"):
            self.assertIn(column, sql)
        self.assertIn("x + w <= 12", sql)
        self.assertIn("columns = w", sql)
        self.assertIn("block_type IN ('table', 'chart') AND artifact_id IS NOT NULL", sql)
        self.assertIn("block_type = 'text' AND btrim(content) <> ''", sql)
        self.assertIn("CREATE TABLE report_v1.report_manual_run_commands", sql)
        self.assertIn("UNIQUE (definition_id, definition_version, idempotency_key)", sql)
        command_table = sql.split("CREATE TABLE report_v1.report_manual_run_commands", 1)[1].split(");", 1)[0]
        for forbidden in ("policy_version", "context_hash", "watermark", "block_results"):
            self.assertNotIn(f"{forbidden} ", command_table)


if __name__ == "__main__":
    unittest.main()
