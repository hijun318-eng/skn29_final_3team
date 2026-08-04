from __future__ import annotations

from datetime import datetime, timezone
from inspect import signature
import os
from pathlib import Path
from sys import path
import unittest
from unittest.mock import patch
from uuid import UUID

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

    def test_report_approved_version_is_immutable_and_only_it_can_run(self):
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
                report_api.create_run(run, report_context)
            self.assertEqual(409, draft_run.exception.status_code)
            self.assertEqual(
                "approved",
                report_api.approve_version("report-1", 1, approved_at, report_context)["status"],
            )
            with self.assertRaises(HTTPException) as immutable:
                report_api.approve_version("report-1", 1, approved_at, report_context)
            self.assertEqual(409, immutable.exception.status_code)
            self.assertEqual("run-1", report_api.create_run(run, report_context)["run_id"])
            with self.assertRaises(HTTPException) as duplicate:
                report_api.create_run(run, report_context)
            self.assertEqual(409, duplicate.exception.status_code)

    def test_report_routes_do_not_change_frozen_openapi_contract(self):
        paths = {route.path for route in report_api.report_router.routes}
        self.assertIn("/reports/definitions", paths)
        self.assertIn("/reports/runs", paths)
        self.assertFalse(any(path.startswith("/reports") for path in app.openapi()["paths"]))


@unittest.skipUnless(os.getenv("REPORT_DATABASE_URL"), "temporary report DB is required")
class PostgresReportRepositoryTest(unittest.TestCase):
    def test_database_keeps_approved_version_and_run_id_invariants(self):
        from app.adapters.report_repository import PostgresReportRepository, _engine
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        database_url = os.environ["REPORT_DATABASE_URL"]
        definition_id = "00000000-0000-0000-0000-000000000101"
        approved_at = datetime(2026, 8, 4, tzinfo=timezone.utc)
        repository = PostgresReportRepository(database_url, context().user_id)
        repository.add_draft(
            ReportDefinitionVersion(
                definition_id,
                1,
                DefinitionStatus.DRAFT,
                "운영 보고서",
                (
                    ReportBlock(
                        "00000000-0000-0000-0000-000000000301",
                        "객실 매출",
                        "00000000-0000-0000-0000-000000000401",
                        6,
                    ),
                ),
            )
        )
        run = ReportRun(
            "00000000-0000-0000-0000-000000000201",
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
        repository.add_run(run)
        with self.assertRaisesRegex(ValueError, "run_id"):
            repository.add_run(run)
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
