import unittest
from datetime import datetime, timezone

from src.report.repository import InMemoryReportRepository
from src.report.router import REPORT_ROUTES, ReportRouteError, create_report_router


class ReportRouterContractTest(unittest.TestCase):
    def setUp(self):
        self.router = create_report_router(InMemoryReportRepository())

    def test_route_manifest_is_ready_for_r4_registration(self):
        self.assertEqual(5, len(REPORT_ROUTES))
        self.assertIn(("POST", "/reports/definitions", "create_definition"), REPORT_ROUTES)
        self.assertIn(
            ("POST", "/reports/definitions/{definition_id}/versions/{version}/approve", "approve_version"),
            REPORT_ROUTES,
        )

    def test_router_creates_approves_and_versions_without_overwriting(self):
        created = self.router.create_definition({
            "definition_id": "report-1",
            "title": "주간 운영 보고서",
            "blocks": [{
                "block_id": "block-1", "title": "객실 매출", "artifact_id": "artifact-1",
                "query_id": "query-1", "columns": 6,
            }],
        })
        self.assertEqual("REPORT-v1.0.0", created["contract_version"])
        approved_at = datetime(2026, 8, 3, tzinfo=timezone.utc).isoformat()
        approved = self.router.approve_version("report-1", 1, approved_at)
        self.assertEqual("approved", approved["status"])
        with self.assertRaises(ReportRouteError) as conflict:
            self.router.approve_version("report-1", 1, approved_at)
        self.assertEqual(409, conflict.exception.status_code)
        next_draft = self.router.create_next_draft("report-1", 1)
        self.assertEqual(2, next_draft["version"])
        self.assertEqual("artifact-1", next_draft["blocks"][0]["artifact_id"])

        run = self.router.create_run({
            "run_id": "run-1",
            "definition_id": "report-1",
            "definition_version": 1,
            "as_of": approved_at,
            "policy_version": "policy-v1",
            "context_hash": "context-1",
            "watermark": {"pms": "2026-07-28T05:00:00.000Z"},
            "status": "partial",
            "blocks": [{
                "block_id": "block-1", "artifact_id": "artifact-1", "query_id": "query-1",
                "snapshot_checksum": "sha256-1", "status": "partial",
            }],
        })
        self.assertEqual(1, run["definition_version"])
        self.assertEqual("artifact-1", run["blocks"][0]["artifact_id"])
        self.assertEqual("sha256-1", run["blocks"][0]["snapshot_checksum"])
        with self.assertRaises(ReportRouteError) as duplicate:
            self.router.create_run({
                "run_id": "run-1", "definition_id": "report-1", "definition_version": 1,
                "as_of": approved_at, "policy_version": "policy-v1", "context_hash": "context-1",
                "watermark": {}, "status": "success", "blocks": [],
            })
        self.assertEqual(409, duplicate.exception.status_code)

    def test_router_rejects_unknown_fields(self):
        with self.assertRaises(ReportRouteError) as invalid:
            self.router.create_definition({
                "definition_id": "report-1", "title": "보고서", "blocks": [], "role": "admin",
            })
        self.assertEqual(422, invalid.exception.status_code)


if __name__ == "__main__":
    unittest.main()