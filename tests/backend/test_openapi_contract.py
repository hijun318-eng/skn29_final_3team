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
                "/analysis",
                "/health",
                "/readiness",
                "/reports/definitions",
                "/reports/definitions/{definition_id}/versions/{version}/approve",
                "/reports/definitions/{definition_id}/versions/{version}/drafts",
                "/reports/definitions/{definition_id}/versions/{version}",
                "/reports/definitions/{definition_id}/versions/{version}/blocks",
                "/reports/runs",
                "/reports/runs/manual",
                "/reports/runs/{run_id}",
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
                "submitAnalysis",
                "reportCreateDefinition",
                "reportListDefinitions",
                "reportApproveVersion",
                "reportCreateNextDraft",
                "reportGetDefinitionVersion",
                "reportReplaceDraftBlocks",
                "reportListRuns",
                "reportCreateManualRunCommand",
                "reportGetRun",
            },
            operation_ids,
        )
        self.assertNotIn("post", committed["paths"]["/reports/runs"])

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
