from __future__ import annotations

import unittest

from src.rag.integration.contracts import (
    DocumentEvidence,
    IntegrationContext,
    ToolRegistration,
)
from src.rag.integration.coordinator import ToolCallError
from src.rag.integration.mcp_dispatcher import McpJsonRpcDispatcher
from src.rag.integration.rate_limit import ProcessLocalToolRateLimiter
from src.rag.integration.sql_adapter import (
    ApprovedSqlEvidenceAdapter,
    ApprovedSqlPlan,
)
from src.rag.integration.tool_service import (
    DocumentSearchToolHandler,
    RegistryToolService,
    SqlEvidenceToolHandler,
)


class FakePlanResolver:
    def __init__(self, approved: bool = True) -> None:
        self._approved = approved

    def resolve(self, question: str, context: IntegrationContext) -> ApprovedSqlPlan:
        return ApprovedSqlPlan(
            sql="SELECT synthetic_value FROM approved_view",
            parameters={"as_of": context.as_of},
            gate_token="g2-approved",
            source_refs=("urn:dataset:approved_view",),
            policy_version="SQL-POLICY-v1",
            approved=self._approved,
        )


class FakeDataPlatform:
    def __init__(self, status: str = "SUCCEEDED", evidence_complete: bool = True) -> None:
        self._status = status
        self._evidence_complete = evidence_complete

    def execute_query(self, sql, parameters, gate_token):
        return {"query_id": "query-1"}

    def get_query_status(self, query_id):
        return {
            "query_id": query_id,
            "status": self._status,
            "rows": [{"synthetic_value": 1}],
            "evidence_complete": self._evidence_complete,
        }


class FakeDocumentPort:
    def __init__(self) -> None:
        self.last_context = None

    def search(self, question, context):
        self.last_context = context
        return (
            DocumentEvidence(
                document_id="POL-001",
                document_title="정책",
                document_version="1.0",
                citation="[POL-001 v1.0 p.1-1]",
                snippet="정책 근거",
                score=0.9,
            ),
        )


class FakeRegistry:
    def __init__(self, registration: ToolRegistration) -> None:
        self.registration = registration

    def load(self, tool_codes):
        return (
            {self.registration.tool_code: self.registration}
            if self.registration.tool_code in tool_codes
            else {}
        )

    def list_callable(self, role):
        return (self.registration,) if self.registration.callable_by(role) else ()


class EchoHandler:
    def call(self, arguments, context):
        return arguments


class BrokenHandler:
    def call(self, arguments, context):
        raise RuntimeError("database password must not escape")


class ToolIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = IntegrationContext(
            request_id="request-1",
            trace_id="trace-1",
            actor_id="actor-1",
            role="hotel_analyst",
            as_of="2026-08-04",
        )

    def test_approved_sql_adapter_uses_existing_data_platform_contract(self) -> None:
        adapter = ApprovedSqlEvidenceAdapter(FakeDataPlatform(), FakePlanResolver())
        evidence = adapter.query("매출", self.context)
        self.assertEqual(evidence.query_id, "query-1")
        self.assertEqual(evidence.as_of, "2026-08-04")
        self.assertEqual(evidence.observed_facts[0]["synthetic_value"], 1)

    def test_unapproved_sql_and_incomplete_evidence_are_blocked(self) -> None:
        with self.assertRaisesRegex(ToolCallError, "SQL_PLAN_NOT_APPROVED"):
            ApprovedSqlEvidenceAdapter(
                FakeDataPlatform(), FakePlanResolver(approved=False)
            ).query("매출", self.context)
        with self.assertRaisesRegex(ToolCallError, "SQL_EVIDENCE_INCOMPLETE"):
            ApprovedSqlEvidenceAdapter(
                FakeDataPlatform(evidence_complete=False), FakePlanResolver()
            ).query("매출", self.context)

    def test_tool_service_lists_and_calls_only_approved_tools(self) -> None:
        registration = self._registration(enabled=True, approval="APPROVED")
        service = RegistryToolService(
            FakeRegistry(registration),
            {registration.tool_code: DocumentSearchToolHandler(FakeDocumentPort())},
        )
        listed = service.list_tools("hotel_analyst")
        result = service.call_tool(
            registration.tool_code, {"query": "정책"}, self.context
        )
        self.assertEqual(len(listed), 1)
        self.assertEqual(result["evidence_type"], "DOCUMENT_EVIDENCE")
        self.assertEqual(result["document_evidence"][0]["document_id"], "POL-001")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["trace_id"], "trace-1")

    def test_tool_service_blocks_disabled_and_invalid_calls(self) -> None:
        disabled = self._registration(enabled=False, approval="NOT_APPROVED")
        service = RegistryToolService(
            FakeRegistry(disabled),
            {disabled.tool_code: DocumentSearchToolHandler(FakeDocumentPort())},
        )
        self.assertEqual(service.list_tools("hotel_analyst"), ())
        with self.assertRaisesRegex(ToolCallError, "TOOL_NOT_APPROVED"):
            service.call_tool(disabled.tool_code, {"query": "정책"}, self.context)

        approved = self._registration(enabled=True, approval="APPROVED")
        handler = DocumentSearchToolHandler(FakeDocumentPort())
        with self.assertRaisesRegex(ToolCallError, "TOOL_INPUT_SCHEMA_INVALID"):
            handler.call({"query": "정책", "role": "data_admin"}, self.context)

    def test_sql_tool_handler_keeps_sql_evidence_type(self) -> None:
        adapter = ApprovedSqlEvidenceAdapter(FakeDataPlatform(), FakePlanResolver())
        result = SqlEvidenceToolHandler(adapter).call({"query": "매출"}, self.context)
        self.assertEqual(result["evidence_type"], "SQL_EVIDENCE")
        self.assertNotIn("document_evidence", result)

    def test_document_tool_passes_bounded_conversation_context(self) -> None:
        port = FakeDocumentPort()
        handler = DocumentSearchToolHandler(port)
        handler.call(
            {
                "query": "그 다음 절차는?",
                "recent_utterances": ["예약 선수금이 미입금됐어"],
                "selected_document_ids": ["SOP-FRT-003"],
            },
            self.context,
        )
        self.assertEqual(
            port.last_context.recent_utterances,
            ("예약 선수금이 미입금됐어",),
        )
        self.assertEqual(
            port.last_context.selected_document_ids,
            ("SOP-FRT-003",),
        )
        with self.assertRaisesRegex(ToolCallError, "TOOL_INPUT_SCHEMA_INVALID"):
            handler.call(
                {"query": "질문", "recent_utterances": "문자열은 배열이 아님"},
                self.context,
            )
        with self.assertRaisesRegex(ToolCallError, "TOOL_INPUT_SCHEMA_INVALID"):
            handler.call(
                {"query": "질문", "recent_utterances": ["이전"] * 4},
                self.context,
            )

    def test_mcp_tools_list_and_call_follow_json_rpc_contract(self) -> None:
        registration = self._registration(enabled=True, approval="APPROVED")
        service = RegistryToolService(
            FakeRegistry(registration),
            {registration.tool_code: DocumentSearchToolHandler(FakeDocumentPort())},
        )
        dispatcher = McpJsonRpcDispatcher(service)
        listed = dispatcher.dispatch(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            self.context,
        )
        called = dispatcher.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": registration.tool_code, "arguments": {"query": "정책"}},
            },
            self.context,
        )
        self.assertEqual(listed["result"]["tools"][0]["inputSchema"]["type"], "object")
        self.assertFalse(called["result"]["isError"])
        self.assertEqual(called["result"]["content"][0]["type"], "text")

    def test_mcp_unknown_tool_is_protocol_error(self) -> None:
        registration = self._registration(enabled=True, approval="APPROVED")
        dispatcher = McpJsonRpcDispatcher(RegistryToolService(FakeRegistry(registration), {}))
        response = dispatcher.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "unknown", "arguments": {}},
            },
            self.context,
        )
        self.assertEqual(response["error"]["code"], -32602)

    def test_tool_calls_are_rate_limited_per_actor(self) -> None:
        registration = self._registration(enabled=True, approval="APPROVED")
        service = RegistryToolService(
            FakeRegistry(registration),
            {registration.tool_code: DocumentSearchToolHandler(FakeDocumentPort())},
            ProcessLocalToolRateLimiter(maximum_calls=1, window_seconds=60),
        )
        service.call_tool(registration.tool_code, {"query": "정책"}, self.context)
        with self.assertRaisesRegex(ToolCallError, "TOOL_RATE_LIMITED"):
            service.call_tool(registration.tool_code, {"query": "정책"}, self.context)

    def test_registry_enforces_registered_input_schema(self) -> None:
        registration = self._registration(enabled=True, approval="APPROVED")
        service = RegistryToolService(
            FakeRegistry(registration), {registration.tool_code: EchoHandler()}
        )
        with self.assertRaisesRegex(ToolCallError, "TOOL_INPUT_SCHEMA_INVALID"):
            service.call_tool(
                registration.tool_code,
                {"query": "valid query", "unexpected": True},
                self.context,
            )

    def test_registry_rejects_invalid_context(self) -> None:
        registration = self._registration(enabled=True, approval="APPROVED")
        service = RegistryToolService(
            FakeRegistry(registration), {registration.tool_code: EchoHandler()}
        )
        invalid = IntegrationContext(
            request_id="",
            trace_id="trace-1",
            actor_id="actor-1",
            role="hotel_analyst",
            as_of="2026-08-04",
        )
        with self.assertRaisesRegex(ToolCallError, "TOOL_CONTEXT_INVALID"):
            service.call_tool(registration.tool_code, {"query": "valid query"}, invalid)

    def test_registry_redacts_unexpected_handler_error(self) -> None:
        registration = self._registration(enabled=True, approval="APPROVED")
        service = RegistryToolService(
            FakeRegistry(registration), {registration.tool_code: BrokenHandler()}
        )
        with self.assertRaisesRegex(ToolCallError, "^TOOL_INTERNAL_ERROR$"):
            service.call_tool(
                registration.tool_code, {"query": "valid query"}, self.context
            )

    def test_registry_enforces_output_schema(self) -> None:
        base = self._registration(enabled=True, approval="APPROVED")
        registration = ToolRegistration(
            **{
                **base.__dict__,
                "output_schema_json": {
                    "type": "object",
                    "required": ["result"],
                    "properties": {"result": {"type": "string"}},
                    "additionalProperties": False,
                },
            }
        )
        service = RegistryToolService(
            FakeRegistry(registration), {registration.tool_code: EchoHandler()}
        )
        with self.assertRaisesRegex(ToolCallError, "TOOL_OUTPUT_SCHEMA_INVALID"):
            service.call_tool(
                registration.tool_code, {"query": "valid query"}, self.context
            )

    def test_schema_validator_handles_union_pattern_and_number_bounds(self) -> None:
        RegistryToolService._assert_schema(None, {"type": ["string", "null"]})
        RegistryToolService._assert_schema(
            "SOP-ROOM-003", {"type": "string", "pattern": r"[A-Z][A-Z0-9-]+"}
        )
        RegistryToolService._assert_schema(5, {"type": "integer", "minimum": 1, "maximum": 10})
        with self.assertRaises(ValueError):
            RegistryToolService._assert_schema("bad id", {"type": "string", "pattern": r"[A-Z-]+"})
        with self.assertRaises(ValueError):
            RegistryToolService._assert_schema(11, {"type": "integer", "maximum": 10})

    def test_document_handler_matches_registered_output_contract(self) -> None:
        base = self._registration(enabled=True, approval="APPROVED")
        registration = ToolRegistration(
            **{
                **base.__dict__,
                "output_schema_json": {
                    "type": "object",
                    "required": ["request_id", "document_evidence", "warnings"],
                    "properties": {
                        "request_id": {"type": "string"},
                        "document_evidence": {"type": "array"},
                        "warnings": {"type": "array"},
                    },
                },
            }
        )
        service = RegistryToolService(
            FakeRegistry(registration),
            {registration.tool_code: DocumentSearchToolHandler(FakeDocumentPort())},
        )
        result = service.call_tool(
            registration.tool_code, {"query": "정책"}, self.context
        )
        self.assertEqual(result["request_id"], self.context.request_id)
        self.assertEqual(len(result["document_evidence"]), 1)

    @staticmethod
    def _registration(enabled: bool, approval: str) -> ToolRegistration:
        return ToolRegistration(
            tool_code="internal-manual-search",
            semantic_version="0.4.0-poc",
            evidence_type="DOCUMENT_EVIDENCE",
            enabled=enabled,
            approval_status=approval,
            required_roles=frozenset({"hotel_analyst"}),
            title="Internal manual search",
            description="Return document evidence.",
            input_schema_json={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string", "minLength": 2}},
                "additionalProperties": False,
            },
            health_status="HEALTHY",
        )


if __name__ == "__main__":
    unittest.main()
