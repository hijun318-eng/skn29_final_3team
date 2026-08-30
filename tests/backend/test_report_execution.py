from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from functools import wraps
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
sys.path.insert(0, str(BACKEND))

from app.auth_principal_store import Principal  # noqa: E402
from app.authorization import permission_snapshot_id  # noqa: E402
from app.contracts import AnalysisStatus, Role  # noqa: E402
from app.services.report.execution import (  # noqa: E402
    AnalysisDefinitionReplay,
    ReplayOutcome,
    ReportExecutionService,
)
from app.services.report.document import approve_report_document  # noqa: E402
from app.adapters.report_repository import PostgresReportRepository  # noqa: E402
from app.database import dispose_database  # noqa: E402
from tests.support.semantic_snapshot_fixture import (  # noqa: E402
    approved_semantic_snapshot_fixture,
)
from src.report.domain import (  # noqa: E402
    BlockFailureCode,
    BlockRunStatus,
    BlockType,
    ReportRun,
    DefinitionStatus,
    ReportBlock,
    ReportDefinitionVersion,
    ManualRunCommand,
    RunStatus,
)


OWNER = UUID("00000000-0000-0000-0000-000000000001")
AS_OF = datetime(2026, 8, 14, 15, tzinfo=timezone.utc)


class _RedactedDatabaseUrl(str):
    def __repr__(self) -> str:
        return "'<redacted-test-database-url>'"


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        if sys.platform == "win32":
            loop = asyncio.SelectorEventLoop()
            try:
                return loop.run_until_complete(function(*args, **kwargs))
            finally:
                loop.close()
        return asyncio.run(function(*args, **kwargs))

    return run


class _Gate:
    def __init__(self, acquired: bool = True) -> None:
        self.acquired = acquired
        self.releases = 0

    async def acquire(self, wait_seconds=0):
        self.wait_seconds = wait_seconds
        return self.acquired

    def release(self):
        self.releases += 1


class _AnalysisRepository:
    def __init__(self) -> None:
        self.request_id = uuid4()
        self.finished = None
        self.context_receipts = []

    async def get_definition_for_report(self, definition_id, version):
        snapshot = approved_semantic_snapshot_fixture(
            execution_as_of=date(2026, 8, 15),
            period_start="2026-06-01",
            period_end="2026-07-01",
            product_release_id="product-report-v1",
            semantic_release_id="semantic-report-v1",
            permission_snapshot_id=permission_snapshot_id(OWNER, Role.ANALYST),
        )
        return {
            "definition_id": definition_id,
            "version": version,
            "question": "지난달 객실 매출",
            "parameters": {
                "period_start": "2026-06-01",
                "period_end_exclusive": "2026-07-01",
                "property": "walkerhill",
            },
            "semantic_request": {
                "resolved_slots": {
                    "metric_id": "reviewed_measure",
                    "metric_ids": ["reviewed_measure"],
                    "dimension_fields": [],
                    "user_filters": [],
                    "time_range": {
                        "start": "2026-06-01",
                        "end_exclusive": "2026-07-01",
                    },
                    "comparison_time_range": None,
                    "analysis_operation": "aggregate",
                    "analysis_time_bucket": None,
                    "result_limit": None,
                }
            },
            "approved_semantic_snapshot": snapshot.model_dump(mode="json"),
        }

    async def begin_run(self, definition, context, as_of, idempotency_key, parameters):
        self.request_id = context.request_id
        self.context = context
        self.as_of = as_of
        self.idempotency_key = idempotency_key
        self.parameters = parameters
        return self.request_id, True

    async def finish_run(self, request_id, response, execution):
        self.finished = (request_id, response, execution)

    async def persist_context_receipt(self, context, package):
        self.context_receipts.append((context, package))

    async def fail_run(self, request_id, error_type="UNSUPPORTED"):
        self.finished = (request_id, error_type)

    async def get_run_artifact(self, request_id):
        return {
            "artifact_id": uuid4(),
            "query_id": "query-new",
            "artifact_checksum": "a" * 64,
            "evidence": {"policy_version": "policy-current"},
        }


class _ActiveReleasePlatform:
    async def get_active_context_release(self):
        return "semantic-report-v1"

    async def get_catalog_readiness(self):
        return {"runtime_catalog": "ready"}, "product-report-v1"


class _Controller:
    def __init__(self):
        self.data_platform = _ActiveReleasePlatform()

    async def submit(self, payload, context, execution_sink, *, context_receipt_sink):
        self.payload = payload
        self.context = context
        await context_receipt_sink(context, {"package_hash": "report-context"})
        execution_sink({"plan": {}, "query": {}, "package": {}})
        return SimpleNamespace(
            data=SimpleNamespace(status=AnalysisStatus.SUCCEEDED),
            error=None,
        )


@async_test
async def test_analysis_definition_replay_reseals_period_and_persists_new_evidence():
    repository = _AnalysisRepository()
    controller = _Controller()
    gate = _Gate()
    replay = AnalysisDefinitionReplay("postgresql://test", controller, gate)

    with patch(
        "app.services.report.execution.PostgresAnalysisRepository",
        return_value=repository,
    ), patch(
        "app.services.report.execution.require_active_subject_with_capability",
        return_value=Principal(OWNER, Role.ANALYST),
    ):
        outcome = await replay.execute(
            owner_id=OWNER,
            definition_id=str(uuid4()),
            definition_version=3,
            as_of=AS_OF,
            idempotency_key="report:run:block",
            product_release_id="product-report-v1",
            permission_snapshot_id=permission_snapshot_id(OWNER, Role.ANALYST),
            semantic_release_id="semantic-report-v1",
        )

    assert outcome.status is BlockRunStatus.SUCCESS
    assert len(repository.context_receipts) == 1
    assert repository.context_receipts[0][0].request_id == repository.request_id
    assert outcome.query_id == "query-new"
    assert outcome.snapshot_checksum == "a" * 64
    assert outcome.policy_version == "policy-current"
    assert repository.parameters == {
        "window_start": "2026-06-01",
        "window_end": "2026-07-01",
    }
    assert controller.payload.parameters == repository.parameters
    assert controller.payload.resolved_slots is None
    assert repository.as_of.isoformat() == "2026-08-15"
    assert repository.context.product_release_id == "product-report-v1"
    assert repository.context.semantic_release_id == "semantic-report-v1"
    assert repository.context.require_fresh_query is True
    assert repository.finished[0] == repository.request_id
    assert gate.releases == 1


@async_test
async def test_analysis_definition_replay_stores_rate_limit_as_recovery_failure():
    repository = _AnalysisRepository()
    replay = AnalysisDefinitionReplay(
        "postgresql://test",
        _Controller(),
        _Gate(acquired=False),
    )

    with patch(
        "app.services.report.execution.PostgresAnalysisRepository",
        return_value=repository,
    ), patch(
        "app.services.report.execution.require_active_subject_with_capability",
        return_value=Principal(OWNER, Role.ANALYST),
    ):
        outcome = await replay.execute(
            owner_id=OWNER,
            definition_id=str(uuid4()),
            definition_version=3,
            as_of=AS_OF,
            idempotency_key="report:rate-limited",
            product_release_id="product-report-v1",
            permission_snapshot_id=permission_snapshot_id(OWNER, Role.ANALYST),
            semantic_release_id="semantic-report-v1",
        )

    assert outcome.status is BlockRunStatus.FAILED
    assert outcome.failure_code is BlockFailureCode.RATE_LIMITED
    assert repository.finished == (repository.request_id, "RECOVERY")


@async_test
async def test_analysis_definition_replay_snapshot_persistence_failure_is_terminal():
    repository = _AnalysisRepository()
    controller = _Controller()
    replay = AnalysisDefinitionReplay(
        "postgresql://test",
        controller,
        _Gate(),
    )

    with patch(
        "app.services.report.execution.PostgresAnalysisRepository",
        return_value=repository,
    ), patch(
        "app.services.report.execution.require_active_subject_with_capability",
        return_value=Principal(OWNER, Role.ANALYST),
    ), patch.object(
        repository,
        "finish_run",
        side_effect=ValueError("snapshot validation failed"),
    ):
        outcome = await replay.execute(
            owner_id=OWNER,
            definition_id=str(uuid4()),
            definition_version=3,
            as_of=AS_OF,
            idempotency_key="report:snapshot-persistence-failed",
            product_release_id="product-report-v1",
            permission_snapshot_id=permission_snapshot_id(OWNER, Role.ANALYST),
            semantic_release_id="semantic-report-v1",
        )

    assert outcome.failure_code is BlockFailureCode.ARTIFACT_PERSIST_FAILED
    assert repository.finished == (repository.request_id, "PERSISTENCE")


class _ReportRepository:
    def __init__(self) -> None:
        self.records = []
        self.run = ReportRun(
            "00000000-0000-0000-0000-000000000010",
            "00000000-0000-0000-0000-000000000020",
            1,
            AS_OF,
            "policy-current",
            "context-current",
            {},
            RunStatus.PARTIAL,
            product_release_id="product-report-v1",
            permission_snapshot_id="permission-report-v1",
            semantic_release_id="semantic-report-v1",
        )

    async def claim_manual_run(self, command_id):
        self.command_id = command_id
        return {
            "claimed": True,
            "run_id": self.run.run_id,
            "owner_id": OWNER,
            "as_of": AS_OF,
            "product_release_id": self.run.product_release_id,
            "permission_snapshot_id": self.run.permission_snapshot_id,
            "semantic_release_id": self.run.semantic_release_id,
            "blocks": (
                {
                    "block_id": "block-1",
                    "analysis_definition_id": "analysis-1",
                    "analysis_definition_version": 1,
                },
                {
                    "block_id": "block-2",
                    "analysis_definition_id": "analysis-2",
                    "analysis_definition_version": 2,
                },
            ),
        }

    async def record_block_run(self, run_id, block_id, **outcome):
        self.records.append((run_id, block_id, outcome))

    async def finish_manual_run(self, command_id):
        self.finished_command = command_id
        return self.run


class _Replay:
    def __init__(self) -> None:
        self.calls = []

    async def execute(self, **payload):
        self.calls.append(payload)
        if payload["definition_id"] == "analysis-1":
            return ReplayOutcome(
                BlockRunStatus.SUCCESS,
                request_id=str(uuid4()),
                artifact_id=str(uuid4()),
                query_id="new-query-1",
                snapshot_checksum="b" * 64,
                policy_version="policy-current",
            )
        return ReplayOutcome(
            BlockRunStatus.FAILED,
            failure_code=BlockFailureCode.QUERY_SOURCE_FAILED,
            failure_message="The approved source is unavailable.",
        )


@async_test
async def test_report_execution_replays_every_block_and_isolates_typed_failure():
    repository = _ReportRepository()
    replay = _Replay()
    service = ReportExecutionService(repository, replay)

    run = await service.execute_manual_run("command-1")

    assert run.status is RunStatus.PARTIAL
    assert len(replay.calls) == 2
    assert len(repository.records) == 2
    assert repository.records[0][2]["query_id"] == "new-query-1"
    assert repository.records[1][2]["failure_code"] is BlockFailureCode.QUERY_SOURCE_FAILED
    assert replay.calls[0]["idempotency_key"].endswith(":block-1")
    assert replay.calls[0]["product_release_id"] == "product-report-v1"
    assert replay.calls[0]["permission_snapshot_id"] == "permission-report-v1"
    assert replay.calls[0]["semantic_release_id"] == "semantic-report-v1"
    assert repository.finished_command == "command-1"


@async_test
async def test_scheduled_execution_uses_the_same_manual_replay_path():
    class ScheduledRepository(_ReportRepository):
        async def queue_due_schedule(self, schedule_id, now):
            self.scheduled_for = now
            return {"schedule_id": schedule_id}, ManualRunCommand(
                "command-scheduled", self.run.definition_id, 1, now, "schedule-key"
            )

        async def complete_due_schedule(self, schedule_id, scheduled_for, run_id):
            self.completed_schedule = (schedule_id, scheduled_for, run_id)
            return {"schedule_id": schedule_id, "last_run_id": run_id}

    repository = ScheduledRepository()
    replay = _Replay()
    service = ReportExecutionService(repository, replay)

    schedule, run = await service.run_due_schedule("schedule-1", AS_OF)

    assert run is repository.run
    assert schedule["last_run_id"] == run.run_id
    assert repository.command_id == "command-scheduled"
    assert len(replay.calls) == 2
    assert repository.completed_schedule == ("schedule-1", AS_OF, run.run_id)


@async_test
async def test_concurrent_schedule_poll_does_not_advance_a_running_command():
    class ConcurrentRepository(_ReportRepository):
        def __init__(self):
            super().__init__()
            self.run = ReportRun(
                self.run.run_id,
                self.run.definition_id,
                self.run.definition_version,
                self.run.as_of,
                self.run.policy_version,
                self.run.context_hash,
                self.run.watermark,
                RunStatus.RUNNING,
            )

        async def queue_due_schedule(self, schedule_id, now):
            return {"schedule_id": schedule_id, "next_run_at": now}, ManualRunCommand(
                "command-running", self.run.definition_id, 1, now, "schedule-key"
            )

        async def claim_manual_run(self, command_id):
            return {"claimed": False, "run_id": self.run.run_id, "blocks": ()}

        async def get_run(self, run_id):
            assert run_id == self.run.run_id
            return self.run

        async def complete_due_schedule(self, *_args):
            raise AssertionError("running schedule must not advance")

    repository = ConcurrentRepository()
    service = ReportExecutionService(repository, _Replay())

    schedule, run = await service.run_due_schedule("schedule-1", AS_OF)

    assert run is None
    assert schedule["next_run_at"] == AS_OF


@pytest.fixture(scope="module")
def replay_database():
    configured = os.getenv("MIGRATION_TEST_DATABASE_URL")
    if not configured:
        pytest.skip("MIGRATION_TEST_DATABASE_URL is not configured")
    base = make_url(configured)
    database = f"report_replay_{uuid4().hex[:8]}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
    admin.dispose()
    url = base.set(database=database).render_as_string(hide_password=False)
    environment = os.environ.copy()
    environment["APP_DATABASE_URL"] = url
    environment["APP_DB_USER"] = base.username or "postgres"
    environment["APP_CATALOG_PUBLISHER_USER"] = environment["APP_DB_USER"]
    migrated = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if migrated.returncode:
        raise RuntimeError(migrated.stdout + migrated.stderr)
    try:
        yield _RedactedDatabaseUrl(url)
    finally:
        engine = create_engine(url)
        engine.dispose()
        admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database AND pid <> pg_backend_pid()"
                ),
                {"database": database},
            )
            connection.exec_driver_sql(f'DROP DATABASE "{database}"')
        admin.dispose()


def _seed_analysis_evidence(engine, *, definition_id, request_id, query_execution_id, artifact_id, query_id):
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO analysis_v1.analysis_definitions
                (definition_id, version, owner_id, title, question_text_redacted,
                 parameters_json, parameter_hash, semantic_request_json,
                 parameter_schema_json, is_saved)
            VALUES (:definition_id, 1, :owner_id, 'Replay source',
                    'recognized room revenue summary', '{}'::jsonb, :hash,
                    '{}'::jsonb, '{}'::jsonb, false)
            ON CONFLICT (definition_id, version) DO NOTHING
        """), {"definition_id": definition_id, "owner_id": OWNER, "hash": "a" * 64})
        connection.execute(text("""
            INSERT INTO chat.analysis_requests
                (request_id, request_type, user_id, user_role,
                 question_text_redacted, question_hash, ambiguity_status,
                 sql_policy_version, status, trace_id, started_at, completed_at)
            VALUES (:request_id, 'CHAT', :owner_id, 'analyst',
                    'recognized room revenue summary', :hash, 'CLEAR',
                    'policy-current', 'SUCCEEDED', :trace_id, now(), now())
        """), {
            "request_id": request_id, "owner_id": OWNER,
            "hash": "b" * 64, "trace_id": uuid4().hex,
        })
        connection.execute(text("""
            INSERT INTO analysis_v1.analysis_run_links
                (definition_id, definition_version, request_id, idempotency_key,
                 as_of, timezone_name, parameters_json, parameter_hash)
            VALUES (:definition_id, 1, :request_id, :idempotency_key,
                    DATE '2026-08-14', 'Asia/Seoul', '{}'::jsonb, :hash)
        """), {
            "definition_id": definition_id, "request_id": request_id,
            "idempotency_key": str(request_id), "hash": "c" * 64,
        })
        connection.execute(text("""
            INSERT INTO query.query_executions
                (query_execution_id, request_id, attempt_no, generation_mode,
                 generated_sql_redacted, sql_hash, ast_validation_json,
                 join_validation_json, permission_validation_json, explain_json,
                 validation_status, trino_query_id, execution_status, row_count,
                 scan_bytes, result_checksum, source_urns_json, source_cutoff_json)
            VALUES (:query_execution_id, :request_id, 1, 'LLM', 'SELECT 1', :hash,
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                    'ALLOWED', :query_id, 'SUCCEEDED', 1, 1, :checksum,
                    '[]'::jsonb, '{}'::jsonb)
        """), {
            "query_execution_id": query_execution_id, "request_id": request_id,
            "hash": "d" * 64, "query_id": query_id, "checksum": "e" * 64,
        })
        connection.execute(text("""
            INSERT INTO artifact.analysis_artifacts
                (artifact_id, request_id, query_execution_id, artifact_type,
                 title, data_snapshot_json, chart_spec_json, narrative_markdown,
                 evidence_json, freshness_status, status, artifact_checksum)
            VALUES (:artifact_id, :request_id, :query_execution_id, 'TABLE',
                    'Replay result',
                    CAST(:snapshot AS jsonb),
                    CAST(:chart AS jsonb), 'Replay result narrative',
                    CAST(:evidence AS jsonb),
                    'FRESH', 'APPROVED', :checksum)
        """), {
            "artifact_id": artifact_id, "request_id": request_id,
            "query_execution_id": query_execution_id, "checksum": "f" * 64,
            "snapshot": '{"columns":["month","value"],"rows":[{"month":"2026-08","value":1}]}',
            "chart": '{"chart_type":"bar","x_field":"month","y_fields":["value"]}',
            "evidence": '{"policy_version":"policy-current","metric_values":[{"label":"Revenue","value":1,"unit":"KRW"}]}',
        })


@async_test
async def test_postgres_report_run_records_new_replay_lineage_and_partial_failure(replay_database):
    engine = create_engine(replay_database)
    definition_id = uuid4()
    source_request_id, replay_request_id = uuid4(), uuid4()
    source_query_execution_id, replay_query_execution_id = uuid4(), uuid4()
    source_artifact_id, replay_artifact_id = uuid4(), uuid4()
    _seed_analysis_evidence(
        engine,
        definition_id=definition_id,
        request_id=source_request_id,
        query_execution_id=source_query_execution_id,
        artifact_id=source_artifact_id,
        query_id="source-query",
    )
    _seed_analysis_evidence(
        engine,
        definition_id=definition_id,
        request_id=replay_request_id,
        query_execution_id=replay_query_execution_id,
        artifact_id=replay_artifact_id,
        query_id="replay-query",
    )

    report_id = uuid4()
    block_success, block_failed = uuid4(), uuid4()
    repository = PostgresReportRepository(replay_database, OWNER)
    await repository.add_draft(ReportDefinitionVersion(
        str(report_id), 1, DefinitionStatus.DRAFT, "Replay Report", (
            ReportBlock(str(block_success), "Success", str(source_artifact_id), 6, "source-query"),
            ReportBlock(str(block_failed), "Failure", str(source_artifact_id), 6, "source-query", x=6),
        ),
    ))
    await repository.approve(str(report_id), 1, AS_OF)
    command = await repository.queue_manual_run(
        str(report_id), 1, AS_OF, "manual-replay-1"
    )
    claim = await repository.claim_manual_run(command.command_id)
    assert claim["claimed"] is True
    assert all(block["analysis_definition_id"] == str(definition_id) for block in claim["blocks"])

    await repository.record_block_run(
        claim["run_id"], str(block_success), status=BlockRunStatus.SUCCESS,
        request_id=str(replay_request_id), artifact_id=str(replay_artifact_id),
        query_id="replay-query", snapshot_checksum="f" * 64,
        policy_version="policy-current",
    )
    await repository.record_block_run(
        claim["run_id"], str(block_failed), status=BlockRunStatus.FAILED,
        failure_code=BlockFailureCode.QUERY_SOURCE_FAILED,
        failure_message="The approved source is unavailable.",
    )
    run = await repository.finish_manual_run(command.command_id)

    assert run.status is RunStatus.PARTIAL
    assert run.blocks[0].artifact_id == str(replay_artifact_id)
    assert run.blocks[0].artifact_id != str(source_artifact_id)
    assert run.blocks[0].request_id == str(replay_request_id)
    assert run.blocks[1].failure_code is BlockFailureCode.QUERY_SOURCE_FAILED
    with pytest.raises(KeyError):
        await PostgresReportRepository(replay_database, uuid4()).get_run(run.run_id)
    await dispose_database()
    engine.dispose()


@async_test
async def test_postgres_aggregate_artifact_survives_save_pdf_and_single_block_replay(replay_database):
    engine = create_engine(replay_database)
    analysis_definition_id = uuid4()
    request_id = uuid4()
    query_execution_id = uuid4()
    artifact_id = uuid4()
    _seed_analysis_evidence(
        engine,
        definition_id=analysis_definition_id,
        request_id=request_id,
        query_execution_id=query_execution_id,
        artifact_id=artifact_id,
        query_id="source-query",
    )

    report_id = uuid4()
    block_id = uuid4()
    repository = PostgresReportRepository(replay_database, OWNER)
    await repository.add_draft(ReportDefinitionVersion(
        str(report_id),
        1,
        DefinitionStatus.DRAFT,
        "Aggregate Artifact Report",
        (
            ReportBlock(
                str(block_id),
                "Analysis Artifact",
                str(artifact_id),
                12,
                "source-query",
                BlockType.ARTIFACT,
                0,
                0,
                12,
                12,
                '{"presentationMode":"standard","visibleViews":["summary","kpi","chart","table"]}',
            ),
        ),
        orientation="landscape",
    ))

    reloaded = await repository.get_version(str(report_id), 1)
    assert len(reloaded.blocks) == 1
    assert reloaded.blocks[0].type is BlockType.ARTIFACT
    assert reloaded.blocks[0].artifact_id == str(artifact_id)

    class FakeHTML:
        def __init__(self, **kwargs):
            self.html = kwargs["string"]

        def write_pdf(self, **kwargs):
            return b"%PDF-1.7\naggregate-artifact"

    with patch.dict(sys.modules, {"weasyprint": SimpleNamespace(HTML=FakeHTML)}):
        approved = await approve_report_document(
            repository,
            str(report_id),
            1,
            AS_OF,
            "landscape",
        )

    assert approved.status is DefinitionStatus.APPROVED
    document = await repository.get_document(str(report_id), 1)
    assert document["pdf_bytes"].startswith(b"%PDF-")
    assert document["artifact_versions"] == [{
        "artifact_id": str(artifact_id),
        "artifact_checksum": "f" * 64,
        "query_id": "source-query",
    }]
    assert "Replay result narrative" in document["html_snapshot"]
    assert "주요 KPI" in document["html_snapshot"]
    assert "<svg" in document["html_snapshot"]
    assert "<table>" in document["html_snapshot"]

    command = await repository.queue_manual_run(
        str(report_id), 1, AS_OF, "aggregate-artifact-replay"
    )
    claim = await repository.claim_manual_run(command.command_id)
    assert len(claim["blocks"]) == 1
    assert claim["blocks"][0]["block_id"] == str(block_id)
    await repository.record_block_run(
        claim["run_id"],
        str(block_id),
        status=BlockRunStatus.SUCCESS,
        request_id=str(request_id),
        artifact_id=str(artifact_id),
        query_id="source-query",
        snapshot_checksum="f" * 64,
        policy_version="policy-current",
    )
    run = await repository.finish_manual_run(command.command_id)
    assert run.status is RunStatus.SUCCESS
    assert len(run.blocks) == 1
    assert run.blocks[0].artifact_id == str(artifact_id)
    await dispose_database()
    engine.dispose()
