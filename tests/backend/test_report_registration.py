from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from inspect import signature
import os
from pathlib import Path
from sys import path
import unittest
from unittest.mock import patch
from uuid import UUID
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
path.insert(0, str(BACKEND))

from app.api import report_router as report_api  # noqa: E402
from app.contracts import RequestContext, Role  # noqa: E402
from app.main import app  # noqa: E402
from app.report_contracts import (  # noqa: E402
    ApproveReportVersionRequest,
    CreateManualRunRequest,
    CreateReportDefinitionRequest,
    CreateReportFromArtifactRequest,
    CreateReportScheduleRequest,
    ReplaceReportBlocksRequest,
    UpdateReportScheduleRequest,
)
from src.report.repository import InMemoryReportRepository  # noqa: E402
from src.report.router import create_report_router  # noqa: E402
from src.report.domain import (  # noqa: E402
    DefinitionStatus,
    BlockType,
    ReportBlock,
    ReportDefinitionVersion,
    ReportRun,
    RunStatus,
)


def context(role: Role = Role.REPORT_ADMIN) -> RequestContext:
    return RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        role=role,
    )


class ReportRegistrationTest(unittest.TestCase):
    def test_analysis_artifact_transfer_builds_server_owned_blocks(self):
        class TransferRepository(InMemoryReportRepository):
            def get_transfer_artifact(self, artifact_id):
                if artifact_id != "00000000-0000-0000-0000-000000000099":
                    raise KeyError("본인의 승인된 Analysis Artifact를 찾을 수 없습니다.")
                return {
                    "artifact_id": artifact_id,
                    "trino_query_id": "query-real",
                    "narrative_markdown": "실제 분석 요약",
                    "data_snapshot_json": {"columns": ["value"], "rows": [{"value": 1}]},
                    "chart_spec_json": {"chart_type": "bar", "x_field": "month", "y_fields": ["value"]},
                }

        router = create_report_router(TransferRepository())
        payload = CreateReportFromArtifactRequest(
            artifact_id=UUID("00000000-0000-0000-0000-000000000099"),
            title="실제 Artifact 보고서",
        )
        with patch.object(report_api, "_router", return_value=router):
            created = report_api.create_draft_from_analysis_artifact(
                payload, context(Role.HOTEL_ANALYST)
            )

        self.assertEqual("draft", created["status"])
        self.assertEqual(["text", "chart", "table"], [block["type"] for block in created["blocks"]])
        self.assertEqual("실제 분석 요약", created["blocks"][0]["content"])
        for block in created["blocks"][1:]:
            self.assertEqual(str(payload.artifact_id), block["artifact_id"])
            self.assertEqual("query-real", block["query_id"])

        with patch.object(report_api, "_router", return_value=router), self.assertRaises(HTTPException) as missing:
            report_api.create_draft_from_analysis_artifact(
                payload.model_copy(update={"artifact_id": uuid4()}),
                context(Role.HOTEL_ANALYST),
            )
        self.assertEqual(404, missing.exception.status_code)

    def test_report_routes_require_authentication_and_report_admin(self):
        dependency = signature(report_api.report_admin_context).parameters["context"]
        self.assertIn("analysis_context", repr(dependency.annotation))
        self.assertEqual(Role.REPORT_ADMIN, report_api.report_admin_context(context()).role)
        for role in (Role.HOTEL_ANALYST, Role.DATA_ADMIN):
            with self.assertRaises(HTTPException) as denied:
                report_api.report_admin_context(context(role))
            self.assertEqual(403, denied.exception.status_code)

    def test_report_repository_scope_follows_authenticated_role(self):
        for role, manage_all in (
            (Role.HOTEL_ANALYST, False),
            (Role.REPORT_ADMIN, True),
        ):
            with self.subTest(role=role), patch.dict(
                os.environ, {"APP_RUNTIME_DATABASE_URL": "postgresql://report-db"}
            ), patch(
                "app.adapters.report_repository.PostgresReportRepository"
            ) as repository:
                repository.return_value = InMemoryReportRepository()

                report_api._router(context(role))

                repository.assert_called_once_with(
                    "postgresql://report-db",
                    context(role).user_id,
                    manage_all=manage_all,
                )

    def test_report_v11_routes_replace_draft_and_keep_result_ingestion_internal(self):
        proposal = create_report_router(InMemoryReportRepository())
        with patch.object(report_api, "_router", return_value=proposal):
            approved_at = datetime(2026, 8, 4, tzinfo=timezone.utc).isoformat()
            definition = {
                "definition_id": "report-1",
                "title": "운영 보고서",
                "blocks": [
                    {
                        "block_id": "block-1",
                        "title": "객실 매출",
                        "artifact_id": "artifact-1",
                        "query_id": "query-1",
                        "columns": 6,
                    }
                ],
            }
            run = {
                "run_id": "run-1",
                "definition_id": "report-1",
                "definition_version": 1,
                "as_of": approved_at,
                "policy_version": "policy-v1",
                "context_hash": "context-1",
                "watermark": {"pms": "2026-08-04T00:00:00Z"},
                "status": "success",
                "blocks": [],
            }

            report_context = context()
            self.assertEqual(
                "draft",
                report_api.create_definition(
                    CreateReportDefinitionRequest.model_validate(definition), report_context
                )["status"],
            )
            with self.assertRaises(HTTPException) as draft_run:
                report_api.create_run_internal(run, report_context)
            self.assertEqual(409, draft_run.exception.status_code)
            replaced = report_api.replace_draft_blocks(
                "report-1",
                1,
                ReplaceReportBlocksRequest.model_validate({"blocks": [{
                    "block_id": "text-1", "title": "해석", "type": "text",
                    "content": "관측 결과", "x": 0, "y": 0, "w": 12, "h": 2,
                }]}),
                report_context,
            )
            self.assertEqual("text", replaced["blocks"][0]["type"])
            self.assertEqual(1, len(report_api.list_definitions(report_context)["items"]))
            self.assertEqual(
                "approved",
                report_api.approve_version(
                    "report-1",
                    1,
                    ApproveReportVersionRequest(approved_at=approved_at),
                    report_context,
                )["status"],
            )
            with self.assertRaises(HTTPException) as immutable:
                report_api.replace_draft_blocks(
                    "report-1", 1, ReplaceReportBlocksRequest(blocks=[]), report_context
                )
            self.assertEqual(409, immutable.exception.status_code)
            self.assertEqual("run-1", report_api.create_run_internal(run, report_context)["run_id"])
            self.assertEqual("run-1", report_api.list_runs(report_context)["items"][0]["run_id"])
            self.assertEqual("run-1", report_api.get_run("run-1", report_context)["run_id"])
            with self.assertRaises(HTTPException) as duplicate:
                report_api.create_run_internal(run, report_context)
            self.assertEqual(409, duplicate.exception.status_code)

            command_payload = {
                "definition_id": "report-1", "version": 1,
                "as_of": approved_at, "idempotency_key": "manual-1",
            }
            command = report_api.create_manual_run_command(
                CreateManualRunRequest.model_validate(command_payload), report_context
            )
            self.assertEqual("queued", command["status"])
            self.assertNotIn("run_id", command)
            with self.assertRaises(ValidationError):
                CreateManualRunRequest.model_validate(
                    {**command_payload, "idempotency_key": " "}
                )
            for forbidden in (
                "command_id", "run_id", "status", "policy_version", "context_hash",
                "watermark", "blocks", "result",
            ):
                with self.subTest(forbidden=forbidden):
                    with self.assertRaises(ValidationError):
                        CreateManualRunRequest.model_validate(
                            {**command_payload, forbidden: "client-value"}
                        )

    def test_report_routes_are_typed_without_public_result_ingestion(self):
        paths = {route.path for route in report_api.report_router.routes}
        self.assertIn("/reports/definitions", paths)
        self.assertIn("/reports/runs", paths)
        self.assertIn("/reports/runs/manual", paths)
        self.assertNotIn(
            ("/reports/runs", "POST"),
            {(route.path, method) for route in report_api.report_router.routes for method in route.methods},
        )
        schema = app.openapi()
        self.assertIn("/reports/definitions", schema["paths"])
        self.assertIn("/reports/runs/manual", schema["paths"])
        self.assertIn("/reports/schedules", schema["paths"])
        self.assertIn("/reports/schedules/{schedule_id}", schema["paths"])
        self.assertIn("/reports/schedules/{schedule_id}/run-due", schema["paths"])
        self.assertIn("/reports/assistant/drafts", schema["paths"])
        self.assertNotIn("post", schema["paths"]["/reports/runs"])

    def test_schedule_contract_requires_timezone_aware_instants(self):
        payload = {
            "schedule_id": str(uuid4()),
            "definition_id": str(uuid4()),
            "version": 1,
            "cadence": "daily",
            "next_run_at": "2026-08-12T09:00:00+09:00",
        }
        schedule = CreateReportScheduleRequest.model_validate(payload)
        self.assertEqual("Asia/Seoul", schedule.timezone)
        self.assertIsNotNone(schedule.next_run_at.utcoffset())
        with self.assertRaises(ValidationError):
            CreateReportScheduleRequest.model_validate(
                {**payload, "next_run_at": "2026-08-12T09:00:00"}
            )
        self.assertFalse(UpdateReportScheduleRequest(enabled=False).enabled)

    def test_schedule_calendar_advances_in_seoul_time(self):
        from app.adapters.report_repository import _advance_schedule

        current = datetime.fromisoformat("2026-01-31T09:00:00+09:00")
        self.assertEqual(
            "2026-02-28T09:00:00+09:00",
            _advance_schedule(current, "monthly").isoformat(),
        )
        self.assertEqual(
            "2026-02-01T09:00:00+09:00",
            _advance_schedule(current, "daily").isoformat(),
        )

    def test_report_assistant_uses_its_own_strict_prompt_and_schema(self):
        from app.adapters.contract_model import _openai_payload
        from src.ai.prompt_registry import get_prompt

        payload = _openai_payload("gpt-test", "report_assistant", {"artifact": {}})
        self.assertEqual(
            get_prompt("report.assistant").text,
            payload["messages"][0]["content"],
        )
        schema = payload["response_format"]["json_schema"]["schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            {"title", "executive_summary", "table_title", "chart_title"},
            set(schema["required"]),
        )


@unittest.skipUnless(
    os.getenv("REPORT_DATABASE_URL") and os.getenv("REPORT_DATABASE_DISPOSABLE") == "1",
    "disposable temporary report DB is required",
)
class PostgresReportRepositoryTest(unittest.TestCase):
    def test_database_owner_scope_layout_history_and_concurrent_idempotency(self):
        from app.adapters.report_repository import PostgresReportRepository, _engine
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        database_url = os.environ["REPORT_DATABASE_URL"]
        definition_id = str(uuid4())
        block_id = str(uuid4())
        artifact_id = str(uuid4())
        approved_at = datetime(2026, 8, 4, tzinfo=timezone.utc)
        repository = PostgresReportRepository(database_url, context().user_id)
        other_repository = PostgresReportRepository(
            database_url, UUID("00000000-0000-0000-0000-000000000002")
        )
        admin_repository = PostgresReportRepository(
            database_url,
            UUID("00000000-0000-0000-0000-000000000003"),
            manage_all=True,
        )
        repository.add_draft(
            ReportDefinitionVersion(
                definition_id,
                1,
                DefinitionStatus.DRAFT,
                "운영 보고서",
                (
                    ReportBlock(
                        block_id,
                        "객실 매출",
                        artifact_id,
                        6,
                    ),
                ),
            )
        )
        with self.assertRaises(KeyError):
            other_repository.get_version(definition_id, 1)
        self.assertEqual((), other_repository.list_definitions())
        self.assertEqual(
            definition_id,
            admin_repository.get_version(definition_id, 1).definition_id,
        )
        self.assertIn(
            definition_id,
            {item.definition_id for item in admin_repository.list_definitions()},
        )
        right_block = ReportBlock(
            str(uuid4()), "오른쪽 해석", None, 6, None,
            BlockType.TEXT, 6, 0, 6, 2, "오른쪽 관측 결과",
        )
        left_block = ReportBlock(
            str(uuid4()), "왼쪽 해석", None, 6, None,
            BlockType.TEXT, 0, 0, 6, 2, "왼쪽 관측 결과",
        )
        replaced = repository.replace_draft_blocks(
            definition_id, 1, (right_block, left_block)
        )
        self.assertEqual(
            [left_block.block_id, right_block.block_id],
            [block.block_id for block in replaced.blocks],
        )
        with self.assertRaises(DBAPIError):
            with _engine(database_url).begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_blocks
                            (definition_id, definition_version, block_id, title,
                             artifact_id, columns, block_type, x, y, w, h, content)
                        VALUES (:definition_id, 1, :block_id, 'bounds',
                                :artifact_id, 2, 'chart', 11, 0, 2, 1, '')
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "block_id": str(uuid4()),
                        "artifact_id": str(uuid4()),
                    },
                )
        with self.assertRaises(DBAPIError):
            with _engine(database_url).begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_manual_run_commands
                            (command_id, definition_id, definition_version, as_of, idempotency_key)
                        VALUES (:command_id, :definition_id, 1, :as_of, 'before-approval')
                        """
                    ),
                    {
                        "command_id": str(uuid4()),
                        "definition_id": definition_id,
                        "as_of": approved_at,
                    },
                )
        run = ReportRun(
            str(uuid4()),
            definition_id,
            1,
            approved_at,
            "policy-v1",
            "context-1",
            {},
            RunStatus.SUCCESS,
        )

        with self.assertRaisesRegex(ValueError, "승인된"):
            repository.add_run(run)
        admin_repository.approve(definition_id, 1, approved_at)
        with self.assertRaisesRegex(ValueError, "draft Report version"):
            repository.replace_draft_blocks(definition_id, 1, ())
        repository.add_run(run)
        self.assertEqual(run.run_id, repository.get_run(run.run_id).run_id)
        self.assertEqual(run.run_id, admin_repository.get_run(run.run_id).run_id)
        self.assertEqual(1, len(repository.list_runs(definition_id)))
        with self.assertRaises(KeyError):
            other_repository.get_run(run.run_id)
        self.assertEqual((), other_repository.list_runs())
        with self.assertRaisesRegex(ValueError, "run_id"):
            repository.add_run(run)
        with ThreadPoolExecutor(max_workers=8) as pool:
            commands = tuple(pool.map(
                lambda _: repository.queue_manual_run(
                    definition_id, 1, approved_at, "same-request"
                ),
                range(8),
            ))
        self.assertEqual(1, len({command.command_id for command in commands}))
        schedule_id = str(uuid4())
        schedule = repository.create_schedule(
            schedule_id, definition_id, 1, "daily", "Asia/Seoul", approved_at
        )
        self.assertEqual(schedule_id, str(schedule["schedule_id"]))
        self.assertEqual(1, len(repository.list_schedules()))
        self.assertEqual((), other_repository.list_schedules())
        self.assertEqual(
            (schedule_id,),
            repository.list_due_schedule_ids(approved_at),
        )
        disabled = repository.set_schedule_enabled(schedule_id, False)
        self.assertFalse(disabled["enabled"])
        self.assertEqual((), repository.list_due_schedule_ids(approved_at))
        with self.assertRaises(KeyError):
            other_repository.set_schedule_enabled(schedule_id, True)
        self.assertTrue(repository.set_schedule_enabled(schedule_id, True)["enabled"])
        scheduled, scheduled_run = repository.run_due_schedule(
            schedule_id, approved_at.replace(minute=1)
        )
        self.assertIsNotNone(scheduled_run)
        self.assertEqual(scheduled_run.run_id, str(scheduled["last_run_id"]))
        unchanged, duplicate_run = repository.run_due_schedule(
            schedule_id, approved_at.replace(minute=1)
        )
        self.assertIsNone(duplicate_run)
        self.assertEqual(scheduled["next_run_at"], unchanged["next_run_at"])
        with self.assertRaises(KeyError):
            other_repository.get_schedule(schedule_id)
        self.assertEqual(
            schedule_id,
            str(admin_repository.get_schedule(schedule_id)["schedule_id"]),
        )
        with self.assertRaisesRegex(ValueError, "승인된"):
            other_repository.queue_manual_run(
                definition_id, 1, approved_at, "other-owner"
            )
        with self.assertRaises(DBAPIError):
            with _engine(database_url).begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE report_v1.report_definition_versions
                        SET title = '변경 금지'
                        WHERE definition_id = :definition_id AND version = 1
                        """
                    ),
                    {"definition_id": definition_id},
                )
        with self.assertRaises(DBAPIError):
            with _engine(database_url).begin() as connection:
                connection.execute(
                    text(
                        """
                        DELETE FROM report_v1.report_blocks
                        WHERE definition_id = :definition_id AND definition_version = 1
                        """
                    ),
                    {"definition_id": definition_id},
                )
        with self.assertRaises(DBAPIError):
            with _engine(database_url).begin() as connection:
                connection.execute(
                    text(
                        """
                        DELETE FROM report_v1.report_definition_versions
                        WHERE definition_id = :definition_id AND version = 1
                        """
                    ),
                    {"definition_id": definition_id},
                )
        with self.assertRaises(DBAPIError):
            with _engine(database_url).begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE report_v1.report_blocks SET title = '변경 금지'
                        WHERE definition_id = :definition_id AND definition_version = 1
                        """
                    ),
                    {"definition_id": definition_id},
                )


if __name__ == "__main__":
    unittest.main()
