from __future__ import annotations

import ast
import unittest
from pathlib import Path

from app.api.mcp_router import (
    MCP_PROTOCOL_VERSION,
    TOOL_INPUT_SCHEMA,
    TOOL_NAME,
    TOOL_OUTPUT_SCHEMA,
    _has_client_info,
    _origin_allowed,
)


ROOT = Path(__file__).resolve().parents[2]


class McpProtocolTest(unittest.TestCase):
    def test_contract_is_one_read_only_owner_scoped_tool(self) -> None:
        self.assertEqual("2026-07-28", MCP_PROTOCOL_VERSION)
        self.assertEqual("analysis.get_run", TOOL_NAME)
        self.assertEqual(["request_id"], TOOL_INPUT_SCHEMA["required"])
        self.assertFalse(TOOL_INPUT_SCHEMA["additionalProperties"])
        self.assertIn("artifact_id", TOOL_OUTPUT_SCHEMA["required"])

    def test_latest_stateless_client_identity_is_required(self) -> None:
        self.assertTrue(_has_client_info({"_meta": {"io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"}}}))
        self.assertFalse(_has_client_info({}))
        self.assertFalse(_has_client_info({"_meta": {"io.modelcontextprotocol/clientInfo": {"name": "", "version": "1"}}}))

    def test_origin_is_fail_closed_when_present(self) -> None:
        self.assertTrue(_origin_allowed(None))
        self.assertFalse(_origin_allowed("https://evil.example"))

    def test_migration_is_additive_and_does_not_create_rag_or_ml(self) -> None:
        source = (ROOT / "app/backend/migrations/versions/20260812_12_mcp_tool.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        values = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"revision", "down_revision"}
        }
        self.assertEqual({"revision": "20260812_12", "down_revision": "20260812_11"}, values)
        self.assertIn("CREATE TABLE tooling.tool_registry", source)
        self.assertIn("CREATE TABLE tooling.tool_runs", source)
        self.assertNotIn("CREATE TABLE rag.", source)
        self.assertNotIn("CREATE TABLE ml.", source)


if __name__ == "__main__":
    unittest.main()
