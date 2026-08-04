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


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
path.insert(0, str(BACKEND))

from app.api import report_router as report_api  # noqa: E402
from app.contracts import RequestContext, Role  # noqa: E402
from app.main import app  # noqa: E402
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
    def test_report_routes_require_authentication_and_report_admin(self):
        dependency = signature(report_api.report_admin_context).parameters["context"]
        self.assertIn("analysis_context", repr(dependency.annotation))
        self.assertEqual(Role.REPORT_ADMIN, report_api.report_admin_context(context()).role)
        for role in (Role.HOTEL_ANALYST, Role.DATA_ADMIN):
            with self.assertRaises(HTTPException) as denied:
                report_api.report_admin_context(context(role))
            self.assertEqual(403, denied.exception.status_code)

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
            self.assertEqual("draft", report_api.create_definition(definition, report_context)["status"])
            with self.assertRaises(HTTPException) as draft_run:
                report_api.create_run_internal(run, report_context)
            self.assertEqual(409, draft_run.exception.status_code)
            replaced = report_api.replace_draft_blocks(
                "report-1",
                1,
                {"blocks": [{
                    "block_id": "text-1", "title": "해석", "type": "text",
                    "content": "관측 결과", "x": 0, "y": 0, "w": 12, "h": 2,
                }]},
                report_context,
            )
            self.assertEqual("text", replaced["blocks"][0]["type"])
            self.assertEqual(1, len(report_api.list_definitions(report_context)["items"]))
            self.assertEqual(
                "approved",
                report_api.approve_version("report-1", 1, approved_at, report_context)["status"],
            )
            with self.assertRaises(HTTPException) as immutable:
                report_api.replace_draft_blocks("report-1", 1, {"blocks": []}, report_context)
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
            command = report_api.create_manual_run_command(command_payload, report_context)
            self.assertEqual("queued", command["status"])
            self.assertNotIn("run_id", command)
            with self.assertRaises(HTTPException) as empty_idempotency:
                report_api.create_manual_run_command(
                    {**command_payload, "idempotency_key": " "}, report_context
                )
            self.assertEqual(422, empty_idempotency.exception.status_code)
            for forbidden in (
                "command_id", "run_id", "status", "policy_version", "context_hash",
                "watermark", "blocks", "result",
            ):
                with self.subTest(forbidden=forbidden):
                    with self.assertRaises(HTTPException) as untrusted:
                        report_api.create_manual_run_command(
                            {**command_payload, forbidden: "client-value"}, report_context
                        )
                    self.assertEqual(422, untrusted.exception.status_code)

    def test_report_routes_do_not_change_frozen_openapi_contract(self):
        paths = {route.path for route in report_api.report_router.routes}
        self.assertIn("/reports/definitions", paths)
        self.assertIn("/reports/runs", paths)
        self.assertIn("/reports/runs/manual", paths)
        self.assertNotIn(
            ("/reports/runs", "POST"),
            {(route.path, method) for route in report_api.report_router.routes for method in route.methods},
        )
        self.assertFalse(any(path.startswith("/reports") for path in app.openapi()["paths"]))


@unittest.skipUnless(os.getenv("REPORT_DATABASE_URL"), "temporary report DB is required")
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
        text_block = ReportBlock(
            str(uuid4()), "해석", None, 12, None,
            BlockType.TEXT, 0, 0, 12, 2, "관측 결과",
        )
        self.assertEqual(
            BlockType.TEXT,
            repository.replace_draft_blocks(definition_id, 1, (text_block,)).blocks[0].type,
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
        repository.approve(definition_id, 1, approved_at)
        with self.assertRaisesRegex(ValueError, "draft Report version"):
            repository.replace_draft_blocks(definition_id, 1, ())
        repository.add_run(run)
        self.assertEqual(run.run_id, repository.get_run(run.run_id).run_id)
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
