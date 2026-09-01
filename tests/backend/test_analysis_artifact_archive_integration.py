"""격리 PostgreSQL에서 Analysis Artifact 보관의 소유권·동시성·참조 보존을 검증한다."""

from __future__ import annotations

import asyncio
from functools import wraps
import os
from pathlib import Path
from sys import path
import sys
from types import MethodType
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters.analysis_repository import PostgresAnalysisRepository  # noqa: E402
# 보고서 service package를 먼저 조립해 repository↔scheduler import cycle을 피한다.
from app.services.report.execution import ReportExecutionService  # noqa: E402,F401
from app.adapters.report_repository import PostgresReportRepository  # noqa: E402
from app.database import dispose_database  # noqa: E402
from src.report.domain import (  # noqa: E402
    DefinitionStatus,
    ReportBlock,
    ReportDefinitionVersion,
)


DATABASE_URL = os.getenv("ANALYSIS_ARCHIVE_DATABASE_URL")
DISPOSABLE = os.getenv("ANALYSIS_ARCHIVE_DATABASE_DISPOSABLE") == "1"
pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not DISPOSABLE,
    reason="disposable Analysis Artifact archive PostgreSQL is required",
)


def async_test(function):
    """플러그인 없이 플랫폼에 맞는 event loop로 async integration을 실행한다."""

    @wraps(function)
    def run(*args, **kwargs):
        if sys.platform == "win32":
            loop = asyncio.SelectorEventLoop()
            try:
                return loop.run_until_complete(function(*args, **kwargs))
            finally:
                loop.run_until_complete(dispose_database())
                loop.close()

        async def invoke():
            try:
                return await function(*args, **kwargs)
            finally:
                await dispose_database()

        return asyncio.run(invoke())

    return run


def _seed_artifact(database_url: str, owner_id):
    definition_id = uuid4()
    request_id = uuid4()
    query_execution_id = uuid4()
    artifact_id = uuid4()
    query_id = f"artifact-archive-{uuid4().hex}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO analysis_v1.analysis_definitions (
                    definition_id, version, owner_id, title, question_text_redacted,
                    parameters_json, parameter_hash, semantic_request_json,
                    parameter_schema_json, is_saved
                ) VALUES (
                    :definition_id, 1, :owner_id, 'Archive source', 'Archive source',
                    '{}'::jsonb, :parameter_hash, '{}'::jsonb, '{}'::jsonb, false
                )
                """
            ),
            {
                "definition_id": definition_id,
                "owner_id": owner_id,
                "parameter_hash": "a" * 64,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO chat.analysis_requests (
                    request_id, request_type, user_id, user_role,
                    question_text_redacted, question_hash, ambiguity_status,
                    sql_policy_version, status, trace_id, started_at, completed_at
                ) VALUES (
                    :request_id, 'CHAT', :owner_id, 'analyst', 'Archive source',
                    :question_hash, 'CLEAR', 'policy-current', 'SUCCEEDED',
                    :trace_id, now(), now()
                )
                """
            ),
            {
                "request_id": request_id,
                "owner_id": owner_id,
                "question_hash": "b" * 64,
                "trace_id": uuid4().hex,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO analysis_v1.analysis_run_links (
                    definition_id, definition_version, request_id, idempotency_key,
                    as_of, timezone_name, parameters_json, parameter_hash
                ) VALUES (
                    :definition_id, 1, :request_id, :idempotency_key,
                    DATE '2026-08-31', 'Asia/Seoul', '{}'::jsonb, :parameter_hash
                )
                """
            ),
            {
                "definition_id": definition_id,
                "request_id": request_id,
                "idempotency_key": str(request_id),
                "parameter_hash": "c" * 64,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO query.query_executions (
                    query_execution_id, request_id, attempt_no, generation_mode,
                    generated_sql_redacted, sql_hash, ast_validation_json,
                    join_validation_json, permission_validation_json, explain_json,
                    validation_status, trino_query_id, execution_status, row_count,
                    scan_bytes, result_checksum, source_urns_json, source_cutoff_json
                ) VALUES (
                    :query_execution_id, :request_id, 1, 'LLM', 'SELECT 1',
                    :sql_hash, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                    'ALLOWED', :query_id, 'SUCCEEDED', 1, 1,
                    :result_checksum, '[]'::jsonb, '{}'::jsonb
                )
                """
            ),
            {
                "query_execution_id": query_execution_id,
                "request_id": request_id,
                "sql_hash": "d" * 64,
                "query_id": query_id,
                "result_checksum": "e" * 64,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO artifact.analysis_artifacts (
                    artifact_id, request_id, query_execution_id, artifact_type,
                    title, data_snapshot_json, chart_spec_json, narrative_markdown,
                    evidence_json, freshness_status, status, artifact_checksum
                ) VALUES (
                    :artifact_id, :request_id, :query_execution_id, 'TABLE',
                    'Archive result',
                    CAST(:data_snapshot_json AS jsonb),
                    '{}'::jsonb, 'Archive result', '{}'::jsonb,
                    'FRESH', 'APPROVED', :artifact_checksum
                )
                """
            ),
            {
                "artifact_id": artifact_id,
                "request_id": request_id,
                "query_execution_id": query_execution_id,
                "data_snapshot_json": (
                    '{"columns":["value"],"rows":[{"value":1}]}'
                ),
                "artifact_checksum": "f" * 64,
            },
        )
    engine.dispose()
    return definition_id, request_id, artifact_id, query_id


@async_test
async def test_archive_restore_is_owner_scoped_idempotent_and_audited_once() -> None:
    assert DATABASE_URL is not None
    owner_id = uuid4()
    _definition_id, _request_id, artifact_id, _query_id = _seed_artifact(
        DATABASE_URL, owner_id
    )
    repository = PostgresAnalysisRepository(DATABASE_URL, owner_id)

    archived = await asyncio.gather(
        repository.archive_artifact(
            artifact_id, actor_role="analyst", trace_id="archive-first"
        ),
        repository.archive_artifact(
            artifact_id, actor_role="analyst", trace_id="archive-second"
        ),
    )
    assert archived[0] == archived[1]
    assert archived[0].archived is True
    assert await repository.list_runs(approved_only=True) == []
    assert len(await repository.list_runs(approved_only=True, archived=True)) == 1

    outsider = PostgresAnalysisRepository(DATABASE_URL, uuid4())
    with pytest.raises(KeyError):
        await outsider.archive_artifact(
            artifact_id, actor_role="platform_admin", trace_id="hidden-admin"
        )

    restored = await asyncio.gather(
        repository.restore_artifact(
            artifact_id, actor_role="analyst", trace_id="restore-first"
        ),
        repository.restore_artifact(
            artifact_id, actor_role="analyst", trace_id="restore-second"
        ),
    )
    assert restored[0] == restored[1]
    assert restored[0].archived is False
    assert len(await repository.list_runs(approved_only=True)) == 1

    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        actions = connection.execute(
            text(
                "SELECT action_code, count(*) FROM governance.audit_events "
                "WHERE object_type = 'ANALYSIS_ARTIFACT' AND object_id = :object_id "
                "GROUP BY action_code ORDER BY action_code"
            ),
            {"object_id": str(artifact_id)},
        ).all()
        source_status = connection.execute(
            text(
                "SELECT status FROM artifact.analysis_artifacts "
                "WHERE artifact_id = :artifact_id"
            ),
            {"artifact_id": artifact_id},
        ).scalar_one()
    engine.dispose()
    assert [tuple(row) for row in actions] == [
        ("ANALYSIS_ARTIFACT_ARCHIVED", 1),
        ("ANALYSIS_ARTIFACT_RESTORED", 1),
    ]
    assert source_status == "APPROVED"


@async_test
async def test_archive_preserves_existing_report_reference_and_blocks_new_bindings() -> None:
    assert DATABASE_URL is not None
    owner_id = uuid4()
    _definition_id, _request_id, artifact_id, query_id = _seed_artifact(
        DATABASE_URL, owner_id
    )
    analysis_repository = PostgresAnalysisRepository(DATABASE_URL, owner_id)
    report_repository = PostgresReportRepository(DATABASE_URL, owner_id)
    report_id = uuid4()
    await report_repository.add_draft(
        ReportDefinitionVersion(
            str(report_id),
            1,
            DefinitionStatus.DRAFT,
            "Existing Artifact report",
            (
                ReportBlock(
                    str(uuid4()),
                    "Existing Artifact",
                    str(artifact_id),
                    12,
                    query_id,
                ),
            ),
        )
    )
    assistant_request_id = uuid4()
    await report_repository.start_assistant_request(
        str(assistant_request_id),
        str(artifact_id),
        "1" * 64,
        "report-assistant",
        "v1",
        "2" * 64,
    )
    with pytest.raises(ValueError, match="ARTIFACT_ARCHIVE_IN_PROGRESS"):
        await analysis_repository.archive_artifact(
            artifact_id, actor_role="analyst", trace_id="active-assistant"
        )

    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE report_v1.report_assistant_requests "
                    "SET status = 'success', "
                    "definition_id = :definition_id, definition_version = 1, "
                    "output_hash = :output_hash, completed_at = now() "
                "WHERE assistant_request_id = :request_id"
            ),
                {
                    "request_id": assistant_request_id,
                    "definition_id": report_id,
                    "output_hash": "7" * 64,
                },
        )
    engine.dispose()

    await analysis_repository.archive_artifact(
        artifact_id, actor_role="analyst", trace_id="completed-assistant"
    )
    preserved = await report_repository.get_report_artifact(
        str(report_id), 1, str(artifact_id)
    )
    assert preserved["artifact_id"] == artifact_id
    with pytest.raises(KeyError):
        await report_repository.get_transfer_artifact(str(artifact_id))
    with pytest.raises(KeyError):
        await report_repository.add_draft(
            ReportDefinitionVersion(
                str(uuid4()),
                1,
                DefinitionStatus.DRAFT,
                "Blocked archived Artifact report",
                (
                    ReportBlock(
                        str(uuid4()),
                        "Archived Artifact",
                        str(artifact_id),
                        12,
                        query_id,
                    ),
                ),
            )
        )
    with pytest.raises(KeyError):
        await report_repository.start_assistant_request(
            str(uuid4()),
            str(artifact_id),
            "3" * 64,
            "report-assistant",
            "v1",
            "4" * 64,
        )


@async_test
async def test_archive_races_with_new_assistant_binding_without_partial_success() -> None:
    assert DATABASE_URL is not None
    owner_id = uuid4()
    _definition_id, _request_id, artifact_id, _query_id = _seed_artifact(
        DATABASE_URL, owner_id
    )
    analysis_repository = PostgresAnalysisRepository(DATABASE_URL, owner_id)
    report_repository = PostgresReportRepository(DATABASE_URL, owner_id)

    archive_result, assistant_result = await asyncio.gather(
        analysis_repository.archive_artifact(
            artifact_id, actor_role="analyst", trace_id="archive-binding-race"
        ),
        report_repository.start_assistant_request(
            str(uuid4()),
            str(artifact_id),
            "5" * 64,
            "report-assistant",
            "v1",
            "6" * 64,
        ),
        return_exceptions=True,
    )

    if isinstance(archive_result, Exception):
        assert isinstance(archive_result, ValueError)
        assert str(archive_result) == "ARTIFACT_ARCHIVE_IN_PROGRESS"
        assert assistant_result is None
    else:
        assert archive_result.archived is True
        assert isinstance(assistant_result, KeyError)


def _draft_for_artifact(artifact_id, query_id):
    report_id = uuid4()
    return report_id, ReportDefinitionVersion(
        str(report_id),
        1,
        DefinitionStatus.DRAFT,
        "Concurrent Artifact report",
        (
            ReportBlock(
                str(uuid4()),
                "Concurrent Artifact",
                str(artifact_id),
                12,
                query_id,
            ),
        ),
    )


@async_test
async def test_archive_first_serializes_new_report_binding_to_all_or_nothing() -> None:
    """보관 row lock이 먼저면 대기하던 신규 report 전체 transaction이 rollback된다."""

    assert DATABASE_URL is not None
    owner_id = uuid4()
    _definition_id, _request_id, artifact_id, query_id = _seed_artifact(
        DATABASE_URL, owner_id
    )
    analysis_repository = PostgresAnalysisRepository(DATABASE_URL, owner_id)
    report_repository = PostgresReportRepository(DATABASE_URL, owner_id)
    report_id, draft = _draft_for_artifact(artifact_id, query_id)
    archive_has_lock = asyncio.Event()
    release_archive = asyncio.Event()
    original_lock = analysis_repository._lock_owned_artifact

    async def lock_then_pause(self, session, target_artifact_id):
        row = await original_lock(session, target_artifact_id)
        archive_has_lock.set()
        await release_archive.wait()
        return row

    analysis_repository._lock_owned_artifact = MethodType(
        lock_then_pause, analysis_repository
    )
    archive_task = asyncio.create_task(
        analysis_repository.archive_artifact(
            artifact_id, actor_role="analyst", trace_id="archive-first-report-race"
        )
    )
    await archive_has_lock.wait()
    report_task = asyncio.create_task(report_repository.add_draft(draft))
    await asyncio.sleep(0)
    release_archive.set()

    archived, report_result = await asyncio.gather(
        archive_task, report_task, return_exceptions=True
    )
    assert archived.archived is True
    assert isinstance(report_result, KeyError)
    with pytest.raises(KeyError):
        await report_repository.get_version(str(report_id), 1)


@async_test
async def test_report_binding_first_remains_valid_when_archive_follows() -> None:
    """신규 report의 share lock이 먼저면 저장 후 보관되며 기존 참조는 계속 읽힌다."""

    assert DATABASE_URL is not None
    owner_id = uuid4()
    _definition_id, _request_id, artifact_id, query_id = _seed_artifact(
        DATABASE_URL, owner_id
    )
    analysis_repository = PostgresAnalysisRepository(DATABASE_URL, owner_id)
    report_repository = PostgresReportRepository(DATABASE_URL, owner_id)
    report_id, draft = _draft_for_artifact(artifact_id, query_id)
    report_has_lock = asyncio.Event()
    release_report = asyncio.Event()
    original_require = report_repository._require_owned_artifact

    async def require_then_pause(self, session, target_artifact_id, target_query_id):
        lineage = await original_require(session, target_artifact_id, target_query_id)
        report_has_lock.set()
        await release_report.wait()
        return lineage

    report_repository._require_owned_artifact = MethodType(
        require_then_pause, report_repository
    )
    report_task = asyncio.create_task(report_repository.add_draft(draft))
    await report_has_lock.wait()
    archive_task = asyncio.create_task(
        analysis_repository.archive_artifact(
            artifact_id, actor_role="analyst", trace_id="report-first-archive-race"
        )
    )
    await asyncio.sleep(0)
    release_report.set()

    report_result, archived = await asyncio.gather(report_task, archive_task)
    assert report_result.definition_id == str(report_id)
    assert archived.archived is True
    preserved = await report_repository.get_report_artifact(
        str(report_id), 1, str(artifact_id)
    )
    assert preserved["artifact_id"] == artifact_id
