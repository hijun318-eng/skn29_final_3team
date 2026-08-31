from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import patch

from app.services.mcp_tool_registry import (
    ANALYSIS_GET_RUN_ANNOTATIONS,
    ANALYSIS_GET_RUN_TITLE,
)


ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    ROOT
    / "app/backend/migrations/versions/20260831_68_mcp_registry_metadata.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mcp_registry_metadata_68", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("MCP registry metadata migration cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _captured_sql(module: ModuleType, direction: str) -> str:
    statements: list[str] = []
    with patch.object(module.op, "execute", side_effect=statements.append):
        getattr(module, direction)()
    return " ".join(" ".join(statement.upper().split()) for statement in statements)


class MCPRegistryMetadataMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.migration = _load_migration()

    def test_upgrade_follows_report_head_and_fail_closes_four_receipts(self) -> None:
        self.assertEqual("20260831_68", self.migration.revision)
        self.assertEqual("20260831_67", self.migration.down_revision)

        sql = _captured_sql(self.migration, "upgrade")
        self.assertIn("LOCK TABLE TOOLING.TOOL_REGISTRY", sql)
        self.assertIn("COUNT(*) FROM TOOLING.TOOL_REGISTRY) <> 4", sql)
        self.assertIn("AFFECTED <> 4", sql)
        for tool_id in (
            self.migration.ANALYSIS_GET_RUN_TOOL_ID,
            self.migration.ANALYSIS_RUN_TOOL_ID,
            self.migration.RAG_ANSWER_TOOL_ID,
            self.migration.ML_PREDICT_TOOL_ID,
        ):
            with self.subTest(tool_id=tool_id):
                self.assertIn(tool_id.upper(), sql)
        self.assertIn("INPUT_SCHEMA_JSON =", sql)
        self.assertIn("OUTPUT_SCHEMA_JSON =", sql)
        self.assertIn("ANNOTATIONS_JSON", sql)
        self.assertIn("'CANCELLED'", sql)

    def test_active_descriptor_metadata_matches_canonical_backfill(self) -> None:
        self.assertEqual("Get Analysis Run", ANALYSIS_GET_RUN_TITLE)
        self.assertEqual(
            dict(ANALYSIS_GET_RUN_ANNOTATIONS),
            self.migration.READ_ONLY_ANNOTATIONS,
        )

    def test_candidate_schema_receipts_are_exact_canonical_json(self) -> None:
        candidate_path = (
            ROOT
            / "app/backend/migrations/versions/20260831_64_mcp_candidate_descriptors.py"
        )
        spec = importlib.util.spec_from_file_location("mcp_candidate_64_for_68", candidate_path)
        if spec is None or spec.loader is None:
            self.fail("MCP candidate migration cannot be loaded")
        candidate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(candidate)

        for name in (
            "ANALYSIS_RUN_INPUT_SCHEMA",
            "ANALYSIS_RUN_OUTPUT_SCHEMA",
            "RAG_ANSWER_INPUT_SCHEMA",
            "RAG_ANSWER_OUTPUT_SCHEMA",
            "ML_PREDICT_INPUT_SCHEMA",
            "ML_PREDICT_OUTPUT_SCHEMA",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    getattr(candidate, name),
                    json.loads(getattr(self.migration, f"{name}_JSON")),
                )

    def test_downgrade_preserves_cancelled_or_drifted_metadata(self) -> None:
        sql = _captured_sql(self.migration, "downgrade")
        cancelled_check = sql.index("WHERE STATUS = 'CANCELLED'")
        metadata_check = sql.index("MCP REGISTRY METADATA MUST BE PRESERVED")
        drop_columns = sql.index("DROP COLUMN ANNOTATIONS_JSON")

        self.assertLess(cancelled_check, drop_columns)
        self.assertLess(metadata_check, drop_columns)
        self.assertIn("COUNT(*) FROM TOOLING.TOOL_REGISTRY) <> 4", sql)
        self.assertIn("STATUS IN ('SUCCEEDED','FAILED','DENIED')", sql)


if __name__ == "__main__":
    unittest.main()
