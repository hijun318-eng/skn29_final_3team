from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from inspect import signature
import json
import os
from pathlib import Path
from sys import path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
path.insert(0, str(BACKEND))

from app.api import report_router as report_api  # noqa: E402
from app.authorization import permission_snapshot_id  # noqa: E402
from app.contracts import RequestContext, Role  # noqa: E402
from app.main import app  # noqa: E402
from app.report_contracts import (  # noqa: E402
    ApproveReportVersionRequest,
    CreateManualRunRequest,
    CreateReportDefinitionRequest,
    CreateReportFromArtifactRequest,
    CreateReportScheduleRequest,
    ReplaceReportBlocksRequest,
    ReportArtifactResponse,
    ReportDefinitionListResponse,
    UpdateReportScheduleRequest,
)
from tests.support.report_repository import InMemoryReportRepository  # noqa: E402
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


def report_assistant_request() -> dict[str, object]:
    return {
        "instruction": "Prepare a governed operations summary.",
        "artifact": {
            "artifact_id": "artifact-arbitrary-1",
            "query_id": "query-arbitrary-1",
            "title": "Governed result",
            "narrative": "The governed result was recorded.",
            "evidence": {"source": "runtime"},
            "chart_spec": None,
            "checksum": "a" * 64,
        },
    }


class ReportRegistrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_report_artifact_exposes_exact_persisted_metric_values(self):
        fixture = json.loads(
            (ROOT / "tests" / "backend" / "fixtures" / "api" / "v0.1" / "success.json")
            .read_text(encoding="utf-8")
        )
        result = fixture["data"]["result"]
        evidence = result["evidence"]
        evidence["metric_values"] = [{
            "metric_id": "rooms_sold",
            "result_field": "occupied_rooms",
            "label": "판매 객실 수",
            "definition": "판매 완료 객실 수",
            "unit": "rooms",
            "value": 120,
        }]
        repository = MagicMock()
        repository.get_report_artifact.return_value = {
            "artifact_id": evidence["artifact_id"],
            "trino_query_id": evidence["query_id"],
            "title": "판매 객실 분석",
            "narrative_markdown": result["summary"],
            "data_snapshot_json": result["table"],
            "chart_spec_json": result["chart"],
            "evidence_json": evidence,
            "artifact_checksum": "a" * 64,
        }
        router = MagicMock(repository=repository)

        with patch.object(report_api, "_router", return_value=router):
            response = await report_api.get_report_artifact(
                "definition-1", 1, evidence["artifact_id"], context(Role.ANALYST)
            )

        validated = ReportArtifactResponse.model_validate(response)
        self.assertEqual("occupied_rooms", validated.metrics[0].result_field)
        self.assertEqual(120, validated.metrics[0].value)
        self.assertEqual(validated.metrics, validated.evidence.metric_values)

    async def test_postgres_artifact_reads_and_writes_are_owner_scoped(self):
        from app.adapters.report_repository import PostgresReportRepository

        repository = object.__new__(PostgresReportRepository)
        repository._owner_id = UUID("00000000-0000-0000-0000-000000000001")
        repository._manage_all = True
        session = AsyncMock()
        result = MagicMock()
        result.mappings.return_value.one_or_none.return_value = None
        result.one_or_none.return_value = None
        session.execute.return_value = result

        @asynccontextmanager
        async def session_context():
            yield session

        repository._sessionmaker = MagicMock(side_effect=session_context)
        artifact_id = "00000000-0000-0000-0000-000000000099"

        with self.assertRaises(KeyError):
            await repository.get_assistant_artifact(artifact_id)

        statement, parameters = session.execute.await_args.args
        sql = str(statement)
        self.assertIn("JOIN chat.analysis_requests r", sql)
        self.assertIn("r.user_id = :owner_id", sql)
        self.assertEqual(repository._owner_id, parameters["owner_id"])

        with self.assertRaises(KeyError):
            await repository.get_transfer_artifact(artifact_id)
        transfer_sql = str(session.execute.await_args.args[0])
        self.assertIn("a.evidence_json", transfer_sql)
        self.assertIn("r.user_id = :owner_id", transfer_sql)

        write_session = AsyncMock()
        write_result = MagicMock()
        write_result.one_or_none.return_value = None
        write_session.execute.return_value = write_result
        with self.assertRaises(KeyError):
            await repository._require_owned_artifact(
                write_session,
                UUID(artifact_id),
                "other-owner-query",
            )
        write_sql = str(write_session.execute.await_args.args[0])
        self.assertIn("r.user_id = :owner_id", write_sql)
        self.assertIn("q.trino_query_id = :query_id", write_sql)

        view_spec_id = UUID("00000000-0000-0000-0000-000000000098")
        matching_view = MagicMock()
        matching_view.one_or_none.return_value = (1,)
        session.execute.return_value = matching_view
        await repository._require_artifact_view_spec(
            session,
            view_spec_id,
            UUID(artifact_id),
        )
        view_sql = str(session.execute.await_args.args[0])
        view_parameters = session.execute.await_args.args[1]
        self.assertIn("FROM artifact.view_specs", view_sql)
        self.assertEqual(view_spec_id, view_parameters["view_spec_id"])
        self.assertEqual(UUID(artifact_id), view_parameters["artifact_id"])

        matching_view.one_or_none.return_value = None
        with self.assertRaises(KeyError):
            await repository._require_artifact_view_spec(
                session,
                view_spec_id,
                UUID(artifact_id),
            )

    async def test_report_view_spec_survives_definition_and_replace_roundtrip(self):
        router = create_report_router(InMemoryReportRepository())
        definition_id = str(uuid4())
        block_id = str(uuid4())
        view_spec_id = str(uuid4())
        block = {
            "block_id": block_id,
            "title": "승인 표현",
            "artifact_id": str(uuid4()),
            "query_id": "query-view-spec",
            "view_spec_id": view_spec_id,
            "columns": 12,
            "type": "artifact",
            "x": 0,
            "y": 0,
            "w": 12,
            "h": 12,
            "content": "{}",
        }
        report_context = context(Role.ANALYST)

        with patch.object(report_api, "_router", return_value=router):
            created = await report_api.create_definition(
                CreateReportDefinitionRequest.model_validate({
                    "definition_id": definition_id,
                    "title": "표현 계보 보고서",
                    "blocks": [block],
                }),
                report_context,
            )
            replaced = await report_api.replace_draft_blocks(
                definition_id,
                1,
                ReplaceReportBlocksRequest.model_validate({"blocks": [block]}),
                report_context,
            )

        self.assertEqual(view_spec_id, created["blocks"][0]["view_spec_id"])
        self.assertEqual(view_spec_id, replaced["blocks"][0]["view_spec_id"])

    async def test_analysis_artifact_transfer_builds_server_owned_blocks(self):
        class TransferRepository(InMemoryReportRepository):
            artifact = {
                "artifact_id": "00000000-0000-0000-0000-000000000099",
                "artifact_checksum": "a" * 64,
                "trino_query_id": "query-real",
                "narrative_markdown": "실제 분석 요약",
                "data_snapshot_json": {"columns": ["value"], "rows": [{"value": 1}]},
                "evidence_json": {"metric_values": [{
                    "result_field": "value", "label": "실적", "unit": "count", "value": 1,
                }]},
                "chart_spec_json": {
                    "chart_type": "bar", "x_field": "value", "y_fields": ["value"],
                },
            }

            def get_transfer_artifact(self, artifact_id):
                if artifact_id != self.artifact["artifact_id"]:
                    raise KeyError("본인의 승인된 Analysis Artifact를 찾을 수 없습니다.")
                return self.artifact

            def get_document_source(self, definition_id, version):
                report = self.get_version(definition_id, version)
                artifact = self.artifact
                return {
                    "definition_id": report.definition_id,
                    "version": report.version,
                    "title": report.title,
                    "orientation": report.orientation,
                    "currency_display_unit": report.currency_display_unit,
                    "blocks": [{
                        "block_id": block.block_id,
                        "title": block.title,
                        "type": block.type.value,
                        "x": block.x,
                        "y": block.y,
                        "w": block.w,
                        "h": block.h,
                        "content": block.content,
                        "artifact": {
                            "artifact_id": artifact["artifact_id"],
                            "artifact_checksum": artifact["artifact_checksum"],
                            "query_id": artifact["trino_query_id"],
                            "table": artifact["data_snapshot_json"],
                            "chart_spec": artifact["chart_spec_json"],
                            "evidence": artifact["evidence_json"],
                            "narrative": artifact["narrative_markdown"],
                        },
                    } for block in report.blocks],
                    "artifact_versions": [{
                        "artifact_id": artifact["artifact_id"],
                        "artifact_checksum": artifact["artifact_checksum"],
                        "query_id": artifact["trino_query_id"],
                    }],
                }

        router = create_report_router(TransferRepository())
        payload = CreateReportFromArtifactRequest(
            artifact_id=UUID("00000000-0000-0000-0000-000000000099"),
            title="실제 Artifact 보고서",
        )
        with patch.object(report_api, "_router", return_value=router):
            created = await report_api.create_draft_from_analysis_artifact(
                payload, context(Role.ANALYST)
            )

        self.assertEqual("draft", created["status"])
        self.assertEqual("landscape", created["orientation"])
        self.assertEqual("auto", created["currency_display_unit"])
        self.assertEqual(1, len(created["blocks"]))
        block = created["blocks"][0]
        self.assertEqual("artifact", block["type"])
        self.assertEqual("실제 Artifact 보고서", block["title"])
        self.assertEqual(str(payload.artifact_id), block["artifact_id"])
        self.assertEqual("query-real", block["query_id"])
        self.assertEqual((0, 0, 12, 12), (block["x"], block["y"], block["w"], block["h"]))
        self.assertEqual({
            "schemaVersion": "ANSWER-ARTIFACT-BLOCK-v1",
            "presentationMode": "standard",
            "sizeMode": "auto",
            "visibleViews": ["summary", "kpi", "chart", "table"],
        }, json.loads(block["content"]))

        reloaded = await router.get_version(created["definition_id"], 1)
        self.assertEqual([block], reloaded["blocks"])
        self.assertEqual(
            ["table"],
            report_api._artifact_visible_views({
                "narrative_markdown": "",
                "data_snapshot_json": {"columns": ["value"], "rows": [{"value": 0}]},
                "evidence_json": {"metric_values": []},
                "chart_spec_json": None,
            }),
        )

        fake_html = type(
            "FakeHTML",
            (),
            {
                "__init__": lambda self, **kwargs: None,
                "write_pdf": lambda self, **kwargs: b"%PDF-1.7\naggregate",
            },
        )
        from app.services.report.document import approve_report_document

        with patch.dict(sys.modules, {"weasyprint": SimpleNamespace(HTML=fake_html)}):
            approved = await approve_report_document(
                router.repository,
                created["definition_id"],
                1,
                datetime(2026, 8, 14, tzinfo=timezone.utc),
                None,
            )
        self.assertEqual(DefinitionStatus.APPROVED, approved.status)
        document = router.repository.get_document(created["definition_id"], 1)
        self.assertTrue(document["pdf_bytes"].startswith(b"%PDF-"))
        self.assertIn('data-visible-views="summary kpi chart table"', document["html_snapshot"])

        with patch.object(report_api, "_router", return_value=router), self.assertRaises(HTTPException) as missing:
            await report_api.create_draft_from_analysis_artifact(
                payload.model_copy(update={"artifact_id": uuid4()}),
                context(Role.ANALYST),
            )
        self.assertEqual(404, missing.exception.status_code)

    def test_aggregate_artifact_block_is_an_additive_api_type(self):
        payload = ReplaceReportBlocksRequest.model_validate({
            "title": "Analysis Artifact Review",
            "orientation": "landscape",
            "currency_display_unit": "billion",
            "blocks": [{
            "block_id": "00000000-0000-0000-0000-000000000011",
            "title": "Analysis Artifact",
            "type": "artifact",
            "artifact_id": "00000000-0000-0000-0000-000000000099",
            "query_id": "query-real",
            "columns": 12,
            "w": 12,
            "h": 12,
            "content": '{"presentationMode":"detail","visibleViews":["summary","kpi","chart","table"]}',
        }]})

        self.assertEqual("artifact", payload.blocks[0].type)
        self.assertEqual("Analysis Artifact Review", payload.title)
        self.assertEqual("landscape", payload.orientation)
        self.assertEqual("billion", payload.currency_display_unit)
        with self.assertRaises(ValidationError):
            ReplaceReportBlocksRequest.model_validate({
                "blocks": [], "currency_display_unit": "trillion"
            })

    def test_report_routes_require_authentication_and_report_admin(self):
        dependency = signature(report_api.report_admin_context).parameters["context"]
        self.assertIn("analysis_context", repr(dependency.annotation))
        self.assertEqual(Role.REPORT_ADMIN, report_api.report_admin_context(context()).role)
        for role in (Role.ANALYST, Role.DATA_ADMIN):
            with self.assertRaises(HTTPException) as denied:
                report_api.report_admin_context(context(role))
            self.assertEqual(403, denied.exception.status_code)

    def test_report_repository_scope_follows_authenticated_role(self):
        for role, manage_all in (
            (Role.ANALYST, False),
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
                    product_release_id=None,
                    permission_snapshot_id=permission_snapshot_id(
                        context(role).user_id, role
                    ),
                    semantic_release_id=None,
                )

    async def test_report_v11_routes_replace_draft_and_keep_result_ingestion_internal(self):
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
                (await report_api.create_definition(
                    CreateReportDefinitionRequest.model_validate(definition), report_context
                ))["status"],
            )
            with self.assertRaises(HTTPException) as draft_run:
                await report_api.create_run_internal(run, report_context)
            self.assertEqual(409, draft_run.exception.status_code)
            replaced = await report_api.replace_draft_blocks(
                "report-1",
                1,
                ReplaceReportBlocksRequest.model_validate({"blocks": [{
                    "block_id": "text-1", "title": "해석", "type": "text",
                    "content": "관측 결과", "x": 0, "y": 0, "w": 12, "h": 2,
                }]}),
                report_context,
            )
            self.assertEqual("text", replaced["blocks"][0]["type"])
            listed = await report_api.list_definitions(report_context)
            validated_list = ReportDefinitionListResponse.model_validate(listed)
            self.assertEqual(1, len(validated_list.items))
            self.assertIsNone(validated_list.items[0].blocks[0].view_spec_id)
            fake_html = type(
                "FakeHTML",
                (),
                {
                    "__init__": lambda self, **kwargs: None,
                    "write_pdf": lambda self, **kwargs: b"%PDF-1.7\ncontract",
                },
            )
            with patch.dict(sys.modules, {"weasyprint": SimpleNamespace(HTML=fake_html)}):
                self.assertEqual(
                    "approved",
                    (await report_api.approve_version(
                        "report-1",
                        1,
                        ApproveReportVersionRequest(approved_at=approved_at),
                        report_context,
                    ))["status"],
                )
            with self.assertRaises(HTTPException) as immutable:
                await report_api.replace_draft_blocks(
                    "report-1", 1, ReplaceReportBlocksRequest(blocks=[]), report_context
                )
            self.assertEqual(409, immutable.exception.status_code)
            self.assertEqual(
                "run-1", (await report_api.create_run_internal(run, report_context))["run_id"]
            )
            self.assertEqual(
                "run-1", (await report_api.list_runs(report_context))["items"][0]["run_id"]
            )
            self.assertEqual(
                "run-1", (await report_api.get_run("run-1", report_context))["run_id"]
            )
            with self.assertRaises(HTTPException) as duplicate:
                await report_api.create_run_internal(run, report_context)
            self.assertEqual(409, duplicate.exception.status_code)

            command_payload = {
                "definition_id": "report-1", "version": 1,
                "idempotency_key": "manual-1",
            }
            command = await report_api.create_manual_run_command(
                CreateManualRunRequest.model_validate(command_payload), report_context
            )
            self.assertEqual("queued", command["status"])
            self.assertEqual(
                report_context.as_of.isoformat(), command["as_of"].split("T", 1)[0]
            )
            self.assertNotIn("run_id", command)
            with self.assertRaises(ValidationError):
                CreateManualRunRequest.model_validate(
                    {**command_payload, "idempotency_key": " "}
                )
            for forbidden in (
                "as_of", "command_id", "run_id", "status", "policy_version", "context_hash",
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

        payload = _openai_payload(
            "gpt-5.4-mini", "report_assistant", report_assistant_request()
        )
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

    async def test_report_assistant_awaits_the_async_model_transport(self):
        from app.adapters.report_assistant import generate_report_draft

        response = {
            "title": "Operations report",
            "executive_summary": "Revenue remained stable.",
            "table_title": "Revenue detail",
            "chart_title": "Revenue trend",
        }
        transport = AsyncMock(return_value=response)
        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_ENDPOINT": "https://model.invalid",
                    "OPENAI_API_KEY": "test-token",
                    "OPENAI_MODEL": "gpt-5.4-mini",
                },
            ),
            patch(
                "app.adapters.report_assistant.openai_transport",
                transport,
            ),
        ):
            proposal, trace = await generate_report_draft(report_assistant_request())

        self.assertEqual(response, proposal)
        self.assertEqual("gpt-5.4-mini", trace["model_version"])
        transport.assert_awaited_once()


@unittest.skipUnless(
    os.getenv("REPORT_DATABASE_URL") and os.getenv("REPORT_DATABASE_DISPOSABLE") == "1",
    "disposable temporary report DB is required",
)
class PostgresReportRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        from app.database import dispose_database

        await dispose_database()

    async def test_display_settings_survive_reload_and_immutable_pdf_approval(self):
        from app.adapters.report_repository import PostgresReportRepository
        from app.services.report.document import approve_report_document

        database_url = os.environ["REPORT_DATABASE_URL"]
        repository = PostgresReportRepository(
            database_url, uuid4()
        )
        definition_id = str(uuid4())
        block = ReportBlock(
            str(uuid4()),
            "핵심 요약",
            None,
            12,
            None,
            BlockType.TEXT,
            content="저장된 설정으로 확정합니다.",
        )
        await repository.add_draft(
            ReportDefinitionVersion(
                definition_id,
                1,
                DefinitionStatus.DRAFT,
                "설정 영속화 검증 보고서",
                (block,),
            )
        )

        saved = await repository.replace_draft_blocks(
            definition_id,
            1,
            (block,),
            title="제목·설정 영속화 검증 보고서",
            orientation="landscape",
            currency_display_unit="million",
        )
        reloaded = await repository.get_version(definition_id, 1)
        self.assertEqual(("landscape", "million"), (
            saved.orientation, saved.currency_display_unit
        ))
        self.assertEqual(("landscape", "million"), (
            reloaded.orientation, reloaded.currency_display_unit
        ))
        self.assertEqual("제목·설정 영속화 검증 보고서", saved.title)
        self.assertEqual(saved.title, reloaded.title)

        approved = await approve_report_document(
            repository,
            definition_id,
            1,
            datetime.now(timezone.utc),
            None,
        )
        document = await repository.get_document(definition_id, 1)
        self.assertEqual(DefinitionStatus.APPROVED, approved.status)
        self.assertEqual("landscape", document["orientation"])
        self.assertEqual("million", document["currency_display_unit"])
        self.assertIn(
            '<meta name="answervice-orientation" content="landscape">',
            document["html_snapshot"],
        )
        self.assertIn(
            '<meta name="answervice-currency-display-unit" content="million">',
            document["html_snapshot"],
        )
        self.assertTrue(document["pdf_bytes"].startswith(b"%PDF-"))

    async def test_database_owner_scope_layout_history_and_concurrent_idempotency(self):
        from app.adapters.report_repository import PostgresReportRepository
        from sqlalchemy import create_engine, make_url, text
        from sqlalchemy.exc import DBAPIError

        database_url = os.environ["REPORT_DATABASE_URL"]
        sync_database_url = make_url(database_url).set(drivername="postgresql+psycopg")
        test_engine = create_engine(sync_database_url)
        self.addCleanup(test_engine.dispose)
        definition_id = str(uuid4())
        block_id = str(uuid4())
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
        await repository.add_draft(
            ReportDefinitionVersion(
                definition_id,
                1,
                DefinitionStatus.DRAFT,
                "운영 보고서",
                (
                    ReportBlock(
                        block_id,
                        "객실 매출",
                        None,
                        6,
                        None,
                        BlockType.TEXT,
                        content="검증된 설명",
                    ),
                ),
            )
        )
        with self.assertRaises(KeyError):
            await other_repository.get_version(definition_id, 1)
        self.assertEqual((), await other_repository.list_definitions())
        self.assertEqual(
            definition_id,
            (await admin_repository.get_version(definition_id, 1)).definition_id,
        )
        self.assertIn(
            definition_id,
            {
                item.definition_id
                for item in await admin_repository.list_definitions()
            },
        )
        right_block = ReportBlock(
            str(uuid4()), "오른쪽 해석", None, 6, None,
            BlockType.TEXT, 6, 0, 6, 2, "오른쪽 관측 결과",
        )
        left_block = ReportBlock(
            str(uuid4()), "왼쪽 해석", None, 6, None,
            BlockType.TEXT, 0, 0, 6, 2, "왼쪽 관측 결과",
        )
        replaced = await repository.replace_draft_blocks(
            definition_id,
            1,
            (right_block, left_block),
            orientation="landscape",
            currency_display_unit="hundredMillion",
        )
        self.assertEqual(
            [left_block.block_id, right_block.block_id],
            [block.block_id for block in replaced.blocks],
        )
        self.assertEqual("landscape", replaced.orientation)
        self.assertEqual("hundredMillion", replaced.currency_display_unit)
        reloaded = await repository.get_version(definition_id, 1)
        self.assertEqual("landscape", reloaded.orientation)
        self.assertEqual("hundredMillion", reloaded.currency_display_unit)
        with self.assertRaises(DBAPIError):
            with test_engine.begin() as connection:
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
            with test_engine.begin() as connection:
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
            await repository.add_run(run)
        await admin_repository.approve(definition_id, 1, approved_at)
        with self.assertRaisesRegex(ValueError, "draft Report version"):
            await repository.replace_draft_blocks(definition_id, 1, ())
        await repository.add_run(run)
        self.assertEqual(run.run_id, (await repository.get_run(run.run_id)).run_id)
        self.assertEqual(
            run.run_id,
            (await admin_repository.get_run(run.run_id)).run_id,
        )
        self.assertEqual(1, len(await repository.list_runs(definition_id)))
        with self.assertRaises(KeyError):
            await other_repository.get_run(run.run_id)
        self.assertEqual((), await other_repository.list_runs())
        with self.assertRaisesRegex(ValueError, "run_id"):
            await repository.add_run(run)
        commands = await asyncio.gather(
            *(
                repository.queue_manual_run(
                    definition_id, 1, approved_at, "same-request"
                )
                for _ in range(8)
            )
        )
        self.assertEqual(1, len({command.command_id for command in commands}))
        schedule_id = str(uuid4())
        schedule = await repository.create_schedule(
            schedule_id, definition_id, 1, "daily", "Asia/Seoul", approved_at
        )
        self.assertEqual(schedule_id, str(schedule["schedule_id"]))
        self.assertEqual(1, len(await repository.list_schedules()))
        self.assertEqual((), await other_repository.list_schedules())
        self.assertEqual(
            (schedule_id,),
            await repository.list_due_schedule_ids(approved_at),
        )
        disabled = await repository.set_schedule_enabled(schedule_id, False)
        self.assertFalse(disabled["enabled"])
        self.assertEqual((), await repository.list_due_schedule_ids(approved_at))
        with self.assertRaises(KeyError):
            await other_repository.set_schedule_enabled(schedule_id, True)
        self.assertTrue(
            (await repository.set_schedule_enabled(schedule_id, True))["enabled"]
        )
        scheduled, scheduled_command = await repository.queue_due_schedule(
            schedule_id, approved_at.replace(minute=1)
        )
        self.assertIsNotNone(scheduled_command)
        await repository.claim_manual_run(scheduled_command.command_id)
        scheduled_run = await repository.finish_manual_run(scheduled_command.command_id)
        scheduled = await repository.complete_due_schedule(
            schedule_id, scheduled_command.as_of, scheduled_run.run_id
        )
        self.assertEqual(scheduled_run.run_id, str(scheduled["last_run_id"]))
        unchanged, duplicate_command = await repository.queue_due_schedule(
            schedule_id, approved_at.replace(minute=1)
        )
        self.assertIsNone(duplicate_command)
        self.assertEqual(scheduled["next_run_at"], unchanged["next_run_at"])
        with self.assertRaises(KeyError):
            await other_repository.get_schedule(schedule_id)
        self.assertEqual(
            schedule_id,
            str((await admin_repository.get_schedule(schedule_id))["schedule_id"]),
        )
        with self.assertRaisesRegex(ValueError, "승인된"):
            await other_repository.queue_manual_run(
                definition_id, 1, approved_at, "other-owner"
            )
        with self.assertRaises(DBAPIError):
            with test_engine.begin() as connection:
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
            with test_engine.begin() as connection:
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
            with test_engine.begin() as connection:
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
            with test_engine.begin() as connection:
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
