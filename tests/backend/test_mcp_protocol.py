from __future__ import annotations

import ast
import base64
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.exceptions import RequestValidationError

from app.api.mcp_router import (
    HEADER_MISMATCH,
    MCP_PROTOCOL_VERSION,
    MCP_SERVER_INFO,
    TOOL_INPUT_SCHEMA,
    TOOL_NAME,
    TOOL_OUTPUT_SCHEMA,
    UNSUPPORTED_PROTOCOL_VERSION,
    _decode_mcp_header,
    _discovery_result,
    _has_request_metadata,
    _origin_allowed,
    _rpc_result,
    _structured_run_output,
    _valid_request_id,
    mcp_post,
)


ROOT = Path(__file__).resolve().parents[2]


class _StubRequest:
    def __init__(self, payload: object, *, origin: str | None = None) -> None:
        self._payload = payload
        self.headers = {} if origin is None else {"Origin": origin}

    async def json(self) -> object:
        return self._payload


def _request_payload(
    method: str = "server/discover",
    *,
    version: str = MCP_PROTOCOL_VERSION,
    request_id: object = "request-1",
    extra_params: dict[str, object] | None = None,
) -> dict[str, object]:
    params: dict[str, object] = {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": version,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    }
    if extra_params:
        params.update(extra_params)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }


class McpProtocolTest(unittest.TestCase):
    def test_contract_is_one_read_only_owner_scoped_tool(self) -> None:
        self.assertEqual("2026-07-28", MCP_PROTOCOL_VERSION)
        self.assertEqual("analysis.get_run", TOOL_NAME)
        self.assertEqual(["request_id"], TOOL_INPUT_SCHEMA["required"])
        self.assertFalse(TOOL_INPUT_SCHEMA["additionalProperties"])
        self.assertIn("artifact_id", TOOL_OUTPUT_SCHEMA["required"])

    def test_latest_stateless_request_metadata_is_self_contained(self) -> None:
        metadata = {
            "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
            "io.modelcontextprotocol/clientCapabilities": {},
            "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
        }
        self.assertTrue(_has_request_metadata({"_meta": metadata}, MCP_PROTOCOL_VERSION))
        self.assertTrue(_has_request_metadata(
            {"_meta": {key: value for key, value in metadata.items() if not key.endswith("clientInfo")}},
            MCP_PROTOCOL_VERSION,
        ))
        self.assertFalse(_has_request_metadata({}, MCP_PROTOCOL_VERSION))
        self.assertFalse(_has_request_metadata(
            {"_meta": {**metadata, "io.modelcontextprotocol/protocolVersion": "2025-11-25"}},
            MCP_PROTOCOL_VERSION,
        ))
        self.assertFalse(_has_request_metadata(
            {"_meta": {**metadata, "io.modelcontextprotocol/clientInfo": {"name": "", "version": "1"}}},
            MCP_PROTOCOL_VERSION,
        ))

    def test_discovery_and_results_publish_stateless_server_contract(self) -> None:
        discovery = _discovery_result()
        self.assertEqual([MCP_PROTOCOL_VERSION], discovery["supportedVersions"])
        self.assertEqual({"tools": {"listChanged": False}}, discovery["capabilities"])
        self.assertEqual((0, "private"), (discovery["ttlMs"], discovery["cacheScope"]))

        body = json.loads(_rpc_result("discover", discovery).body)
        self.assertEqual("complete", body["result"]["resultType"])
        self.assertEqual(
            MCP_SERVER_INFO,
            body["result"]["_meta"]["io.modelcontextprotocol/serverInfo"],
        )

    def test_tool_output_is_projected_to_the_declared_schema(self) -> None:
        projected = _structured_run_output({
            "request_id": "request-1",
            "status": "SUCCEEDED",
            "trace_id": "trace-1",
            "query_id": None,
            "artifact_id": "artifact-1",
            "internal_context": {"must_not_leak": True},
        })
        self.assertEqual(set(TOOL_OUTPUT_SCHEMA["properties"]), set(projected))
        self.assertNotIn("internal_context", projected)
        with self.assertRaises(ValueError):
            _structured_run_output({
                "request_id": "request-1",
                "status": "SUCCEEDED",
                "trace_id": None,
                "query_id": None,
                "artifact_id": None,
            })

    def test_origin_is_fail_closed_when_present(self) -> None:
        self.assertTrue(_origin_allowed(None))
        self.assertFalse(_origin_allowed("https://evil.example"))

    def test_request_id_and_encoded_name_follow_wire_contract(self) -> None:
        self.assertTrue(_valid_request_id("request-1"))
        self.assertTrue(_valid_request_id(1))
        self.assertFalse(_valid_request_id(None))
        self.assertFalse(_valid_request_id(True))

        encoded = base64.b64encode(TOOL_NAME.encode()).decode()
        self.assertEqual(
            TOOL_NAME,
            _decode_mcp_header(f"=?base64?{encoded}?="),
        )
        self.assertIsNone(_decode_mcp_header("=?base64?invalid!?="))

    def test_openapi_marks_standard_transport_headers_as_required(self) -> None:
        contract = json.loads(
            (ROOT / "app/backend/contracts/openapi.v0.1.json").read_text(
                encoding="utf-8"
            )
        )
        parameters = contract["paths"]["/mcp"]["post"]["parameters"]
        required = {
            parameter["name"]: parameter["required"]
            for parameter in parameters
        }
        self.assertTrue(required["MCP-Protocol-Version"])
        self.assertTrue(required["Mcp-Method"])

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


class McpTransportContractTest(unittest.IsolatedAsyncioTestCase):
    async def _post(
        self,
        payload: object,
        *,
        protocol_version: str | None = MCP_PROTOCOL_VERSION,
        method_header: str | None = "server/discover",
        name_header: str | None = None,
    ) -> tuple[int, dict[str, object]]:
        response = await mcp_post(
            _StubRequest(payload),  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            protocol_version,
            method_header,
            name_header,
        )
        return response.status_code, json.loads(response.body)

    async def test_discovery_is_stateless_and_self_describing(self) -> None:
        status, body = await self._post(_request_payload())

        self.assertEqual(200, status)
        result = body["result"]
        self.assertEqual("complete", result["resultType"])
        self.assertEqual([MCP_PROTOCOL_VERSION], result["supportedVersions"])
        self.assertEqual(
            MCP_SERVER_INFO,
            result["_meta"]["io.modelcontextprotocol/serverInfo"],
        )

    async def test_fastapi_missing_header_error_uses_mcp_contract(self) -> None:
        from app.main import validation_error

        request = SimpleNamespace(url=SimpleNamespace(path="/mcp"))
        response = await validation_error(
            request,  # type: ignore[arg-type]
            RequestValidationError([]),
        )
        body = json.loads(response.body)

        self.assertEqual(400, response.status_code)
        self.assertEqual(HEADER_MISMATCH, body["error"]["code"])

    async def test_missing_metadata_is_invalid_params_with_http_400(self) -> None:
        payload = _request_payload()
        payload["params"] = {}

        status, body = await self._post(payload)

        self.assertEqual(400, status)
        self.assertEqual(-32602, body["error"]["code"])

    async def test_header_mismatch_uses_protocol_error_and_http_400(self) -> None:
        status, body = await self._post(
            _request_payload(),
            protocol_version=None,
        )
        self.assertEqual(
            (400, HEADER_MISMATCH),
            (status, body["error"]["code"]),
        )

        status, body = await self._post(
            _request_payload(),
            method_header="tools/list",
        )
        self.assertEqual(
            (400, HEADER_MISMATCH),
            (status, body["error"]["code"]),
        )

    async def test_unsupported_version_lists_supported_versions(self) -> None:
        unsupported = "2025-11-25"
        status, body = await self._post(
            _request_payload(version=unsupported),
            protocol_version=unsupported,
        )

        self.assertEqual(400, status)
        self.assertEqual(UNSUPPORTED_PROTOCOL_VERSION, body["error"]["code"])
        self.assertEqual(
            {"supported": [MCP_PROTOCOL_VERSION], "requested": unsupported},
            body["error"]["data"],
        )

    async def test_unknown_method_uses_json_rpc_error_and_http_404(self) -> None:
        status, body = await self._post(
            _request_payload(method="prompts/list"),
            method_header="prompts/list",
        )

        self.assertEqual(404, status)
        self.assertEqual(-32601, body["error"]["code"])

    async def test_discovery_rejects_non_metadata_params(self) -> None:
        status, body = await self._post(
            _request_payload(extra_params={"unexpected": True}),
        )

        self.assertEqual(400, status)
        self.assertEqual(-32602, body["error"]["code"])


if __name__ == "__main__":
    unittest.main()
