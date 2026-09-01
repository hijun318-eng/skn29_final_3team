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
                "/analysis/ml",
                "/analysis/progress/{trace_id}",
                "/analysis/progress/{trace_id}/poll",
                "/analysis/progress/{trace_id}/cancel",
                "/analysis/requests/{request_id}/progress",
                "/analysis/requests/{request_id}/cancel",
                "/analysis/definitions",
                "/analysis/definitions/{definition_id}",
                "/analysis/definitions/{definition_id}/runs",
                "/analysis/artifacts/{artifact_id}/archive",
                "/analysis/artifacts/{artifact_id}/restore",
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
                "/ml/capabilities",
                "/rag/documents",
                "/rag/documents/{manual_id}/source",
                "/rag/documents/{manual_id}/source.pdf",
                "/rag/query",
                "/readiness",
                "/reports/definitions",
                "/reports/definitions/{definition_id}",
                "/reports/drafts/from-analysis-artifact",
                "/reports/definitions/{definition_id}/versions/{version}/approve",
                "/reports/definitions/{definition_id}/versions/{version}/document",
                "/reports/definitions/{definition_id}/versions/{version}/document.html",
                "/reports/definitions/{definition_id}/versions/{version}/document.pdf",
                "/reports/definitions/{definition_id}/versions/{version}/artifacts/{artifact_id}",
                "/reports/definitions/{definition_id}/versions/{version}/drafts",
                "/reports/definitions/{definition_id}/versions/{version}",
                "/reports/definitions/{definition_id}/versions/{version}/blocks",
                "/reports/definitions/{definition_id}/archive",
                "/reports/definitions/{definition_id}/restore",
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
                "/reports/assistant/sessions/{assistant_request_id}/cancel",
                "/reports/assistant/sessions/{assistant_request_id}/evaluation",
                "/reports/assistant/sessions/{assistant_request_id}/external-transfer-consent",
                "/reports/assistant/sessions/{assistant_request_id}/external-transfer-disclosure",
                "/reports/assistant/sessions/{assistant_request_id}/messages",
                "/reports/assistant/sessions/{assistant_request_id}/patch-approval",
                "/reports/assistant/sessions/{assistant_request_id}/retry",
                "/reports/assistant/sessions/{assistant_request_id}/review",
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
                "createMlAnalysis",
                "getAnalysisProgress",
                "pollAnalysisProgress",
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
                "analysisArchiveArtifact",
                "analysisRestoreArtifact",
                "createConversation",
                "getConversationTurns",
                "executeConversationCommand",
                "getMlCapabilities",
                "queryInternalManual",
                "listInternalManuals",
                "getInternalManualSource",
                "getInternalManualPdf",
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
                "reportArchiveDefinition",
                "reportRestoreDefinition",
                "reportPermanentlyDeleteDefinition",
                "reportListRuns",
                "reportCreateManualRunCommand",
                "reportGetRun",
                "reportCreateSchedule",
                "reportListSchedules",
                "reportUpdateSchedule",
                "reportRunDueSchedule",
                "reportAssistantLegacyDraftGone",
                "reportAssistantOperationsFailures",
                "reportAssistantOperationsSummary",
                "reportAssistantCreateSession",
                "reportAssistantGetSession",
                "reportAssistantCancelSession",
                "reportAssistantDecidePlan",
                "reportAssistantGetEvaluation",
                "reportAssistantGetExternalTransferDisclosure",
                "reportAssistantAcceptExternalTransfer",
                "reportAssistantReview",
                "reportAssistantSubmitMessage",
                "reportAssistantDecidePatch",
                "reportAssistantRetrySession",
                "mcpGet",
                "mcpDelete",
                "mcpPost",
            },
            operation_ids,
        )
        self.assertNotIn("post", committed["paths"]["/reports/runs"])

    def test_generic_rag_source_advertises_pdf_and_docx_without_conversion(self) -> None:
        """generic 원문 경로는 PDF와 DOCX를 서로 다른 media type으로 공개한다."""

        response = app.openapi()["paths"]["/rag/documents/{manual_id}/source"][
            "get"
        ]["responses"]["200"]
        self.assertEqual(
            {
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            },
            set(response["content"]),
        )

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

    def test_report_assistant_page_receipts_and_internal_sixth_artifact_are_publicly_bounded(self) -> None:
        """응답은 target/actual과 최대 5+result를 공개하고 요청에는 exact를 강요하지 않는다."""

        schemas = app.openapi()["components"]["schemas"]
        session = schemas["ReportAssistantSessionResponse"]["properties"]
        self.assertEqual(1, session["artifact_ids"]["minItems"])
        self.assertEqual(6, session["artifact_ids"]["maxItems"])
        self.assertTrue(session["artifact_ids"]["uniqueItems"])
        self.assertIn("첫 번째", session["artifact_ids"]["description"])
        self.assertIn("exact_page_count", session)
        self.assertIn("verified_page_count", session)
        self.assertEqual(20, session["exact_page_count"]["anyOf"][0]["maximum"])
        self.assertNotIn("maximum", session["verified_page_count"]["anyOf"][0])
        error = schemas["ErrorBody"]["properties"]
        self.assertEqual(20, error["exact_page_count"]["anyOf"][0]["maximum"])
        self.assertEqual(1, error["verified_page_count"]["anyOf"][0]["minimum"])
        self.assertNotIn("maximum", error["verified_page_count"]["anyOf"][0])
        self.assertIn(
            "REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED",
            schemas["ErrorCode"]["enum"],
        )
        patch_approval = app.openapi()["paths"][
            "/reports/assistant/sessions/{assistant_request_id}/patch-approval"
        ]["post"]["responses"]
        for status in ("409", "502"):
            with self.subTest(status=status):
                self.assertEqual(
                    "#/components/schemas/ErrorResponse",
                    patch_approval[status]["content"]["application/json"]["schema"]["$ref"],
                )
        for request_name in (
            "CreateReportAssistantSessionRequest",
            "ReportAssistantMessageRequest",
            "ReportAssistantPatchApprovalRequest",
        ):
            with self.subTest(request=request_name):
                self.assertNotIn(
                    "exact_page_count", schemas[request_name]["properties"]
                )

    def test_report_assistant_external_transfer_consent_is_explicit_and_bounded(self) -> None:
        """외부 전송은 서버 disclosure와 accepted=true만 받으며 모든 모델 경로가 428을 공개한다."""

        schema = app.openapi()
        schemas = schema["components"]["schemas"]
        consent = schemas["ReportAssistantExternalTransferConsentRequest"]
        self.assertFalse(consent["additionalProperties"])
        self.assertEqual(
            {"disclosure_id", "disclosure_hash", "accepted"},
            set(consent["properties"]),
        )
        self.assertEqual(set(consent["required"]), set(consent["properties"]))
        self.assertIs(consent["properties"]["accepted"]["const"], True)
        self.assertEqual(
            "^[0-9a-f]{64}$", consent["properties"]["disclosure_hash"]["pattern"]
        )

        paths = schema["paths"]
        disclosure_path = (
            "/reports/assistant/sessions/{assistant_request_id}"
            "/external-transfer-disclosure"
        )
        consent_path = (
            "/reports/assistant/sessions/{assistant_request_id}"
            "/external-transfer-consent"
        )
        self.assertEqual(
            "#/components/schemas/ReportAssistantExternalTransferDisclosureResponse",
            paths[disclosure_path]["get"]["responses"]["200"]["content"]
            ["application/json"]["schema"]["$ref"],
        )
        self.assertEqual(
            "#/components/schemas/ReportAssistantExternalTransferConsentRequest",
            paths[consent_path]["post"]["requestBody"]["content"]
            ["application/json"]["schema"]["$ref"],
        )
        self.assertEqual(
            "#/components/schemas/ReportAssistantExternalTransferConsentResponse",
            paths[consent_path]["post"]["responses"]["200"]["content"]
            ["application/json"]["schema"]["$ref"],
        )
        for action in ("messages", "review", "approval"):
            with self.subTest(action=action):
                response = paths[
                    f"/reports/assistant/sessions/{{assistant_request_id}}/{action}"
                ]["post"]["responses"]["428"]
                self.assertEqual(
                    "#/components/schemas/ReportAssistantExternalTransferErrorResponse",
                    response["content"]["application/json"]["schema"]["$ref"],
                )

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
        self.assertIn("permission_snapshot_id", evidence)
        self.assertIn("semantic_release_id", evidence)
        self.assertIn("evidence_cutoff", evidence)
        metric_reference = schema["components"]["schemas"]["MetricReference"]["properties"]
        self.assertIn("display_label", metric_reference)
        self.assertIn("display_unit", metric_reference)

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
