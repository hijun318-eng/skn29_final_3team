import unittest
from datetime import datetime, timezone

from src.report.router import REPORT_ROUTES, ReportRouteError, create_report_router
from tests.support.report_repository import InMemoryReportRepository


class ReportRouterContractTest(unittest.IsolatedAsyncioTestCase):
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
            ("POST", "/reports/definitions/{definition_id}/archive", "archive_definition"),
            REPORT_ROUTES,
        )
        self.assertIn(
            ("POST", "/reports/definitions/{definition_id}/restore", "restore_definition"),
            REPORT_ROUTES,
        )
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

    async def test_router_creates_approves_and_versions_without_overwriting(self):
        created = await self.router.create_definition({
            "definition_id": "report-1",
            "title": "주간 운영 보고서",
            "orientation": "landscape",
            "currency_display_unit": "hundredMillion",
            "blocks": [{
                "block_id": "block-1", "title": "객실 매출", "artifact_id": "artifact-1",
                "query_id": "query-1", "columns": 6,
            }],
        })
        self.assertEqual("REPORT-v1.0.0", created["contract_version"])
        self.assertEqual("landscape", created["orientation"])
        self.assertEqual("hundredMillion", created["currency_display_unit"])
        approved_at = datetime(2026, 8, 3, tzinfo=timezone.utc).isoformat()
        approved = await self.router.approve_version("report-1", 1, approved_at)
        self.assertEqual("approved", approved["status"])
        with self.assertRaises(ReportRouteError) as conflict:
            await self.router.approve_version("report-1", 1, approved_at)
        self.assertEqual(409, conflict.exception.status_code)
        next_draft = await self.router.create_next_draft("report-1", 1)
        self.assertEqual(2, next_draft["version"])
        self.assertEqual("artifact-1", next_draft["blocks"][0]["artifact_id"])
        self.assertEqual("table", next_draft["blocks"][0]["type"])
        self.assertEqual(6, next_draft["blocks"][0]["w"])
        self.assertEqual("landscape", next_draft["orientation"])
        self.assertEqual("hundredMillion", next_draft["currency_display_unit"])

        run = await self.router.create_run({
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
                "request_id": "request-1",
            }],
        })
        self.assertEqual(1, run["definition_version"])
        self.assertEqual("artifact-1", run["blocks"][0]["artifact_id"])
        self.assertEqual("sha256-1", run["blocks"][0]["snapshot_checksum"])
        self.assertEqual(2, len((await self.router.list_definitions())["items"]))
        self.assertEqual("run-1", (await self.router.list_runs())["items"][0]["run_id"])
        self.assertEqual("run-1", (await self.router.get_run("run-1"))["run_id"])
        with self.assertRaises(ReportRouteError) as duplicate:
            await self.router.create_run({
                "run_id": "run-1", "definition_id": "report-1", "definition_version": 1,
                "as_of": approved_at, "policy_version": "policy-v1", "context_hash": "context-1",
                "watermark": {}, "status": "success", "blocks": [],
            })
        self.assertEqual(409, duplicate.exception.status_code)

    async def test_draft_layout_replace_and_manual_command_trust_boundary(self):
        await self.router.create_definition({
            "definition_id": "report-1",
            "title": "주간 운영 보고서",
            "blocks": [{
                "block_id": "block-1", "title": "객실 매출", "artifact_id": "artifact-1",
                "columns": 6,
            }],
        })
        replaced = await self.router.replace_draft_blocks("report-1", 1, {
            "title": "주간 운영 보고서 · 검토본",
            "orientation": "landscape",
            "currency_display_unit": "million",
            "expected_draft_revision": 1,
            "blocks": [{
            "block_id": "text-1", "title": "해석", "type": "text", "content": "관측 결과",
            "x": 0, "y": 0, "w": 12, "h": 2,
        }]})
        self.assertEqual("text", replaced["blocks"][0]["type"])
        self.assertEqual("주간 운영 보고서 · 검토본", replaced["title"])
        self.assertIsNone(replaced["blocks"][0]["artifact_id"])
        self.assertEqual("landscape", replaced["orientation"])
        self.assertEqual("million", replaced["currency_display_unit"])

        approved_at = datetime(2026, 8, 3, tzinfo=timezone.utc).isoformat()
        await self.router.approve_version("report-1", 1, approved_at)
        with self.assertRaises(ReportRouteError) as immutable:
            await self.router.replace_draft_blocks(
                "report-1", 1, {"blocks": [], "expected_draft_revision": 2}
            )
        self.assertEqual(409, immutable.exception.status_code)

        payload = {
            "definition_id": "report-1", "version": 1,
            "as_of": approved_at, "idempotency_key": "manual-20260803",
        }
        command = await self.router.create_manual_run_command(payload)
        repeated = await self.router.create_manual_run_command(payload)
        self.assertEqual("queued", command["status"])
        self.assertEqual(command["command_id"], repeated["command_id"])
        self.assertNotIn("run_id", command)
        for forbidden in (
            "command_id", "run_id", "definition_version", "status", "policy_version",
            "context_hash", "watermark", "blocks", "result",
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ReportRouteError) as untrusted:
                    await self.router.create_manual_run_command({**payload, forbidden: "client-value"})
                self.assertEqual(422, untrusted.exception.status_code)

    async def test_artifact_view_title_is_immutable_during_manual_save(self):
        """일반 저장 API도 기존 분석 view의 source 식별 제목 변조를 거부한다."""

        await self.router.create_definition({
            "definition_id": "report-artifact-title",
            "title": "분석 보고서",
            "blocks": [{
                "block_id": "chart-1",
                "title": "객실 매출 추이",
                "artifact_id": "artifact-1",
                "type": "chart",
                "columns": 12,
                "w": 12,
                "h": 7,
            }],
        })

        with self.assertRaises(ReportRouteError) as immutable:
            await self.router.replace_draft_blocks(
                "report-artifact-title",
                1,
                {
                    "blocks": [{
                        "block_id": "chart-1",
                        "title": "사용자가 바꾼 제목",
                        "artifact_id": "artifact-1",
                        "type": "chart",
                        "columns": 12,
                        "w": 12,
                        "h": 7,
                    }],
                    "expected_draft_revision": 1,
                },
            )

        self.assertEqual(409, immutable.exception.status_code)
        self.assertIn("Artifact view block 제목", str(immutable.exception.detail))

    async def test_router_rejects_unknown_fields(self):
        with self.assertRaises(ReportRouteError) as invalid:
            await self.router.create_definition({
                "definition_id": "report-1", "title": "보고서", "blocks": [], "role": "admin",
            })
        self.assertEqual(422, invalid.exception.status_code)

    async def test_archive_is_idempotent_read_only_and_explicitly_listed(self):
        await self.router.create_definition({
            "definition_id": "report-archive",
            "title": "보관 계약 보고서",
            "blocks": [],
        })

        archived = await self.router.archive_definition(
            "report-archive", actor_role="analyst", trace_id="archive-trace"
        )
        repeated = await self.router.archive_definition(
            "report-archive", actor_role="analyst", trace_id="archive-retry"
        )

        self.assertTrue(archived["archived"])
        self.assertEqual(archived["archived_at"], repeated["archived_at"])
        self.assertEqual([], (await self.router.list_definitions())["items"])
        archived_items = (
            await self.router.list_definitions(archived=True)
        )["items"]
        self.assertEqual(1, len(archived_items))
        self.assertEqual("report-archive", archived_items[0]["definition_id"])
        self.assertIsNotNone(
            (await self.router.get_version("report-archive", 1))["archived_at"]
        )
        with self.assertRaises(ReportRouteError) as read_only:
            await self.router.replace_draft_blocks(
                "report-archive",
                1,
                {"blocks": [], "expected_draft_revision": 1},
            )
        self.assertEqual(409, read_only.exception.status_code)

        restored = await self.router.restore_definition(
            "report-archive", actor_role="analyst", trace_id="restore-trace"
        )
        repeated_restore = await self.router.restore_definition(
            "report-archive", actor_role="analyst", trace_id="restore-retry"
        )
        self.assertFalse(restored["archived"])
        self.assertEqual(restored, repeated_restore)
        self.assertEqual(1, len((await self.router.list_definitions())["items"]))

    async def test_archive_rejects_a_queued_manual_run(self):
        await self.router.create_definition({
            "definition_id": "report-running",
            "title": "실행 대기 보고서",
            "blocks": [],
        })
        approved_at = datetime(2026, 8, 3, tzinfo=timezone.utc).isoformat()
        await self.router.approve_version("report-running", 1, approved_at)
        await self.router.create_manual_run_command({
            "definition_id": "report-running",
            "version": 1,
            "as_of": approved_at,
            "idempotency_key": "archive-blocker",
        })

        with self.assertRaises(ReportRouteError) as blocked:
            await self.router.archive_definition(
                "report-running", actor_role="analyst", trace_id="blocked-trace"
            )
        self.assertEqual(409, blocked.exception.status_code)
        self.assertEqual("REPORT_ARCHIVE_IN_PROGRESS", blocked.exception.detail)

    async def test_draft_revision_retries_are_idempotent_and_stale_changes_conflict(self):
        created = await self.router.create_definition({
            "definition_id": "report-cas",
            "title": "Revision report",
            "blocks": [],
        })
        self.assertEqual(1, created["draft_revision"])
        changed_payload = {
            "title": "  Revision report updated  ",
            "blocks": [],
            "expected_draft_revision": 1,
        }
        changed = await self.router.replace_draft_blocks(
            "report-cas", 1, changed_payload
        )
        self.assertEqual("Revision report updated", changed["title"])
        self.assertEqual(2, changed["draft_revision"])

        exact_retry = await self.router.replace_draft_blocks(
            "report-cas", 1, changed_payload
        )
        self.assertEqual(2, exact_retry["draft_revision"])

        with self.assertRaises(ReportRouteError) as stale:
            await self.router.replace_draft_blocks(
                "report-cas",
                1,
                {
                    "title": "Stale overwrite",
                    "blocks": [],
                    "expected_draft_revision": 1,
                },
            )
        self.assertEqual(409, stale.exception.status_code)
        self.assertEqual(
            {
                "code": "REPORT_REVISION_CONFLICT",
                "current_draft_revision": 2,
            },
            stale.exception.detail,
        )
        current = await self.router.get_version("report-cas", 1)
        self.assertEqual("Revision report updated", current["title"])
        self.assertEqual(2, current["draft_revision"])


if __name__ == "__main__":
    unittest.main()
