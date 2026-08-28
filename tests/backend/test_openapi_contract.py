from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
CONTRACTS = BACKEND / "contracts"
FIXTURES = ROOT / "tests" / "backend" / "fixtures" / "api" / "v0.1"
sys.path.insert(0, str(BACKEND))

from app.contract_examples import STATE_MAPPING, contract_fixtures  # noqa: E402
from app.contracts import (  # noqa: E402
    AnalysisResponse,
    AnalysisStatus,
    CONTRACT_VERSION,
    OPENAPI_DOCUMENT_VERSION,
)
from app.main import app  # noqa: E402


class OpenApiContractTest(unittest.TestCase):
    def test_committed_openapi_matches_fastapi(self) -> None:
        committed = json.loads(
            (CONTRACTS / "openapi.v0.1.json").read_text(encoding="utf-8")
        )

        self.assertEqual(app.openapi(), committed)
        self.assertEqual(OPENAPI_DOCUMENT_VERSION, committed["info"]["version"])
        self.assertEqual("OPENAPI-v1.0.0", CONTRACT_VERSION)
        self.assertEqual(
            {
                "/admin/accounts",
                "/admin/accounts/{subject}",
                "/admin/accounts/{subject}/password",
                "/admin/audit-events",
                "/admin/audit-trails",
                "/admin/audit-trails/{trail_id}",
                "/admin/connections",
                "/analysis",
                "/analysis/progress/{trace_id}",
                "/analysis/progress/{trace_id}/cancel",
                "/analysis/requests/{request_id}/progress",
                "/analysis/requests/{request_id}/cancel",
                "/analysis/definitions",
                "/analysis/definitions/{definition_id}",
                "/analysis/definitions/{definition_id}/runs",
                "/analysis/runs",
                "/analysis/runs/{request_id}",
                "/analysis/runs/{request_id}/artifact",
                "/auth/session",
                "/auth/login",
                "/auth/logout",
                "/conversations",
                "/conversations/{conversation_id}/commands",
                "/conversations/{conversation_id}/turns",
                "/health",
                "/mcp",
                "/readiness",
                "/reports/definitions",
                "/reports/drafts/from-analysis-artifact",
                "/reports/definitions/{definition_id}/versions/{version}/approve",
                "/reports/definitions/{definition_id}/versions/{version}/document",
                "/reports/definitions/{definition_id}/versions/{version}/document.html",
                "/reports/definitions/{definition_id}/versions/{version}/document.pdf",
                "/reports/definitions/{definition_id}/versions/{version}/artifacts/{artifact_id}",
                "/reports/definitions/{definition_id}/versions/{version}/drafts",
                "/reports/definitions/{definition_id}/versions/{version}",
                "/reports/definitions/{definition_id}/versions/{version}/blocks",
                "/reports/runs",
                "/reports/runs/manual",
                "/reports/runs/{run_id}",
                "/reports/schedules",
                "/reports/schedules/{schedule_id}",
                "/reports/schedules/{schedule_id}/run-due",
                "/reports/assistant/drafts",
                "/reports/assistant/operations/failures",
                "/reports/assistant/operations/summary",
                "/reports/assistant/sessions",
                "/reports/assistant/sessions/{assistant_request_id}",
                "/reports/assistant/sessions/{assistant_request_id}/approval",
                "/reports/assistant/sessions/{assistant_request_id}/evaluation",
                "/reports/assistant/sessions/{assistant_request_id}/messages",
                "/reports/assistant/sessions/{assistant_request_id}/patch-approval",
                "/reports/assistant/sessions/{assistant_request_id}/retry",
            },
            set(committed["paths"]),
        )
        operation_ids = {
            operation["operationId"]
            for path in committed["paths"].values()
            for operation in path.values()
        }
        self.assertEqual(
            {
                "listAdminAccounts",
                "createAdminAccount",
                "updateAdminAccount",
                "deleteAdminAccount",
                "resetAdminAccountPassword",
                "listAdminConnections",
                "listAdminAuditEvents",
                "listAdminAuditTrails",
                "getAdminAuditTrail",
                "getHealth",
                "getReadiness",
                "getAuthenticatedSession",
                "createAuthenticatedSession",
                "deleteAuthenticatedSession",
                "submitAnalysis",
                "getAnalysisProgress",
                "cancelAnalysisProgress",
                "getAnalysisProgressByRequest",
                "cancelAnalysisProgressByRequest",
                "analysisCreateDefinition",
                "analysisListDefinitions",
                "analysisGetDefinition",
                "analysisReplayDefinition",
                "analysisListRuns",
                "analysisGetRun",
                "analysisGetRunArtifact",
                "createConversation",
                "getConversationTurns",
                "executeConversationCommand",
                "reportCreateDefinition",
                "reportCreateDraftFromAnalysisArtifact",
                "reportListDefinitions",
                "reportApproveVersion",
                "reportGetFinalDocument",
                "reportGetFinalHtml",
                "reportGetFinalPdf",
                "reportCreateNextDraft",
                "reportGetDefinitionVersion",
                "reportGetArtifact",
                "reportReplaceDraftBlocks",
                "reportListRuns",
                "reportCreateManualRunCommand",
                "reportGetRun",
                "reportCreateSchedule",
                "reportListSchedules",
                "reportUpdateSchedule",
                "reportRunDueSchedule",
                "reportAssistantCreateDraft",
                "reportAssistantOperationsFailures",
                "reportAssistantOperationsSummary",
                "reportAssistantCreateSession",
                "reportAssistantGetSession",
                "reportAssistantDecidePlan",
                "reportAssistantGetEvaluation",
                "reportAssistantSubmitMessage",
                "reportAssistantDecidePatch",
                "reportAssistantRetrySession",
                "mcpGet",
                "mcpPost",
            },
            operation_ids,
        )
        self.assertNotIn("post", committed["paths"]["/reports/runs"])

    def test_analysis_persistence_requests_reject_server_owned_fields(self) -> None:
        schemas = app.openapi()["components"]["schemas"]
        for name in ("CreateAnalysisDefinitionRequest", "ReplayAnalysisRequest"):
            with self.subTest(schema=name):
                self.assertFalse(schemas[name]["additionalProperties"])
        run = schemas["AnalysisRunResponse"]["properties"]
        self.assertIn("CANCELLED", run["status"]["enum"])
        self.assertIn("CLARIFYING", run["status"]["enum"])
        self.assertIn("snapshot_cutoff", run)
        self.assertIn("snapshot_selection", run)
        for forbidden in ("sql", "parameters", "result", "snapshot"):
            self.assertNotIn(forbidden, run)

    def test_authenticated_routes_use_server_owned_bearer_identity(self) -> None:
        schema = app.openapi()
        bearer = schema["components"]["securitySchemes"]["BearerAuth"]
        self.assertEqual("http", bearer["type"])
        self.assertEqual("bearer", bearer["scheme"])
        for path, operations in schema["paths"].items():
            if path in {"/health", "/readiness", "/auth/login"}:
                continue
            for operation in operations.values():
                self.assertEqual([{"BearerAuth": []}], operation["security"])
                parameters = {item["name"].lower() for item in operation.get("parameters", [])}
                self.assertNotIn("authorization", parameters)
                self.assertNotIn("x-user-id", parameters)
                self.assertNotIn("x-role", parameters)

    def test_report_request_schemas_reject_additional_properties(self) -> None:
        schemas = app.openapi()["components"]["schemas"]
        for name in (
            "ApproveReportVersionRequest",
            "CreateManualRunRequest",
            "CreateReportDefinitionRequest",
            "CreateReportScheduleRequest",
            "ReplaceReportBlocksRequest",
            "ReportBlockRequest",
            "UpdateReportScheduleRequest",
        ):
            with self.subTest(schema=name):
                self.assertFalse(schemas[name]["additionalProperties"])

    def test_analysis_schema_exposes_result_and_evidence(self) -> None:
        schema = app.openapi()
        analysis_data = schema["components"]["schemas"]["AnalysisData"]
        analysis_result = schema["components"]["schemas"]["AnalysisResult"]

        self.assertIn("result", analysis_data["properties"])
        self.assertIn("trace", analysis_data["properties"])
        self.assertIn("repair_count", analysis_data["properties"])
        self.assertIn("artifact", analysis_data["properties"])
        self.assertIn("evidence", analysis_result["properties"])
        evidence = schema["components"]["schemas"]["Evidence"]["properties"]
        self.assertIn("product_release_id", evidence)
        self.assertIn("evidence_cutoff", evidence)

    def test_all_fixtures_match_typed_response(self) -> None:
        expected_names = set(contract_fixtures())
        actual_names = {path.stem for path in FIXTURES.glob("*.json")}
        self.assertEqual(expected_names, actual_names)

        for path in FIXTURES.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            AnalysisResponse.model_validate(payload)
            self.assertEqual(CONTRACT_VERSION, payload["meta"]["contract_version"])
            serialized = json.dumps(payload).lower()
            for forbidden in ("password", "credential", "stack_trace"):
                self.assertNotIn(forbidden, serialized)

    def test_state_mapping_covers_every_controller_status(self) -> None:
        committed = json.loads(
            (CONTRACTS / "state_mapping.v0.1.json").read_text(encoding="utf-8")
        )

        self.assertEqual(STATE_MAPPING, committed)
        self.assertEqual(
            {status.value for status in AnalysisStatus},
            set(committed["controller_to_api_ui"]),
        )


if __name__ == "__main__":
    unittest.main()
