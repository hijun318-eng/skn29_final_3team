"""Phase 1 Conversation Safety를 격리 PostgreSQL transaction으로 검증한다."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.adapters.analysis_repository import PostgresAnalysisRepository  # noqa: E402
from app.adapters.analysis_repository_common import _hash  # noqa: E402
from app.adapters.conversation_repository import ConversationRepository  # noqa: E402
from app.authorization import permission_snapshot_id  # noqa: E402
from app.contracts import (  # noqa: E402
    AnalysisData,
    AnalysisResponse,
    AnalysisResult,
    AnalysisStatus,
    ArtifactReference,
    Evidence,
    RequestContext,
    Role,
    TableResult,
    response_meta,
)
from app.services.conversation.reconciler import ConversationReconciler  # noqa: E402


PRODUCT_RELEASE = "ANSWERVICE-PRODUCT-RELEASE-v1:" + "9" * 64
SEMANTIC_RELEASE = "semantic-release:phase1"
OWNER = UUID("10000000-0000-0000-0000-000000000001")


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


def _seed_product_manifest(database_url: str) -> None:
    image_receipts = [{"component": "backend", "digest": "sha256:" + "4" * 64}]
    release_vector = {
        "data_release_id": "data-phase1",
        "semantic_release_id": SEMANTIC_RELEASE,
        "prompt_release_id": "prompt-phase1",
        "policy_release_id": "policy-phase1",
        "runtime_release_id": "runtime-phase1",
    }
    manifest = {
        "schema_version": "ProductReleaseEvidenceManifest.v1",
        "product_release_id": PRODUCT_RELEASE,
        "manifest_sha256": "1" * 64,
        "created_at": "2026-08-22T00:00:00Z",
        "evidence": {
            "source": {
                "commit_sha": "2" * 40,
                "dirty": False,
                "dirty_patch_sha256": None,
            },
            "images": image_receipts,
            "migration": {"revision": "20260822_30", "chain_sha256": "5" * 64},
            "model": {
                "release_id": "MODEL-RELEASE-v1.32.0",
                "manifest_sha256": "6" * 64,
            },
            "catalog": {
                "release_id": "catalog-phase1",
                "manifest_sha256": "7" * 64,
                "projection_sha256": "8" * 64,
            },
            "release_vector": release_vector,
        },
    }
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO governance.product_release_manifests (
                    product_release_id, contract_version, manifest_sha256,
                    manifest_json, source_commit_sha, source_dirty,
                    dirty_patch_sha256, image_digests_json, migration_revision,
                    migration_chain_sha256, model_release_id,
                    model_manifest_sha256, catalog_release_id,
                    catalog_manifest_sha256, catalog_projection_sha256,
                    release_vector_json, created_at
                ) VALUES (
                    :release_id, 'ProductReleaseEvidenceManifest.v1', :manifest_sha,
                    CAST(:manifest AS jsonb), :source_commit, false,
                    NULL, CAST(:images AS jsonb), '20260822_30',
                    :migration_sha, 'MODEL-RELEASE-v1.32.0',
                    :model_sha, 'catalog-phase1', :catalog_sha, :projection_sha,
                    CAST(:release_vector AS jsonb), now()
                )
                """
            ),
            {
                "release_id": PRODUCT_RELEASE,
                "manifest_sha": "1" * 64,
                "manifest": json.dumps(manifest),
                "source_commit": "2" * 40,
                "images": json.dumps(image_receipts),
                "migration_sha": "5" * 64,
                "model_sha": "6" * 64,
                "catalog_sha": "7" * 64,
                "projection_sha": "8" * 64,
                "release_vector": json.dumps(release_vector),
            },
        )
    engine.dispose()


@pytest.fixture(scope="module")
def phase1_database() -> str:
    configured = os.getenv("MIGRATION_TEST_DATABASE_URL")
    if not configured:
        pytest.skip("MIGRATION_TEST_DATABASE_URL is not configured")
    base = make_url(configured)
    database = f"conversation_phase1_{uuid4().hex[:8]}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
    admin.dispose()
    url = base.set(database=database).render_as_string(hide_password=False)
    environment = os.environ.copy()
    environment["APP_DATABASE_URL"] = url
    environment["APP_DB_USER"] = base.username or "postgres"
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
    _seed_product_manifest(url)
    try:
        yield url
    finally:
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


def _runtime(database_url: str):
    async_url = make_url(database_url).set(drivername="postgresql+psycopg")
    engine = create_async_engine(async_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


def _context(conversation_id: UUID, command_id: UUID) -> RequestContext:
    return RequestContext(
        request_id=uuid4(),
        trace_id=f"phase1-{uuid4().hex}",
        conversation_id=conversation_id,
        command_id=command_id,
        user_id=OWNER,
        role=Role.ANALYST,
        as_of=date(2026, 8, 22),
        permission_snapshot_id=permission_snapshot_id(OWNER, Role.ANALYST),
        product_release_id=PRODUCT_RELEASE,
        semantic_release_id=SEMANTIC_RELEASE,
    )


async def _admit_analysis(factory, database_url: str):
    repository = ConversationRepository(factory)
    permission = permission_snapshot_id(OWNER, Role.ANALYST)
    conversation = await repository.create_conversation(
        OWNER,
        "Phase 1 isolated acceptance",
        product_release_id=PRODUCT_RELEASE,
        permission_snapshot_id=permission,
        semantic_release_id=SEMANTIC_RELEASE,
        wall_clock_anchor=date(2026, 8, 22),
    )
    command_id = uuid4()
    acquired, error = await repository.acquire_lease_and_check_cas(
        conversation["conversation_id"],
        None,
        command_id,
        f"phase1-{uuid4()}",
        "a" * 64,
        OWNER,
        PRODUCT_RELEASE,
        permission,
        SEMANTIC_RELEASE,
    )
    assert (acquired, error) == (True, None)
    context = _context(conversation["conversation_id"], command_id)
    analysis = PostgresAnalysisRepository(
        database_url,
        OWNER,
        session_factory=factory,
    )
    await analysis.begin_request("격리 Conversation 원자성 검증", {}, context)
    return repository, analysis, conversation, command_id, context


@async_test
async def test_crash_point_rolls_back_run_turn_head_command_and_lease_together(
    phase1_database: str,
) -> None:
    engine, factory = _runtime(phase1_database)
    try:
        repository, analysis, conversation, command_id, context = await _admit_analysis(
            factory,
            phase1_database,
        )

        async def injected_crash(session) -> None:
            await session.execute(
                text(
                    "UPDATE chat.analysis_requests SET status = 'FAILED', "
                    "error_type = 'UNSUPPORTED', completed_at = now() "
                    "WHERE request_id = :request_id"
                ),
                {"request_id": context.request_id},
            )
            raise RuntimeError("injected crash after run terminal write")

        with pytest.raises(RuntimeError, match="injected crash"):
            await repository.commit_turn(
                conversation["conversation_id"],
                command_id,
                uuid4(),
                0,
                "격리 Conversation 원자성 검증",
                "ANALYSIS",
                [],
                context.request_id,
                None,
                None,
                None,
                {},
                PRODUCT_RELEASE,
                context.permission_snapshot_id,
                SEMANTIC_RELEASE,
                terminal_writer=injected_crash,
            )

        async with factory() as session:
            state = (
                await session.execute(
                    text(
                        """
                        SELECT r.status AS run_status, c.head_turn_id,
                               c.active_command_id, command.status AS command_status,
                               (SELECT count(*) FROM chat.turns
                                WHERE conversation_id = c.conversation_id) AS turn_count
                        FROM chat.analysis_requests r
                        JOIN chat.conversations c ON c.conversation_id = r.conversation_id
                        JOIN chat.turn_commands command ON command.command_id = r.command_id
                        WHERE r.request_id = :request_id
                        """
                    ),
                    {"request_id": context.request_id},
                )
            ).mappings().one()
        assert state["run_status"] == "RECEIVED"
        assert state["head_turn_id"] is None
        assert state["active_command_id"] == command_id
        assert state["command_status"] == "RUNNING"
        assert state["turn_count"] == 0

        async def fail_terminal(session) -> None:
            await analysis.fail_run_in_session(session, context.request_id, "UNSUPPORTED")

        await repository.commit_failed_turn(
            conversation["conversation_id"],
            command_id,
            uuid4(),
            0,
            "격리 Conversation 원자성 검증",
            {"code": "INJECTED_FAILURE", "retryable": True},
            request_id=context.request_id,
            terminal_writer=fail_terminal,
        )
    finally:
        await engine.dispose()


@async_test
async def test_success_commit_has_complete_turn_run_artifact_release_lineage(
    phase1_database: str,
) -> None:
    engine, factory = _runtime(phase1_database)
    try:
        repository, analysis, conversation, command_id, context = await _admit_analysis(
            factory,
            phase1_database,
        )
        artifact_id = uuid4()
        response = AnalysisResponse(
            data=AnalysisData(
                status=AnalysisStatus.SUCCEEDED,
                transitions=(
                    AnalysisStatus.RECEIVED,
                    AnalysisStatus.ROUTED,
                    AnalysisStatus.SUCCEEDED,
                ),
                result=AnalysisResult(
                    summary="격리 결과 1건",
                    table=TableResult(columns=("value",), rows=({"value": 1},)),
                    evidence=Evidence(
                        as_of=context.as_of,
                        query_id="phase1-query-success",
                        product_release_id=PRODUCT_RELEASE,
                        context_release=SEMANTIC_RELEASE,
                        policy_version="policy-v1",
                    ),
                ),
                artifact=ArtifactReference(
                    artifact_id=artifact_id,
                    query_id="phase1-query-success",
                    context_hash="b" * 64,
                ),
            ),
            meta=response_meta(context),
        )
        execution = {
            "plan": {
                "sql": "SELECT :value AS value",
                "executable_sql": "SELECT 1 AS value",
                "model_version": "MODEL-v1",
            },
            "query": {
                "query_id": "phase1-query-success",
                "rows": [{"value": 1}],
                "scan_bytes": 1,
            },
            "package": SimpleNamespace(
                assets=(SimpleNamespace(urn="urn:li:dataset:(phase1,isolated,PROD)"),)
            ),
        }
        await analysis.record_query_lifecycle(
            context.request_id,
            {
                "event_type": "SUBMITTED",
                "query_id": "phase1-query-success",
                "cancel_uri": (
                    "https://trino:8443/v1/statement/phase1-query-success/1"
                ),
                "sql_hash": _hash("SELECT 1 AS value"),
                "status": "RUNNING",
            },
        )
        await analysis.record_query_lifecycle(
            context.request_id,
            {
                "event_type": "HEARTBEAT",
                "query_id": "phase1-query-success",
                "cancel_uri": (
                    "https://trino:8443/v1/statement/phase1-query-success/2"
                ),
                "status": "RUNNING",
            },
        )
        await analysis.record_query_lifecycle(
            context.request_id,
            {
                "event_type": "TERMINAL",
                "query_id": "phase1-query-success",
                "sql_hash": _hash("SELECT 1 AS value"),
                "status": "SUCCEEDED",
                "row_count": 1,
                "scan_bytes": 1,
            },
        )

        async def finish_terminal(session) -> None:
            await analysis.finish_run_in_session(
                session,
                context.request_id,
                response,
                execution,
            )

        turn_id = uuid4()
        default_view_id = uuid4()
        await repository.commit_turn(
            conversation["conversation_id"],
            command_id,
            turn_id,
            0,
            "격리 성공 lineage",
            "ANALYSIS",
            [],
            context.request_id,
            artifact_id,
            default_view_id,
            None,
            {},
            PRODUCT_RELEASE,
            context.permission_snapshot_id,
            SEMANTIC_RELEASE,
            terminal_writer=finish_terminal,
            view_spec={
                "view_type": "TABLE",
                "spec_json": {
                    "chart_type": "table",
                    "source_artifact_id": str(artifact_id),
                    "columns": ["value"],
                },
            },
        )

        presentation_command_id = uuid4()
        acquired, error = await repository.acquire_lease_and_check_cas(
            conversation["conversation_id"],
            turn_id,
            presentation_command_id,
            f"phase1-view-{uuid4()}",
            "d" * 64,
            OWNER,
            PRODUCT_RELEASE,
            context.permission_snapshot_id,
            SEMANTIC_RELEASE,
        )
        assert (acquired, error) == (True, None)
        presentation_turn_id = uuid4()
        bar_view_id = uuid4()
        await repository.commit_turn(
            conversation["conversation_id"],
            presentation_command_id,
            presentation_turn_id,
            1,
            "막대 그래프로 보여줘",
            "PRESENTATION",
            [str(turn_id)],
            None,
            artifact_id,
            bar_view_id,
            None,
            {},
            PRODUCT_RELEASE,
            context.permission_snapshot_id,
            SEMANTIC_RELEASE,
            view_spec={
                "view_type": "BAR",
                "spec_json": {
                    "chart_type": "bar",
                    "source_artifact_id": str(artifact_id),
                    "x_field": "value",
                    "y_fields": ["value"],
                },
            },
        )

        async with factory() as session:
            lineage = (
                await session.execute(
                    text(
                        """
                        SELECT t.request_id, t.artifact_id,
                               t.product_release_id AS turn_release,
                               r.status AS run_status,
                               r.product_release_id AS run_release,
                               a.product_release_id AS artifact_release,
                               a.permission_snapshot_id AS artifact_permission,
                               q.execution_status AS query_status,
                               q.trino_cancel_uri,
                               c.head_turn_id, command.status AS command_status,
                               c.data_focus_turn_id, c.data_focus_artifact_id,
                               c.view_focus_turn_id, c.view_focus_spec_id,
                               v.spec_sha256
                        FROM chat.turns t
                        JOIN chat.analysis_requests r ON r.request_id = t.request_id
                        JOIN artifact.analysis_artifacts a ON a.artifact_id = t.artifact_id
                        JOIN query.query_executions q
                          ON q.query_execution_id = a.query_execution_id
                        JOIN chat.conversations c ON c.conversation_id = t.conversation_id
                        JOIN chat.turn_commands command ON command.turn_id = t.turn_id
                        JOIN artifact.view_specs v ON v.view_spec_id = t.view_spec_id
                        WHERE t.turn_id = :turn_id
                        """
                    ),
                    {"turn_id": turn_id},
                )
            ).mappings().one()
            binding_kinds = set(
                (
                    await session.execute(
                        text(
                            "SELECT object_kind FROM governance.product_release_bindings "
                            "WHERE object_id IN (:conversation, :turn, :run, :artifact, "
                            ":default_view, :bar_view)"
                        ),
                        {
                            "conversation": str(conversation["conversation_id"]),
                            "turn": str(turn_id),
                            "run": str(context.request_id),
                            "artifact": str(artifact_id),
                            "default_view": str(default_view_id),
                            "bar_view": str(bar_view_id),
                        },
                    )
                ).scalars().all()
            )
            presentation = (
                await session.execute(
                    text(
                        "SELECT source_turn_ids, artifact_id, view_spec_id, "
                        "terminal_status FROM chat.turns WHERE turn_id = :turn_id"
                    ),
                    {"turn_id": presentation_turn_id},
                )
            ).mappings().one()
        assert lineage["request_id"] == context.request_id
        assert lineage["artifact_id"] == artifact_id
        assert lineage["turn_release"] == PRODUCT_RELEASE
        assert lineage["run_status"] == "SUCCEEDED"
        assert lineage["run_release"] == PRODUCT_RELEASE
        assert lineage["artifact_release"] == PRODUCT_RELEASE
        assert lineage["artifact_permission"] == context.permission_snapshot_id
        assert lineage["query_status"] == "SUCCEEDED"
        assert lineage["trino_cancel_uri"] is None
        assert lineage["head_turn_id"] == presentation_turn_id
        assert lineage["command_status"] == "COMPLETED"
        assert lineage["data_focus_turn_id"] == turn_id
        assert lineage["data_focus_artifact_id"] == artifact_id
        assert lineage["view_focus_turn_id"] == presentation_turn_id
        assert lineage["view_focus_spec_id"] == bar_view_id
        assert len(lineage["spec_sha256"]) == 64
        assert binding_kinds == {"CONVERSATION", "TURN", "RUN", "ARTIFACT", "VIEW"}
        assert presentation["source_turn_ids"] == [str(turn_id)]
        assert presentation["artifact_id"] == artifact_id
        assert presentation["view_spec_id"] == bar_view_id
        assert presentation["terminal_status"] == "SUCCEEDED"
    finally:
        await engine.dispose()


class _CancelPlatform:
    def __init__(self, status: str) -> None:
        self.status = status
        self.cancelled: list[tuple[str, str]] = []

    async def cancel_query_at(
        self,
        query_id: str,
        cancel_uri: str,
    ) -> dict[str, str]:
        self.cancelled.append((query_id, cancel_uri))
        return {"status": self.status}


@async_test
async def test_reconciler_fails_closed_then_terminalizes_stale_run_lease_and_query(
    phase1_database: str,
) -> None:
    engine, factory = _runtime(phase1_database)
    try:
        repository, analysis, conversation, command_id, context = await _admit_analysis(
            factory,
            phase1_database,
        )
        cancel_uri = "https://trino:8443/v1/statement/phase1-orphan-query/1"
        await analysis.record_query_lifecycle(
            context.request_id,
            {
                "event_type": "SUBMITTED",
                "query_id": "phase1-orphan-query",
                "cancel_uri": cancel_uri,
                "sql_hash": "c" * 64,
                "status": "RUNNING",
            },
        )
        with pytest.raises(ValueError, match="다른 query submission"):
            await analysis.record_query_lifecycle(
                context.request_id,
                {
                    "event_type": "SUBMITTED",
                    "query_id": "phase1-duplicate-query",
                    "cancel_uri": (
                        "https://trino:8443/v1/statement/phase1-duplicate-query/1"
                    ),
                    "sql_hash": "d" * 64,
                    "status": "RUNNING",
                },
            )
        async with factory.begin() as session:
            await session.execute(
                text(
                    "UPDATE chat.conversations "
                    "SET lease_expires_at = now() - interval '1 minute' "
                    "WHERE conversation_id = :conversation_id"
                ),
                {"conversation_id": conversation["conversation_id"]},
            )

        future = datetime.now(timezone.utc) + timedelta(seconds=10)
        nonterminal_cancel = _CancelPlatform("RUNNING")
        reconciler = ConversationReconciler(
            repository,
            nonterminal_cancel,
            stale_seconds=1,
            batch_limit=10,
        )
        with pytest.raises(RuntimeError, match="terminal 상태가 아닙니다"):
            await reconciler.run_once(now=future)

        async with factory() as session:
            unchanged = (
                await session.execute(
                    text(
                        """
                        SELECT r.status AS run_status, q.execution_status,
                               command.status AS command_status,
                               c.active_command_id
                        FROM chat.analysis_requests r
                        JOIN query.query_executions q ON q.request_id = r.request_id
                        JOIN chat.turn_commands command ON command.command_id = r.command_id
                        JOIN chat.conversations c ON c.conversation_id = r.conversation_id
                        WHERE r.request_id = :request_id
                        """
                    ),
                    {"request_id": context.request_id},
                )
            ).mappings().one()
        assert unchanged == {
            "run_status": "RECEIVED",
            "execution_status": "RUNNING",
            "command_status": "RUNNING",
            "active_command_id": command_id,
        }

        terminal_cancel = _CancelPlatform("CANCELLED")
        reconciler = ConversationReconciler(
            repository,
            terminal_cancel,
            stale_seconds=1,
            batch_limit=10,
        )
        counts = await reconciler.run_once(now=future)
        assert counts == {"commands": 1, "runs": 1, "queries": 1, "turns": 1}
        assert terminal_cancel.cancelled == [("phase1-orphan-query", cancel_uri)]
        assert await reconciler.run_once(now=future) == {
            "commands": 0,
            "runs": 0,
            "queries": 0,
            "turns": 0,
        }

        async with factory() as session:
            terminal = (
                await session.execute(
                    text(
                        """
                        SELECT r.status AS run_status, r.error_type,
                               q.execution_status, command.status AS command_status,
                               c.active_command_id, c.lease_expires_at,
                               t.request_id AS turn_request_id,
                               t.product_release_id AS turn_release
                        FROM chat.analysis_requests r
                        JOIN query.query_executions q ON q.request_id = r.request_id
                        JOIN chat.turn_commands command ON command.command_id = r.command_id
                        JOIN chat.conversations c ON c.conversation_id = r.conversation_id
                        JOIN chat.turns t ON t.turn_id = command.turn_id
                        WHERE r.request_id = :request_id
                        """
                    ),
                    {"request_id": context.request_id},
                )
            ).mappings().one()
            stale_nonterminal = (
                await session.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM chat.turn_commands WHERE status = 'RUNNING') +
                          (SELECT count(*) FROM chat.analysis_requests
                           WHERE status IN ('RECEIVED','ROUTED','RUNNING')) +
                          (SELECT count(*) FROM query.query_executions
                           WHERE execution_status = 'RUNNING')
                        """
                    )
                )
            ).scalar_one()
        assert terminal["run_status"] == "FAILED"
        assert terminal["error_type"] == "RECOVERY"
        assert terminal["execution_status"] == "CANCELLED"
        assert terminal["command_status"] == "FAILED"
        assert terminal["active_command_id"] is None
        assert terminal["lease_expires_at"] is None
        assert terminal["turn_request_id"] == context.request_id
        assert terminal["turn_release"] == PRODUCT_RELEASE
        assert stale_nonterminal == 0
    finally:
        await engine.dispose()
