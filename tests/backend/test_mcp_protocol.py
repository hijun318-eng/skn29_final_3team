from __future__ import annotations

import ast
import asyncio
import base64
import json
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.api.mcp_router import (
    HEADER_MISMATCH,
    MCP_PROTOCOL_VERSION,
    MCP_SERVER_INFO,
    TOOL_INPUT_SCHEMA,
    TOOL_ID,
    TOOL_NAME,
    TOOL_OUTPUT_SCHEMA,
    TOOL_REQUIRED_ROLES,
    TOOL_SEMANTIC_VERSION,
    TOOL_TIMEOUT_SECONDS,
    TOOL_TRANSPORT,
    TOOL_RATE_LIMITED,
    UNSUPPORTED_PROTOCOL_VERSION,
    _decode_mcp_header,
    _consume_tool_quota,
    _discovery_result,
    _has_request_metadata,
    _origin_allowed,
    _registry_receipt_matches,
    _rpc_result,
    _structured_run_output,
    _tool_output_matches_schema,
    _valid_request_id,
    mcp_post,
)
from app.auth import Principal
from app.contracts import Role
from app.ports.mcp_tool import MCPToolInfrastructureError
from app.services.mcp_tool_rate_limit import McpToolRateLimitDecision


ROOT = Path(__file__).resolve().parents[2]


class _StubRequest:
    def __init__(self, payload: object, *, origin: str | None = None) -> None:
        self._payload = payload
        self.headers = {} if origin is None else {"Origin": origin}
        self.state = SimpleNamespace(trace_id="mcp-test-trace")

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


def _registry_receipt(*, enabled: bool = True) -> dict[str, object]:
    """현재 analysis.get_run code descriptor와 정확히 일치하는 DB receipt를 만든다."""

    return {
        "tool_id": "c4454392-2f92-54a4-ad13-b8cdaba45732",
        "tool_code": TOOL_NAME,
        "semantic_version": TOOL_SEMANTIC_VERSION,
        "description": "Get one persisted Analysis Run owned by the authenticated user.",
        "input_schema_json": TOOL_INPUT_SCHEMA,
        "output_schema_json": TOOL_OUTPUT_SCHEMA,
        "transport": TOOL_TRANSPORT,
        "timeout_seconds": TOOL_TIMEOUT_SECONDS,
        "required_roles_json": list(TOOL_REQUIRED_ROLES),
        "is_enabled": enabled,
    }


class McpProtocolTest(unittest.TestCase):
    def test_contract_is_one_read_only_owner_scoped_tool(self) -> None:
        self.assertEqual("2026-07-28", MCP_PROTOCOL_VERSION)
        self.assertEqual("analysis.get_run", TOOL_NAME)
        self.assertEqual(["request_id"], TOOL_INPUT_SCHEMA["required"])
        self.assertFalse(TOOL_INPUT_SCHEMA["additionalProperties"])
        self.assertFalse(TOOL_OUTPUT_SCHEMA["additionalProperties"])
        self.assertIn("artifact_id", TOOL_OUTPUT_SCHEMA["required"])
        self.assertEqual(42900, TOOL_RATE_LIMITED)
        self.assertFalse(-32099 <= TOOL_RATE_LIMITED <= -32020)

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
        self.assertTrue(_tool_output_matches_schema(projected))
        self.assertFalse(
            _tool_output_matches_schema({**projected, "unexpected": True})
        )
        with self.assertRaises(ValueError):
            _structured_run_output({
                "request_id": "request-1",
                "status": "SUCCEEDED",
                "trace_id": None,
                "query_id": None,
                "artifact_id": None,
            })

    def test_registry_receipt_requires_exact_contract_and_principal_role(self) -> None:
        """부분 일치·schema drift·다른 role은 공개 Tool 승인 receipt가 아니다."""

        principal = Principal(uuid4(), Role.ANALYST)
        receipt = _registry_receipt()
        self.assertTrue(_registry_receipt_matches(receipt, principal))

        mismatches = {
            "semantic_version": "1.0.1",
            "transport": "HTTP",
            "timeout_seconds": 6,
            "required_roles_json": [Role.PLATFORM_ADMIN.value],
            "is_enabled": False,
            "input_schema_json": {**TOOL_INPUT_SCHEMA, "required": []},
            "output_schema_json": {
                **TOOL_OUTPUT_SCHEMA,
                "additionalProperties": True,
            },
        }
        for field, value in mismatches.items():
            with self.subTest(field=field):
                self.assertFalse(
                    _registry_receipt_matches(
                        {**receipt, field: value},
                        principal,
                    )
                )
        self.assertTrue(
            _registry_receipt_matches(
                receipt,
                Principal(uuid4(), Role.PLATFORM_ADMIN),
            )
        )
        self.assertFalse(
            _registry_receipt_matches(
                receipt,
                Principal(uuid4(), Role.REPORT_ADMIN),
            )
        )

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

    def test_cors_exposes_only_retry_after_for_rate_limit_response(self) -> None:
        source = (ROOT / "app/backend/app/main.py").read_text(encoding="utf-8")

        self.assertIn(
            'expose_headers=["X-Request-Id", "X-Trace-Id", "Retry-After"]',
            source,
        )
        for legacy_header in (
            "RateLimit-Limit",
            "RateLimit-Remaining",
            "RateLimit-Reset",
        ):
            self.assertNotIn(legacy_header, source)

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

        closure_source = (
            ROOT
            / "app/backend/migrations/versions/20260831_61_mcp_output_schema_closed.py"
        ).read_text(encoding="utf-8")
        self.assertIn("down_revision = \"20260831_60\"", closure_source)
        self.assertIn("additionalProperties", closure_source)
        self.assertNotIn("ADD COLUMN", closure_source)


class McpTransportContractTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        window_start = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
        self.quota_patcher = patch(
            "app.api.mcp_router._consume_tool_quota",
            new_callable=AsyncMock,
            return_value=McpToolRateLimitDecision(
                allowed=True,
                limit=30,
                remaining=29,
                retry_after_seconds=60,
                window_start=window_start,
                window_end=window_start + timedelta(seconds=60),
            ),
        )
        self.consume_quota = self.quota_patcher.start()

    async def asyncTearDown(self) -> None:
        self.quota_patcher.stop()

    async def _post(
        self,
        payload: object,
        *,
        protocol_version: str | None = MCP_PROTOCOL_VERSION,
        method_header: str | None = "server/discover",
        name_header: str | None = None,
        role: Role = Role.ANALYST,
    ) -> tuple[int, dict[str, object]]:
        response = await mcp_post(
            _StubRequest(payload),  # type: ignore[arg-type]
            Principal(uuid4(), role),
            protocol_version,
            method_header,
            name_header,
        )
        self.last_response = response
        return response.status_code, json.loads(response.body)

    async def _call_tool(
        self,
        arguments: object,
        *,
        role: Role = Role.ANALYST,
    ) -> tuple[int, dict[str, object]]:
        """표준 metadata와 mirrored header를 포함한 Tool 호출을 만든다."""

        return await self._post(
            _request_payload(
                method="tools/call",
                extra_params={"name": TOOL_NAME, "arguments": arguments},
            ),
            method_header="tools/call",
            name_header=TOOL_NAME,
            role=role,
        )

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
        self.assertNotIn("id", body)

    async def test_unidentified_invalid_request_omits_json_rpc_id(self) -> None:
        status, body = await self._post(_request_payload(request_id=True))

        self.assertEqual(400, status)
        self.assertEqual(-32600, body["error"]["code"])
        self.assertNotIn("id", body)

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

    async def test_registry_mismatch_hides_tool_from_list_and_call(self) -> None:
        """전체 registry receipt가 다르면 목록과 직접 호출을 모두 fail-closed 한다."""

        drifted = {
            **_registry_receipt(),
            "output_schema_json": {**TOOL_OUTPUT_SCHEMA, "required": []},
        }
        with patch(
            "app.api.mcp_router._registry_rows",
            AsyncMock(return_value=(drifted,)),
        ) as registry_rows:
            status, listed = await self._post(
                _request_payload(method="tools/list"),
                method_header="tools/list",
            )
            call_payload = _request_payload(
                method="tools/call",
                extra_params={
                    "name": TOOL_NAME,
                    "arguments": {"request_id": str(uuid4())},
                },
            )
            call_status, called = await self._post(
                call_payload,
                method_header="tools/call",
                name_header=TOOL_NAME,
            )

        self.assertEqual(200, status)
        self.assertEqual([], listed["result"]["tools"])
        self.assertEqual(200, call_status)
        self.assertEqual(-32602, called["error"]["code"])
        self.assertEqual(2, registry_rows.await_count)
        self.consume_quota.assert_not_awaited()

    async def test_unknown_tool_is_hidden_without_consuming_quota(self) -> None:
        payload = _request_payload(
            method="tools/call",
            extra_params={"name": "rag.answer", "arguments": {}},
        )

        status, body = await self._post(
            payload,
            method_header="tools/call",
            name_header="rag.answer",
        )

        self.assertEqual(200, status)
        self.assertEqual(-32602, body["error"]["code"])
        self.assertEqual("Unknown or disabled tool", body["error"]["message"])
        self.consume_quota.assert_not_awaited()

    async def test_registry_failure_uses_json_rpc_server_error(self) -> None:
        """Registry 장애가 FastAPI detail 응답으로 wire 계약을 이탈하지 않는다."""

        @asynccontextmanager
        async def unavailable_session(*_args, **_kwargs):
            raise SQLAlchemyError("registry unavailable")
            yield

        with (
            patch(
                "app.api.mcp_router._database_url",
                return_value="postgresql+psycopg://test:test@localhost/test",
            ),
            patch(
                "app.api.mcp_router.session_scope",
                side_effect=unavailable_session,
            ),
        ):
            status, body = await self._post(
                _request_payload(method="tools/list"),
                method_header="tools/list",
            )

        self.assertEqual(503, status)
        self.assertEqual(-32603, body["error"]["code"])
        self.assertEqual(
            "MCP_REGISTRY_UNAVAILABLE",
            body["error"]["data"]["code"],
        )

    async def test_storage_failure_with_unavailable_audit_prioritizes_audit(self) -> None:
        """Tool·감사 저장소가 함께 없으면 감사 불가를 우선해 실패로 닫는다."""

        with (
            patch(
                "app.api.mcp_router._registry_rows",
                AsyncMock(return_value=(_registry_receipt(),)),
            ),
            patch.dict("os.environ", {"APP_RUNTIME_DATABASE_URL": ""}),
        ):
            status, body = await self._call_tool({"request_id": str(uuid4())})

        self.assertEqual(503, status)
        self.assertEqual(-32603, body["error"]["code"])
        self.assertEqual(
            "MCP_AUDIT_UNAVAILABLE",
            body["error"]["data"]["code"],
        )

    async def test_known_tool_permission_denial_is_audited(self) -> None:
        """숨겨진 Tool 존재는 노출하지 않되 known-tool 권한 거부는 감사한다."""

        with (
            patch(
                "app.api.mcp_router._registry_rows",
                AsyncMock(return_value=(_registry_receipt(),)),
            ),
            patch(
                "app.api.mcp_router._record_run",
                AsyncMock(),
            ) as record_run,
        ):
            status, body = await self._call_tool(
                {"request_id": str(uuid4())},
                role=Role.REPORT_ADMIN,
            )

        self.assertEqual(200, status)
        self.assertEqual(-32602, body["error"]["code"])
        self.assertEqual("DENIED", record_run.await_args.args[3])
        self.assertEqual("ACCESS_DENIED", record_run.await_args.args[6])
        self.consume_quota.assert_not_awaited()

    async def test_invalid_tool_arguments_are_audited(self) -> None:
        """활성·허용 Tool의 schema 오류를 실행 실패 감사로 남긴다."""

        with (
            patch(
                "app.api.mcp_router._registry_rows",
                AsyncMock(return_value=(_registry_receipt(),)),
            ),
            patch(
                "app.api.mcp_router._record_run",
                AsyncMock(),
            ) as record_run,
        ):
            status, body = await self._call_tool({"request_id": "not-a-uuid"})

        self.assertEqual(200, status)
        self.assertEqual(-32602, body["error"]["code"])
        self.assertEqual("FAILED", record_run.await_args.args[3])
        self.assertEqual("INVALID_ARGUMENT", record_run.await_args.args[6])
        self.consume_quota.assert_awaited_once()

    async def test_allowed_quota_dispatches_and_audits_success(self) -> None:
        request_id = str(uuid4())
        persisted = {
            "request_id": request_id,
            "status": "SUCCEEDED",
            "trace_id": "trace-success",
            "query_id": "query-success",
            "artifact_id": "artifact-success",
        }
        with (
            patch(
                "app.api.mcp_router._registry_rows",
                AsyncMock(return_value=(_registry_receipt(),)),
            ),
            patch(
                "app.api.mcp_router._database_url",
                return_value="postgresql+psycopg://test:test@localhost/test",
            ),
            patch(
                "app.services.mcp_tool_registry.PostgresAnalysisRepository.get_run",
                AsyncMock(return_value=persisted),
            ) as get_run,
            patch(
                "app.api.mcp_router._record_run",
                AsyncMock(),
            ) as record_run,
        ):
            status, body = await self._call_tool({"request_id": request_id})

        self.assertEqual(200, status)
        self.assertEqual(persisted, body["result"]["structuredContent"])
        self.consume_quota.assert_awaited_once()
        get_run.assert_awaited_once_with(request_id)
        self.assertEqual("SUCCEEDED", record_run.await_args.args[3])

    async def test_quota_denial_is_audited_then_returns_429_without_dispatch(self) -> None:
        window_start = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
        self.consume_quota.return_value = McpToolRateLimitDecision(
            allowed=False,
            limit=30,
            remaining=0,
            retry_after_seconds=17,
            window_start=window_start,
            window_end=window_start + timedelta(seconds=60),
        )
        with (
            patch(
                "app.api.mcp_router._registry_rows",
                AsyncMock(return_value=(_registry_receipt(),)),
            ),
            patch(
                "app.services.mcp_tool_registry.PostgresAnalysisRepository.get_run",
                AsyncMock(),
            ) as get_run,
            patch(
                "app.api.mcp_router._record_run",
                AsyncMock(),
            ) as record_run,
        ):
            status, body = await self._call_tool({"request_id": str(uuid4())})

        self.assertEqual(429, status)
        self.assertEqual(TOOL_RATE_LIMITED, body["error"]["code"])
        self.assertEqual(
            {
                "code": "RATE_LIMITED",
                "limit": 30,
                "remaining": 0,
                "retryAfterSeconds": 17,
                "resetAt": "2026-08-31T00:01:00Z",
            },
            body["error"]["data"],
        )
        self.assertEqual("17", self.last_response.headers["Retry-After"])
        self.assertEqual("no-store", self.last_response.headers["Cache-Control"])
        self.assertNotIn("RateLimit-Limit", self.last_response.headers)
        get_run.assert_not_awaited()
        self.assertEqual("DENIED", record_run.await_args.args[3])
        self.assertEqual("RATE_LIMITED", record_run.await_args.args[6])

    async def test_quota_denial_audit_failure_has_503_priority(self) -> None:
        window_start = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
        self.consume_quota.return_value = McpToolRateLimitDecision(
            allowed=False,
            limit=30,
            remaining=0,
            retry_after_seconds=17,
            window_start=window_start,
            window_end=window_start + timedelta(seconds=60),
        )
        with (
            patch(
                "app.api.mcp_router._registry_rows",
                AsyncMock(return_value=(_registry_receipt(),)),
            ),
            patch(
                "app.api.mcp_router._record_run",
                AsyncMock(
                    side_effect=MCPToolInfrastructureError(
                        "MCP_AUDIT_UNAVAILABLE"
                    )
                ),
            ),
        ):
            status, body = await self._call_tool({"request_id": str(uuid4())})

        self.assertEqual(503, status)
        self.assertEqual(-32603, body["error"]["code"])
        self.assertEqual("MCP_AUDIT_UNAVAILABLE", body["error"]["data"]["code"])
        self.assertNotIn("Retry-After", self.last_response.headers)

    async def test_quota_storage_failure_is_audited_before_503(self) -> None:
        self.consume_quota.side_effect = MCPToolInfrastructureError(
            "MCP_RATE_LIMIT_UNAVAILABLE"
        )
        with (
            patch(
                "app.api.mcp_router._registry_rows",
                AsyncMock(return_value=(_registry_receipt(),)),
            ),
            patch(
                "app.api.mcp_router._record_run",
                AsyncMock(),
            ) as record_run,
        ):
            status, body = await self._call_tool({"request_id": str(uuid4())})

        self.assertEqual(503, status)
        self.assertEqual(-32603, body["error"]["code"])
        self.assertEqual(
            "MCP_RATE_LIMIT_UNAVAILABLE",
            body["error"]["data"]["code"],
        )
        self.assertEqual("FAILED", record_run.await_args.args[3])
        self.assertEqual(
            "MCP_RATE_LIMIT_UNAVAILABLE",
            record_run.await_args.args[6],
        )

    async def test_dispatcher_infrastructure_failure_is_audited_before_503(self) -> None:
        with (
            patch(
                "app.api.mcp_router._registry_rows",
                AsyncMock(return_value=(_registry_receipt(),)),
            ),
            patch(
                "app.api.mcp_router.MCPToolDispatcher.dispatch",
                AsyncMock(
                    side_effect=MCPToolInfrastructureError("MCP_TOOL_UNAVAILABLE")
                ),
            ),
            patch(
                "app.api.mcp_router._record_run",
                AsyncMock(),
            ) as record_run,
        ):
            status, body = await self._call_tool({"request_id": str(uuid4())})

        self.assertEqual(503, status)
        self.assertEqual(-32603, body["error"]["code"])
        self.assertEqual("MCP_TOOL_UNAVAILABLE", body["error"]["data"]["code"])
        self.assertEqual("FAILED", record_run.await_args.args[3])
        self.assertEqual("MCP_TOOL_UNAVAILABLE", record_run.await_args.args[6])

    async def test_audit_failure_uses_json_rpc_server_error(self) -> None:
        """감사 저장 실패 시 Tool 오류를 성공처럼 반환하지 않는다."""

        @asynccontextmanager
        async def unavailable_session(*_args, **_kwargs):
            raise SQLAlchemyError("audit unavailable")
            yield

        with (
            patch(
                "app.api.mcp_router._registry_rows",
                AsyncMock(return_value=(_registry_receipt(),)),
            ),
            patch(
                "app.api.mcp_router._database_url",
                return_value="postgresql+psycopg://test:test@localhost/test",
            ),
            patch(
                "app.api.mcp_router.session_scope",
                side_effect=unavailable_session,
            ),
        ):
            status, body = await self._call_tool({"request_id": "not-a-uuid"})

        self.assertEqual(503, status)
        self.assertEqual(-32603, body["error"]["code"])
        self.assertEqual(
            "MCP_AUDIT_UNAVAILABLE",
            body["error"]["data"]["code"],
        )

    async def test_tool_call_applies_registry_timeout_and_audits_failure(self) -> None:
        """registry의 timeout을 실제 조회에 적용하고 값을 꾸미지 않고 실패한다."""

        async def raise_timeout(awaitable, *, timeout):
            self.assertEqual(TOOL_TIMEOUT_SECONDS, timeout)
            awaitable.close()
            raise TimeoutError

        request_id = str(uuid4())
        with (
            patch(
                "app.api.mcp_router._registry_rows",
                AsyncMock(return_value=(_registry_receipt(),)),
            ),
            patch(
                "app.api.mcp_router._database_url",
                return_value="postgresql+psycopg://test:test@localhost/test",
            ),
            patch(
                "app.services.mcp_tool_registry.PostgresAnalysisRepository.get_run",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.mcp_tool_registry.asyncio.wait_for",
                side_effect=raise_timeout,
            ),
            patch(
                "app.api.mcp_router._record_run",
                AsyncMock(),
            ) as record_run,
        ):
            status, body = await self._call_tool({"request_id": request_id})

        self.assertEqual(200, status)
        self.assertTrue(body["result"]["isError"])
        self.assertNotIn("structuredContent", body["result"])
        self.assertEqual("FAILED", record_run.await_args.args[3])
        self.assertEqual("TOOL_TIMEOUT", record_run.await_args.args[6])

    async def test_unexpected_tool_failure_is_audited_without_leaking_details(self) -> None:
        """예상 밖 실행 예외도 감사하고 내부 오류 문자열은 응답에서 제거한다."""

        request_id = str(uuid4())
        with (
            patch(
                "app.api.mcp_router._registry_rows",
                AsyncMock(return_value=(_registry_receipt(),)),
            ),
            patch(
                "app.api.mcp_router._database_url",
                return_value="postgresql+psycopg://test:test@localhost/test",
            ),
            patch(
                "app.services.mcp_tool_registry.PostgresAnalysisRepository.get_run",
                AsyncMock(side_effect=SQLAlchemyError("secret-dsn")),
            ),
            patch(
                "app.api.mcp_router._record_run",
                AsyncMock(),
            ) as record_run,
        ):
            status, body = await self._call_tool({"request_id": request_id})

        self.assertEqual(200, status)
        self.assertTrue(body["result"]["isError"])
        self.assertNotIn("secret-dsn", json.dumps(body))
        self.assertEqual("FAILED", record_run.await_args.args[3])
        self.assertEqual("TOOL_EXECUTION_FAILED", record_run.await_args.args[6])

    async def test_tool_cancellation_is_not_converted_to_a_failure(self) -> None:
        """quota 소비 뒤 요청 취소는 실행 실패로 감사하지 않고 상위로 전파한다."""

        with (
            patch(
                "app.api.mcp_router._registry_rows",
                AsyncMock(return_value=(_registry_receipt(),)),
            ),
            patch(
                "app.api.mcp_router._database_url",
                return_value="postgresql+psycopg://test:test@localhost/test",
            ),
            patch(
                "app.services.mcp_tool_registry.PostgresAnalysisRepository.get_run",
                AsyncMock(side_effect=asyncio.CancelledError),
            ),
            patch(
                "app.api.mcp_router._record_run",
                AsyncMock(),
            ) as record_run,
        ):
            with self.assertRaises(asyncio.CancelledError):
                await self._call_tool({"request_id": str(uuid4())})

        record_run.assert_not_awaited()
        self.consume_quota.assert_awaited_once()


class McpRateLimitWiringTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_quota_configuration_is_normalized_fail_closed(self) -> None:
        with (
            patch(
                "app.api.mcp_router._database_url",
                return_value="postgresql+psycopg://test:test@localhost/test",
            ),
            patch("app.api.mcp_router.get_sessionmaker", return_value=object()),
            patch.dict("os.environ", {}, clear=True),
        ):
            with self.assertRaises(MCPToolInfrastructureError) as raised:
                await _consume_tool_quota(
                    Principal(uuid4(), Role.ANALYST),
                    TOOL_ID,
                )

        self.assertEqual("MCP_RATE_LIMIT_UNAVAILABLE", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
