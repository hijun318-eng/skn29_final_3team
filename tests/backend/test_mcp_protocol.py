from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.mcp_router import (
    MCP_PROTOCOL_VERSION,
    TOOL_INPUT_SCHEMA,
    TOOL_NAME,
    TOOL_OUTPUT_SCHEMA,
    _has_client_info,
    _origin_allowed,
    _role_is_allowed,
    _tool_registry_access,
)
from app.contracts import Role


ROOT = Path(__file__).resolve().parents[2]


class _RegistryResult:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def mappings(self) -> "_RegistryResult":
        return self

    def one_or_none(self) -> dict[str, object] | None:
        return self._row


class _RegistrySession:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row
        self.statement = ""

    async def execute(self, statement: object, _parameters: object) -> _RegistryResult:
        self.statement = str(statement)
        return _RegistryResult(self._row)


class _RegistryScope:
    def __init__(self, session: _RegistrySession) -> None:
        self._session = session

    async def __aenter__(self) -> _RegistrySession:
        return self._session

    async def __aexit__(self, *_args: object) -> None:
        return None


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

    def test_tool_entitlement_accepts_only_canonical_nonempty_role_arrays(self) -> None:
        self.assertTrue(_role_is_allowed(["analyst"], Role.ANALYST))
        self.assertTrue(_role_is_allowed(["analyst"], Role.ADMIN))
        self.assertFalse(_role_is_allowed(["admin"], Role.ANALYST))
        self.assertFalse(_role_is_allowed([], Role.ADMIN))
        self.assertFalse(_role_is_allowed(["platform_admin"], Role.ADMIN))
        self.assertFalse(_role_is_allowed("analyst", Role.ANALYST))

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

    def test_two_role_migration_constrains_tool_roles_and_preserves_prior_audit_grant(self) -> None:
        source = (
            ROOT / "app/backend/migrations/versions/20260827_31_admin_control_plane.py"
        ).read_text(encoding="utf-8")
        self.assertIn("ck_tool_registry_required_roles", source)
        self.assertIn(
            "context.valid_analysis_template_roles(required_roles_json)", source
        )
        self.assertNotIn(
            "REVOKE SELECT, INSERT ON governance.audit_events", source
        )


class McpRegistryAccessTest(unittest.IsolatedAsyncioTestCase):
    async def test_registry_reads_enabled_and_roles_from_same_row(self) -> None:
        session = _RegistrySession(
            {"is_enabled": True, "required_roles_json": ["admin"]}
        )
        with (
            patch(
                "app.api.mcp_router.session_scope",
                return_value=_RegistryScope(session),
            ),
            patch("app.api.mcp_router._database_url", return_value="postgresql+asyncpg://db"),
        ):
            self.assertEqual((True, False), await _tool_registry_access(Role.ANALYST))
        self.assertIn("is_enabled, required_roles_json", session.statement)


if __name__ == "__main__":
    unittest.main()
