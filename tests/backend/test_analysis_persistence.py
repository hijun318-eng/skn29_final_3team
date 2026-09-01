from __future__ import annotations

import asyncio
import copy
import json
from datetime import date, datetime, timezone
from functools import wraps
from pathlib import Path
from sys import path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.analysis_contracts import (  # noqa: E402
    CreateAnalysisDefinitionRequest,
    ReplayAnalysisRequest,
)
from app.api import router as analysis_api  # noqa: E402
from app.adapters.analysis_repository import (  # noqa: E402
    AnalysisRepositoryUnavailable,
    PostgresAnalysisRepository,
)
from app.context import ContextValidationError  # noqa: E402
from app.contracts import AnalysisRequest, ErrorCode, RequestContext  # noqa: E402
from app.controllers.analysis_controller import AnalysisController  # noqa: E402
from app.services.analysis import AnalysisService  # noqa: E402
from app.services.routing_service import RoutingService  # noqa: E402
from app.services.analysis.semantic_request import (  # noqa: E402
    parse_approved_semantic_request_snapshot,
)
from src.analysis.domain import AnalysisArtifactLifecycle  # noqa: E402
from tests.support.analysis_runtime_fixture import (  # noqa: E402
    AnalysisRuntimeMetadata,
    AnalysisRuntimeDataPlatformFake,
    MetadataDrivenAnalysisModel,
    default_analysis_runtime_metadata,
)
from tests.support.semantic_snapshot_fixture import (  # noqa: E402
    approved_semantic_snapshot_fixture,
)


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


@pytest.fixture(autouse=True)
def isolated_test_controller():
    controller = AnalysisController(
        AnalysisService(
            AnalysisRuntimeDataPlatformFake(),
            MetadataDrivenAnalysisModel(),
        ),
        RoutingService(),
    )
    async def active_context_release() -> str:
        return "fixture-context-v1"

    async def active_product_release_receipt() -> tuple[str, str]:
        return "fixture-product-release", "fixture-context-v1"

    with (
        patch.object(analysis_api, "_controller", return_value=controller),
        patch.object(
            analysis_api,
            "_active_analytics_context_release",
            new=active_context_release,
        ),
        patch.object(
            analysis_api,
            "_active_product_release_receipt",
            new=active_product_release_receipt,
        ),
    ):
        yield


class FakeAnalysisRepository:
    def __init__(self, owner_id: UUID) -> None:
        self.owner_id = owner_id
        self.definition_id = uuid4()
        self.request_id: UUID | None = None
        self.run_context: RequestContext | None = None
        self.finished = None
        self.context_receipts = []
        self.list_options = None
        self.lifecycle_calls = []
        self.definition = {
            "contract_version": "ANALYSIS-PERSISTENCE-v1.0.0-DRAFT",
            "definition_id": self.definition_id,
            "version": 1,
            "status": "approved",
            "title": "객실 운영",
            "question": "합성 객실 운영 현황을 알려줘",
            "parameter_types": {"scenario": "string"},
            "semantic_request": {
                "question": "합성 객실 운영 현황을 알려줘",
                "context_release": "fixture-context-v1",
            },
            "parameter_schema": {"scenario": "string"},
            "approved_semantic_snapshot": (
                approved_semantic_snapshot_fixture().model_dump(mode="json")
            ),
            "created_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
        }
        self.question = "합성 객실 운영 현황을 알려줘"
        self.parameters = {"scenario": "success"}

    async def begin_request(self, question, parameters, request_context):
        self.question = question
        self.parameters = parameters
        self.request_id = request_context.request_id
        self.run_context = request_context
        return self.request_id

    async def persist_context_receipt(self, request_context, package):
        self.context_receipts.append((request_context, package))
        return uuid4()

    async def create_definition_from_run(self, source_request_id, title):
        self.definition.update(title=title)
        return self.definition

    async def list_definitions(self):
        return [self.definition]

    async def get_definition(self, definition_id, *, replay=False):
        if definition_id != self.definition_id:
            raise KeyError("Analysis Definition을 찾을 수 없습니다.")
        if replay:
            return {**self.definition, "question": self.question, "parameters": self.parameters}
        return self.definition

    async def begin_run(
        self, definition, context, as_of, idempotency_key, parameters=None
    ):
        if self.request_id is not None:
            return self.request_id, False
        self.request_id = context.request_id
        self.run_context = context
        self.as_of = as_of
        self.idempotency_key = idempotency_key
        self.parameters = parameters if parameters is not None else definition["parameters"]
        return self.request_id, True

    async def finish_run(self, request_id, response, execution):
        self.finished = (response, execution)

    async def fail_run(self, request_id, error_type="UNSUPPORTED"):
        self.finished = error_type

    async def get_run(self, request_id):
        status = "RECEIVED" if self.finished is None else self.finished[0].data.status.value
        response = self.finished[0] if isinstance(self.finished, tuple) else None
        return {
            "request_id": request_id,
            "definition_id": self.definition_id,
            "definition_version": 1,
            "status": status,
            "as_of": self.as_of,
            "timezone": "Asia/Seoul",
            "trace_id": "analysis-persistence-trace",
            "query_id": response.data.artifact.query_id if response and response.data.artifact else None,
            "artifact_id": response.data.artifact.artifact_id if response and response.data.artifact else None,
            "error_type": None,
            "started_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
            "completed_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
            "question": self.question,
            "period_start": None,
            "period_end_exclusive": None,
        }

    async def list_runs(self, *, limit=100, approved_only=False, archived=False):
        self.list_options = {
            "limit": limit,
            "approved_only": approved_only,
            "archived": archived,
        }
        return [] if self.request_id is None else [await self.get_run(self.request_id)]

    async def get_run_artifact(self, request_id):
        response = self.finished[0] if isinstance(self.finished, tuple) else None
        if response is None or response.data.result is None or response.data.artifact is None:
            raise KeyError("승인된 Analysis Artifact를 찾을 수 없습니다.")
        return {
            "request_id": request_id,
            "trace_id": "analysis-persistence-trace",
            "status": response.data.status.value,
            "question": self.question,
            "summary": response.data.result.summary,
            "metrics": response.data.result.evidence.metric_values,
            "table": response.data.result.table,
            "chart": response.data.result.chart,
            "evidence": response.data.result.evidence,
            "artifact_id": response.data.artifact.artifact_id,
            "query_id": response.data.artifact.query_id,
            "artifact_checksum": "a" * 64,
        }

    async def archive_artifact(self, artifact_id, *, actor_role, trace_id=None):
        self.lifecycle_calls.append(("archive", artifact_id, actor_role, trace_id))
        return AnalysisArtifactLifecycle(
            str(artifact_id),
            datetime(2026, 8, 31, tzinfo=timezone.utc),
            str(self.owner_id),
        )

    async def restore_artifact(self, artifact_id, *, actor_role, trace_id=None):
        self.lifecycle_calls.append(("restore", artifact_id, actor_role, trace_id))
        return AnalysisArtifactLifecycle(str(artifact_id))


def context(owner_id: UUID | None = None) -> RequestContext:
    return RequestContext(
        request_id=uuid4(),
        trace_id="analysis-persistence-trace",
        user_id=owner_id or uuid4(),
        # The runtime contract excludes the as_of business date. Keep at least
        # one completed day in the fixture's generated month-to-date interval.
        as_of=date(2026, 8, 2),
    )


def replay_controller(
    model: MetadataDrivenAnalysisModel | None = None,
) -> AnalysisController:
    """compiler-only replay가 가능한 단일 serving view runtime fixture를 만든다."""

    current = default_analysis_runtime_metadata()
    assets = copy.deepcopy(current.assets)
    asset = assets[0]
    asset["fqn"] = "serving.semantic.measure_events"
    asset["query_policy"]["allowed_catalogs"] = ["serving"]
    asset["metrics"][0]["asset_fqn"] = asset["fqn"]
    asset["metrics"][0]["query_strategies"] = ["VIEW_REUSE"]
    asset["time_metadata"]["fields"][0]["field"]["asset_fqn"] = asset["fqn"]
    metadata = AnalysisRuntimeMetadata(
        assets=tuple(assets),
        schemas=copy.deepcopy(current.schemas),
        metric_terms=copy.deepcopy(current.metric_terms),
        result_rows=copy.deepcopy(current.result_rows),
    )
    return AnalysisController(
        AnalysisService(
            AnalysisRuntimeDataPlatformFake(metadata),
            model or MetadataDrivenAnalysisModel(),
        ),
        RoutingService(),
    )


def test_definition_request_accepts_only_title_and_source_request_id():
    base = {"title": "객실 운영", "source_request_id": str(uuid4())}
    for field in ("definition_id", "owner_id", "status", "question", "parameters", "result"):
        with pytest.raises(ValidationError):
            CreateAnalysisDefinitionRequest.model_validate({**base, field: "client"})


@async_test
async def test_definition_routes_are_owner_scoped_repository_calls_without_values_in_contract():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    request = CreateAnalysisDefinitionRequest(
        title="객실 운영",
        source_request_id=uuid4(),
    )
    with (
        patch.object(analysis_api, "_analysis_repository", return_value=repository),
        patch.object(analysis_api, "_controller", return_value=replay_controller()),
    ):
        created = await analysis_api.create_analysis_definition(request, context(owner))
        listed = (await analysis_api.list_analysis_definitions(context(owner)))["items"]
        fetched = await analysis_api.get_analysis_definition(
            repository.definition_id, context(owner)
        )

    assert created["definition_id"] == repository.definition_id
    assert listed == [created]
    assert fetched == created
    assert "parameters" not in created
    assert created["question"]
    assert created["semantic_request"]
    assert created["parameter_schema"]


@async_test
async def test_run_list_forwards_bounded_approved_artifact_filter():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    with patch.object(analysis_api, "_analysis_repository", return_value=repository):
        listed = await analysis_api.list_analysis_runs(
            context(owner),
            limit=7,
            approved_only=True,
            archived=True,
        )

    assert listed == {"items": []}
    assert repository.list_options == {
        "limit": 7,
        "approved_only": True,
        "archived": True,
    }


@async_test
async def test_artifact_lifecycle_routes_forward_authenticated_actor_without_admin_override():
    owner = uuid4()
    artifact_id = uuid4()
    repository = FakeAnalysisRepository(owner)
    request_context = context(owner)
    with patch.object(analysis_api, "_analysis_repository", return_value=repository):
        archived = await analysis_api.archive_analysis_artifact(
            artifact_id, request_context
        )
        restored = await analysis_api.restore_analysis_artifact(
            artifact_id, request_context
        )

    assert archived["artifact_id"] == str(artifact_id)
    assert archived["archived"] is True
    assert restored == {
        "artifact_id": str(artifact_id),
        "archived": False,
        "archived_at": None,
        "archived_by": None,
    }
    assert repository.lifecycle_calls == [
        ("archive", artifact_id, "analyst", request_context.trace_id),
        ("restore", artifact_id, "analyst", request_context.trace_id),
    ]


@async_test
async def test_repository_run_list_filters_approved_artifacts_before_lateral_limit():
    class Result:
        def mappings(self):
            return []

    class Session:
        statement = ""
        parameters = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement, parameters):
            self.statement = str(statement)
            self.parameters = parameters
            return Result()

    session = Session()

    def session_factory():
        return session

    repository = PostgresAnalysisRepository(
        "postgresql+psycopg://unused",
        uuid4(),
        session_factory=session_factory,
    )
    assert await repository.list_runs(limit=7, approved_only=True) == []

    artifact_filter = "AND (NOT :approved_only OR artifact.status = 'APPROVED')"
    assert artifact_filter in session.statement
    artifact_query = session.statement[session.statement.index(
        "FROM artifact.analysis_artifacts"
    ):]
    assert artifact_query.index(artifact_filter) < artifact_query.index("LIMIT 1")
    assert "AND a.artifact_id IS NOT NULL" in session.statement
    assert "artifact.user_artifact_lifecycle" in session.statement
    assert "request_id UNIQUE" in session.statement
    assert session.parameters["limit"] == 7
    assert session.parameters["approved_only"] is True
    assert session.parameters["archived"] is False


@async_test
async def test_replay_is_idempotent_and_approved_artifact_is_owner_scoped():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    first_context = context(owner)
    payload = ReplayAnalysisRequest(
        idempotency_key="run-1",
    )
    with (
        patch.object(analysis_api, "_analysis_repository", return_value=repository),
        patch.object(analysis_api, "_controller", return_value=replay_controller()),
    ):
        first = await analysis_api.replay_analysis_definition(
            repository.definition_id, payload, first_context
        )
        second = await analysis_api.replay_analysis_definition(
            repository.definition_id, payload, context(owner)
        )

    assert first == second
    assert first["request_id"] == first_context.request_id
    assert first["status"] == "SUCCEEDED", repository.finished[0].error
    assert first["as_of"] == first_context.as_of
    assert first["artifact_id"]
    assert repository.parameters == {
        "window_start": "2026-08-01",
        "window_end": "2026-08-02",
    }
    assert set(repository.finished[1]) == {
        "plan",
        "query",
        "package",
        "semantic_candidate_receipt",
    }
    assert repository.finished[0].data.result.evidence.cached is False
    assert repository.run_context is not None
    assert repository.run_context.product_release_id == "fixture-product-release"
    assert repository.run_context.permission_snapshot_id
    assert repository.run_context.semantic_release_id == "fixture-context-v1"
    assert repository.run_context.require_fresh_query is True
    assert len(repository.context_receipts) == 1
    assert repository.context_receipts[0][0].request_id == first_context.request_id
    package_bindings = {
        item.name: item.value
        for item in repository.finished[1]["package"].parameter_bindings
    }
    assert package_bindings == {
        "window_start": "2026-08-01",
        "window_end": "2026-08-02",
        "record_state_filter": "included",
    }
    assert ":record_state_filter" in repository.finished[1]["plan"]["sql"]
    assert "record_state" in repository.finished[1]["plan"]["sql"]
    assert "included" in repository.finished[1]["plan"]["executable_sql"]

    class SnapshotReceiptResult:
        def mappings(self):
            return self

        def one(self):
            return {
                "product_release_id": repository.run_context.product_release_id,
                "permission_snapshot_id": (
                    repository.run_context.permission_snapshot_id
                ),
                "semantic_release_id": repository.run_context.semantic_release_id,
            }

    class SnapshotCaptureSession:
        snapshot_parameters = None

        async def execute(self, statement, parameters):
            if "SELECT product_release_id" in str(statement):
                return SnapshotReceiptResult()
            self.snapshot_parameters = parameters
            return None

    capture_session = SnapshotCaptureSession()
    response, execution = repository.finished
    await PostgresAnalysisRepository._save_semantic_request_snapshot(
        capture_session,
        first_context.request_id,
        uuid4(),
        uuid4(),
        owner,
        response.data.result.evidence,
        execution,
    )
    saved_snapshot = parse_approved_semantic_request_snapshot(
        json.loads(capture_session.snapshot_parameters["snapshot"])
    )
    assert saved_snapshot.parameters == {
        "window_start": "2026-08-01",
        "window_end": "2026-08-02",
    }
    assert "record_state_filter" not in saved_snapshot.parameters
    assert "result" not in first
    assert "sql" not in first
    with patch.object(analysis_api, "_analysis_repository", return_value=repository):
        artifact = await analysis_api.get_analysis_run_artifact(
            first["request_id"], context(owner)
        )
    assert artifact["request_id"] == first["request_id"]
    assert artifact["artifact_id"] == first["artifact_id"]
    assert artifact["table"].rows
    assert artifact["metrics"] == artifact["evidence"].metric_values
    assert "sql" not in artifact
    assert "parameters" not in artifact


@async_test
async def test_replay_uses_saved_resolved_slots_for_context_dependent_question():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    repository.question = "4월은?"
    repository.definition["approved_semantic_snapshot"] = (
        approved_semantic_snapshot_fixture(
            period_start="2026-05-01",
            period_end="2026-06-01",
        ).model_dump(mode="json")
    )
    model = MetadataDrivenAnalysisModel()
    model.normalize_question = AsyncMock(
        side_effect=AssertionError("saved replay must not reinterpret an elliptical question")
    )
    controller = replay_controller(model)

    with (
        patch.object(analysis_api, "_analysis_repository", return_value=repository),
        patch.object(analysis_api, "_controller", return_value=controller),
    ):
        replayed = await analysis_api.replay_analysis_definition(
            repository.definition_id,
            ReplayAnalysisRequest(
                idempotency_key="saved-resolved-slots",
            ),
            context(owner),
        )

    assert replayed["status"] == "SUCCEEDED", repository.finished[0].error
    assert model.normalize_question.await_count == 0
    assert repository.finished[0].data.result.evidence.metrics[0].metric_id == "reviewed_measure"
    assert repository.finished[0].data.result.evidence.period.start.isoformat() == "2026-05-01"
    assert (
        repository.finished[0].data.result.evidence.period.end_exclusive.isoformat()
        == "2026-06-01"
    )
    assert repository.run_context is not None
    assert repository.run_context.require_fresh_query is True


@async_test
async def test_replay_snapshot_persistence_failure_closes_run_terminally():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    with (
        patch.object(analysis_api, "_analysis_repository", return_value=repository),
        patch.object(analysis_api, "_controller", return_value=replay_controller()),
        patch.object(
            repository,
            "finish_run",
            side_effect=ValueError("snapshot validation failed"),
        ),
        pytest.raises(HTTPException) as caught,
    ):
        await analysis_api.replay_analysis_definition(
            repository.definition_id,
            ReplayAnalysisRequest(idempotency_key="snapshot-persistence-failed"),
            context(owner),
        )

    assert caught.value.status_code == 503
    assert repository.finished == "PERSISTENCE"


def test_definition_public_projection_hides_snapshot_receipts_values_and_lineage():
    snapshot = approved_semantic_snapshot_fixture()
    row = {
        "definition_id": uuid4(),
        "version": 1,
        "title": "승인 분석",
        "question_text_redacted": "승인 분석 질문",
        "parameters": snapshot.parameters,
        "semantic_request": snapshot.model_dump(mode="json"),
        "parameter_schema": {
            item.name: item.value_type for item in snapshot.parameter_bindings
        },
        "created_at": datetime(2026, 8, 31, tzinfo=timezone.utc),
        "semantic_snapshot_id": snapshot.snapshot_id,
        "approved_semantic_snapshot": snapshot.model_dump(mode="json"),
        "approved_snapshot_hash": snapshot.snapshot_hash,
    }

    public = PostgresAnalysisRepository._definition(row)
    internal = PostgresAnalysisRepository._definition(row, replay=True)

    assert public["semantic_request"] == {
        "schema_version": "ANALYSIS-SEMANTIC-SUMMARY-v1",
        "output_metric_ids": ["reviewed_measure"],
        "operation": "aggregate",
        "time_mode": "range",
        "time_bucket": "none",
        "dimension_count": 0,
        "filter_count": 0,
        "comparison": False,
    }
    public_text = json.dumps(public, default=str)
    for secret in (
        str(snapshot.lineage.source_request_id),
        snapshot.release_receipt.permission_snapshot_id,
        snapshot.release_receipt.catalog_checksum,
        "serving.semantic.measure_events",
        "2026-08-01",
    ):
        assert secret not in public_text
    assert internal["approved_semantic_snapshot"] == snapshot.model_dump(mode="json")


@async_test
async def test_replay_legacy_definition_without_snapshot_is_blocked_before_run():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    repository.definition.pop("approved_semantic_snapshot")

    with (
        patch.object(analysis_api, "_analysis_repository", return_value=repository),
        pytest.raises(ContextValidationError) as caught,
    ):
        await analysis_api.replay_analysis_definition(
            repository.definition_id,
            ReplayAnalysisRequest(idempotency_key="legacy-no-snapshot"),
            context(owner),
        )

    assert caught.value.status_code == 409
    assert repository.request_id is None


@async_test
async def test_replay_blocks_saved_definition_from_a_different_context_release():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    repository.definition["approved_semantic_snapshot"] = (
        approved_semantic_snapshot_fixture(
            semantic_release_id="walkerhill-v4-schema-2.0.0-catalog-2.0.0"
        ).model_dump(mode="json")
    )
    payload = ReplayAnalysisRequest(
        idempotency_key="release-mismatch",
    )

    with (
        patch.object(analysis_api, "_analysis_repository", return_value=repository),
        pytest.raises(ContextValidationError) as caught,
    ):
        await analysis_api.replay_analysis_definition(
            repository.definition_id,
            payload,
            context(owner),
        )

    assert caught.value.code is ErrorCode.SCHEMA_VERSION_MISMATCH
    assert caught.value.status_code == 409
    assert repository.request_id is None


def test_run_history_uses_confirmed_artifact_period_for_direct_runs():
    run = PostgresAnalysisRepository._run(
        {
            "request_id": uuid4(),
            "definition_id": uuid4(),
            "definition_version": 1,
            "status": "SUCCEEDED",
            "as_of": date(2026, 8, 13),
            "timezone_name": "Asia/Seoul",
            "trace_id": "trace",
            "query_id": "query",
            "artifact_id": uuid4(),
            "error_type": None,
            "started_at": datetime(2026, 8, 13, tzinfo=timezone.utc),
            "completed_at": datetime(2026, 8, 13, tzinfo=timezone.utc),
            "question": "질문",
            "parameters": {},
            "artifact_period": {"start": "2026-05-01", "end_exclusive": "2026-07-01"},
        }
    )

    assert run["period_start"] == "2026-05-01"
    assert run["period_end_exclusive"] == "2026-07-01"


def test_run_history_preserves_latest_snapshot_time_evidence():
    run = PostgresAnalysisRepository._run(
        {
            "request_id": uuid4(),
            "definition_id": uuid4(),
            "definition_version": 1,
            "status": "SUCCEEDED",
            "as_of": date(2026, 8, 20),
            "timezone_name": "Asia/Seoul",
            "trace_id": "snapshot-trace",
            "query_id": "snapshot-query",
            "artifact_id": uuid4(),
            "error_type": None,
            "started_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
            "completed_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
            "question": "최신 회원 수",
            "parameters": {},
            "artifact_period": None,
            "artifact_snapshot": {
                "cutoff": "2026-08-20",
                "selection": "max_source_value_lt_as_of",
            },
        }
    )

    assert run["period_start"] is None
    assert run["period_end_exclusive"] is None
    assert run["snapshot_cutoff"] == "2026-08-20"
    assert run["snapshot_selection"] == "max_source_value_lt_as_of"


@async_test
async def test_direct_analysis_persists_request_query_and_artifact_when_database_is_configured():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    request_context = context(owner)
    with patch.object(
        analysis_api, "_analysis_repository", return_value=repository
    ), patch.dict(
        "os.environ", {"APP_RUNTIME_DATABASE_URL": "postgresql://configured"}
    ):
        response = await analysis_api.analysis(
            AnalysisRequest(question="합성 객실 운영 현황을 알려줘"),
            request_context,
        )

    assert response.data.status.value == "SUCCEEDED"
    assert repository.request_id == request_context.request_id
    assert repository.run_context is not None
    assert repository.run_context.product_release_id == "fixture-product-release"
    assert repository.run_context.semantic_release_id == "fixture-context-v1"
    assert repository.run_context.permission_snapshot_id
    assert len(repository.context_receipts) == 1
    assert repository.context_receipts[0][0].request_id == request_context.request_id
    assert repository.finished[0] is response
    assert set(repository.finished[1]) == {
        "plan",
        "query",
        "package",
        "semantic_candidate_receipt",
    }


@async_test
async def test_direct_analysis_returns_distinct_retryable_error_when_artifact_persistence_fails():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    request_context = context(owner)
    with patch.object(
        analysis_api, "_analysis_repository", return_value=repository
    ), patch.object(
        repository,
        "finish_run",
        side_effect=AnalysisRepositoryUnavailable("persistence unavailable"),
    ), patch.dict(
        "os.environ", {"APP_RUNTIME_DATABASE_URL": "postgresql://configured"}
    ):
        response = await analysis_api.analysis(
            AnalysisRequest(question="합성 객실 운영 현황을 알려줘"),
            request_context,
        )

    payload = json.loads(response.body)
    assert response.status_code == 503
    assert payload["error"]["code"] == "ARTIFACT_PERSIST_FAILED"
    assert payload["error"]["retryable"] is True
    assert payload["meta"]["trace_id"] == request_context.trace_id
    assert repository.finished == "PERSISTENCE"


@async_test
async def test_terminal_audit_links_request_query_artifact_and_redacted_trace():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    request_context = context(owner)
    with patch.object(
        analysis_api, "_analysis_repository", return_value=repository
    ), patch.dict(
        "os.environ", {"APP_RUNTIME_DATABASE_URL": "postgresql://configured"}
    ):
        response = await analysis_api.analysis(
            AnalysisRequest(question="합성 객실 운영 현황을 알려줘"),
            request_context,
        )

    class RecordingConnection:
        def __init__(self):
            self.statement = None
            self.parameters = None

        async def execute(self, statement, parameters):
            self.statement = str(statement)
            self.parameters = parameters

    connection = RecordingConnection()
    query_execution_id = uuid4()
    artifact_id = response.data.artifact.artifact_id
    await PostgresAnalysisRepository._save_audit(
        connection,
        request_context.request_id,
        response,
        query_execution_id,
        artifact_id,
    )

    details = __import__("json").loads(connection.parameters["details"])
    assert "INSERT INTO governance.audit_events" in connection.statement
    assert connection.parameters["request_id"] == request_context.request_id
    assert connection.parameters["query_execution_id"] == query_execution_id
    assert connection.parameters["artifact_id"] == artifact_id
    assert connection.parameters["action_code"] == "ANALYSIS_SUCCEEDED"
    assert details["status"] == "SUCCEEDED"
    assert details["query_id"] == response.data.result.evidence.query_id
    assert [step["stage"] for step in details["trace"]] == [
        step.stage.value for step in response.data.trace
    ]
    assert "question" not in details
    assert "sql" not in details


@async_test
async def test_replay_requires_store_and_existing_owner_definition():
    owner_context = context()
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(HTTPException) as unavailable:
            analysis_api._analysis_repository(owner_context)
    assert unavailable.value.status_code == 503

    repository = FakeAnalysisRepository(owner_context.user_id)
    with patch.object(analysis_api, "_analysis_repository", return_value=repository):
        with pytest.raises(HTTPException) as missing:
            await analysis_api.replay_analysis_definition(
                uuid4(),
                ReplayAnalysisRequest(idempotency_key="run-2"),
                owner_context,
            )
    assert missing.value.status_code == 404


def test_replay_request_rejects_client_owned_fields_and_blank_idempotency():
    for field, value in (("as_of", "2026-07-01"), ("status", "SUCCEEDED")):
        with pytest.raises(ValidationError):
            ReplayAnalysisRequest.model_validate(
                {"idempotency_key": "run", field: value}
            )
    with pytest.raises(ValidationError):
        ReplayAnalysisRequest(idempotency_key=" ")
