from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
CONTRACTS = BACKEND / "contracts"
sys.path.insert(0, str(BACKEND))

from app.contract_examples import STATE_MAPPING  # noqa: E402
from app.contracts import (  # noqa: E402
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
                "/analysis",
                "/analysis/{request_id}/progress",
                "/analysis/recent",
                "/analysis/definitions",
                "/analysis/definitions/{definition_id}",
                "/analysis/definitions/{definition_id}/runs",
                "/analysis/runs",
                "/analysis/runs/{request_id}",
                "/catalog/sources",
                "/health",
                "/operations/audit",
                "/operations/audit/access",
                "/operations/audit/recovery",
                "/operations/audit/{request_id}",
                "/readiness",
                "/reports/definitions",
                "/reports/definitions/{definition_id}/versions/{version}/approve",
                "/reports/definitions/{definition_id}/versions/{version}/drafts",
                "/reports/definitions/{definition_id}/versions/{version}",
                "/reports/definitions/{definition_id}/versions/{version}/blocks",
                "/reports/definitions/{definition_id}/versions/{version}/schedule",
                "/reports/runs",
                "/reports/runs/manual",
                "/reports/runs/{run_id}",
                "/reports/schedules",
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
                "getHealth",
                "getReadiness",
                "auditSearchRequests",
                "auditGetRequestTrace",
                "auditGetEffectiveAccess",
                "auditGetRecoveryStatus",
                "submitAnalysis",
                "analysisGetProgress",
                "analysisListRecent",
                "analysisCreateDefinition",
                "analysisListDefinitions",
                "analysisGetDefinition",
                "analysisReplayDefinition",
                "analysisListRuns",
                "analysisGetRun",
                "catalogListSources",
                "reportCreateDefinition",
                "reportListDefinitions",
                "reportApproveVersion",
                "reportCreateNextDraft",
                "reportGetDefinitionVersion",
                "reportReplaceDraftBlocks",
                "reportListRuns",
                "reportCreateManualRunCommand",
                "reportGetRun",
                "reportUpsertSchedule",
                "reportListSchedules",
            },
            operation_ids,
        )
        self.assertNotIn("post", committed["paths"]["/reports/runs"])
        self.assertEqual(
            "DataHub 또는 Trino 카탈로그 미가용",
            committed["paths"]["/catalog/sources"]["get"]["responses"]["503"]["description"],
        )
        analysis = committed["paths"]["/analysis"]["post"]
        self.assertIn("503", analysis["responses"])
        self.assertIn("X-Access-Profile", {item["name"] for item in analysis["parameters"]})
        self.assertIn("X-Request-Id", {item["name"] for item in analysis["parameters"]})
        progress = committed["paths"]["/analysis/{request_id}/progress"]["get"]
        self.assertEqual("AnalysisProgressResponse", progress["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1])

    def test_analysis_persistence_requests_reject_server_owned_fields(self) -> None:
        schemas = app.openapi()["components"]["schemas"]
        for name in ("CreateAnalysisDefinitionRequest", "ReplayAnalysisRequest"):
            with self.subTest(schema=name):
                self.assertFalse(schemas[name]["additionalProperties"])
        run = schemas["AnalysisRunResponse"]["properties"]
        for forbidden in ("sql", "parameters", "result", "snapshot"):
            self.assertNotIn(forbidden, run)

    def test_audit_trace_contract_excludes_sensitive_payloads(self) -> None:
        schemas = app.openapi()["components"]["schemas"]
        serialized = json.dumps(schemas["AuditTraceResponse"], ensure_ascii=False)
        for forbidden in ("sql", "parameters", "result", "snapshot", "question"):
            self.assertNotIn(f'"{forbidden}"', serialized)
        self.assertIn("source_urns", schemas["QueryTrace"]["properties"])
        self.assertIn("masking", schemas["ArtifactTrace"]["properties"])
        self.assertEqual(
            {
                "access_profile", "allowed_domains", "datahub_actor",
                "allowed_urns", "trino_role", "datahub_search_attempted",
                "trino_execution_attempted",
            },
            set(schemas["AccessExecutionTrace"]["properties"]),
        )
        self.assertIn("entitlement_hash", schemas["PolicyTrace"]["properties"])

        parameters = {
            item["name"]
            for item in app.openapi()["paths"]["/operations/audit"]["get"]["parameters"]
        }
        self.assertTrue(
            {"request_id", "status", "started_from", "started_to"}.issubset(parameters)
        )

        recovery = json.dumps({name: schemas[name] for name in ("RecoveryStatusResponse", "RetentionStatus", "BackupStatus", "RestoreStatus")}, ensure_ascii=False)
        for forbidden in ("path", "file", "key", "secret"):
            self.assertNotIn(f'"{forbidden}"', recovery)

    def test_authenticated_routes_use_server_owned_bearer_identity(self) -> None:
        schema = app.openapi()
        bearer = schema["components"]["securitySchemes"]["BearerAuth"]
        self.assertEqual("http", bearer["type"])
        self.assertEqual("bearer", bearer["scheme"])
        for path, operations in schema["paths"].items():
            if path in {"/health", "/readiness"}:
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
            "ReplaceReportBlocksRequest",
            "ReportBlockRequest",
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
