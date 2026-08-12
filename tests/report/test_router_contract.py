import unittest
from datetime import datetime, timezone

from src.report.repository import InMemoryReportRepository
from src.report.router import REPORT_ROUTES, ReportRouteError, create_report_router


class ReportRouterContractTest(unittest.TestCase):
    def setUp(self):
        self.router = create_report_router(InMemoryReportRepository())

    def test_route_manifest_is_ready_for_r4_registration(self):
        self.assertEqual(12, len(REPORT_ROUTES))
        self.assertIn(("POST", "/reports/definitions", "create_definition"), REPORT_ROUTES)
        self.assertIn(
            ("POST", "/reports/definitions/{definition_id}/versions/{version}/approve", "approve_version"),
            REPORT_ROUTES,
        )
        self.assertIn(("GET", "/reports/definitions", "list_definitions"), REPORT_ROUTES)
        self.assertIn(
            ("GET", "/reports/definitions/{definition_id}/versions/{version}", "get_version"),
            REPORT_ROUTES,
        )
        self.assertIn(
            ("PUT", "/reports/definitions/{definition_id}/versions/{version}/blocks", "replace_draft_blocks"),
            REPORT_ROUTES,
        )
        self.assertIn(("GET", "/reports/runs", "list_runs"), REPORT_ROUTES)
        self.assertIn(("GET", "/reports/runs/{run_id}", "get_run"), REPORT_ROUTES)
        self.assertIn(("POST", "/reports/runs/manual", "create_manual_run_command"), REPORT_ROUTES)
        self.assertIn(("GET", "/reports/schedules", "list_schedules"), REPORT_ROUTES)

    def test_approved_definition_accepts_a_persistent_monthly_schedule(self):
        self.router.create_definition({"definition_id": "report-1", "title": "월간", "blocks": []})
        approved_at = datetime(2026, 8, 3, tzinfo=timezone.utc).isoformat()
        self.router.approve_version("report-1", 1, approved_at)
        schedule = self.router.upsert_schedule(
            "report-1", 1,
            {"frequency": "monthly", "hour": 9, "minute": 0, "day_of_month": 31, "enabled": True},
            datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual("2026-08-31T09:00:00+00:00", schedule["next_run_at"])
        self.assertEqual(1, len(self.router.list_schedules()["items"]))

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
        self.assertEqual("table", next_draft["blocks"][0]["type"])
        self.assertEqual(6, next_draft["blocks"][0]["w"])

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
        self.assertEqual(2, len(self.router.list_definitions()["items"]))
        self.assertEqual("run-1", self.router.list_runs()["items"][0]["run_id"])
        self.assertEqual("run-1", self.router.get_run("run-1")["run_id"])
        with self.assertRaises(ReportRouteError) as duplicate:
            self.router.create_run({
                "run_id": "run-1", "definition_id": "report-1", "definition_version": 1,
                "as_of": approved_at, "policy_version": "policy-v1", "context_hash": "context-1",
                "watermark": {}, "status": "success", "blocks": [],
            })
        self.assertEqual(409, duplicate.exception.status_code)

    def test_draft_layout_replace_and_manual_command_trust_boundary(self):
        self.router.create_definition({
            "definition_id": "report-1",
            "title": "주간 운영 보고서",
            "blocks": [{
                "block_id": "block-1", "title": "객실 매출", "artifact_id": "artifact-1",
                "columns": 6,
            }],
        })
        replaced = self.router.replace_draft_blocks("report-1", 1, {"blocks": [{
            "block_id": "text-1", "title": "해석", "type": "text", "content": "관측 결과",
            "x": 0, "y": 0, "w": 12, "h": 2,
        }]})
        self.assertEqual("text", replaced["blocks"][0]["type"])
        self.assertIsNone(replaced["blocks"][0]["artifact_id"])

        approved_at = datetime(2026, 8, 3, tzinfo=timezone.utc).isoformat()
        self.router.approve_version("report-1", 1, approved_at)
        with self.assertRaises(ReportRouteError) as immutable:
            self.router.replace_draft_blocks("report-1", 1, {"blocks": []})
        self.assertEqual(409, immutable.exception.status_code)

        payload = {
            "definition_id": "report-1", "version": 1,
            "as_of": approved_at, "idempotency_key": "manual-20260803",
        }
        command = self.router.create_manual_run_command(payload)
        repeated = self.router.create_manual_run_command(payload)
        self.assertEqual("queued", command["status"])
        self.assertEqual(command["command_id"], repeated["command_id"])
        self.assertNotIn("run_id", command)
        for forbidden in (
            "command_id", "run_id", "definition_version", "status", "policy_version",
            "context_hash", "watermark", "blocks", "result",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ReportRouteError) as untrusted:
                    self.router.create_manual_run_command({**payload, forbidden: "client-value"})
                self.assertEqual(422, untrusted.exception.status_code)

    def test_router_rejects_unknown_fields(self):
        with self.assertRaises(ReportRouteError) as invalid:
            self.router.create_definition({
                "definition_id": "report-1", "title": "보고서", "blocks": [], "role": "admin",
            })
        self.assertEqual(422, invalid.exception.status_code)


if __name__ == "__main__":
    unittest.main()
