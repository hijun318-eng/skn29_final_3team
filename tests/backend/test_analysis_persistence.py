from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from sys import path
from unittest.mock import patch
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
from app.contracts import AnalysisRequest, RequestContext  # noqa: E402
from app.controllers.analysis_controller import AnalysisController  # noqa: E402
from app.services.analysis_service import AnalysisService  # noqa: E402
from app.services.routing_service import RoutingService  # noqa: E402
from tests.support.fakes import FakeDataPlatformAdapter, FakeModelAdapter  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_test_controller():
    controller = AnalysisController(
        AnalysisService(FakeDataPlatformAdapter(), FakeModelAdapter()),
        RoutingService(),
    )
    with patch.object(analysis_api, "_controller", return_value=controller):
        yield


class FakeAnalysisRepository:
    def __init__(self, owner_id: UUID) -> None:
        self.owner_id = owner_id
        self.definition_id = uuid4()
        self.request_id: UUID | None = None
        self.finished = None
        self.definition = {
            "contract_version": "ANALYSIS-PERSISTENCE-v1.0.0-DRAFT",
            "definition_id": self.definition_id,
            "version": 1,
            "status": "approved",
            "title": "객실 운영",
            "question": "합성 객실 운영 현황을 알려줘",
            "parameter_types": {"scenario": "string"},
            "semantic_request": {"question": "합성 객실 운영 현황을 알려줘"},
            "parameter_schema": {"scenario": "string"},
            "created_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
        }
        self.question = "합성 객실 운영 현황을 알려줘"
        self.parameters = {"scenario": "success"}

    def begin_request(self, question, parameters, request_context):
        self.question = question
        self.parameters = parameters
        self.request_id = request_context.request_id
        return self.request_id

    def create_definition_from_run(self, source_request_id, title):
        self.definition.update(title=title)
        return self.definition

    def list_definitions(self):
        return [self.definition]

    def get_definition(self, definition_id, *, replay=False):
        if definition_id != self.definition_id:
            raise KeyError("Analysis Definition을 찾을 수 없습니다.")
        if replay:
            return {**self.definition, "question": self.question, "parameters": self.parameters}
        return self.definition

    def begin_run(self, definition, context, as_of, idempotency_key, parameters=None):
        if self.request_id is not None:
            return self.request_id, False
        self.request_id = context.request_id
        self.as_of = as_of
        self.idempotency_key = idempotency_key
        self.parameters = parameters if parameters is not None else definition["parameters"]
        return self.request_id, True

    def finish_run(self, request_id, response, execution):
        self.finished = (response, execution)

    def fail_run(self, request_id, error_type="UNSUPPORTED"):
        self.finished = error_type

    def get_run(self, request_id):
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

    def list_runs(self):
        return [] if self.request_id is None else [self.get_run(self.request_id)]

    def get_run_artifact(self, request_id):
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


def context(owner_id: UUID | None = None) -> RequestContext:
    return RequestContext(
        request_id=uuid4(),
        trace_id="analysis-persistence-trace",
        user_id=owner_id or uuid4(),
        as_of=date(2026, 8, 1),
    )


def test_definition_request_accepts_only_title_and_source_request_id():
    base = {"title": "객실 운영", "source_request_id": str(uuid4())}
    for field in ("definition_id", "owner_id", "status", "question", "parameters", "result"):
        with pytest.raises(ValidationError):
            CreateAnalysisDefinitionRequest.model_validate({**base, field: "client"})


def test_definition_routes_are_owner_scoped_repository_calls_without_values_in_contract():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    request = CreateAnalysisDefinitionRequest(
        title="객실 운영",
        source_request_id=uuid4(),
    )
    with patch.object(analysis_api, "_analysis_repository", return_value=repository):
        created = analysis_api.create_analysis_definition(request, context(owner))
        listed = analysis_api.list_analysis_definitions(context(owner))["items"]
        fetched = analysis_api.get_analysis_definition(repository.definition_id, context(owner))

    assert created["definition_id"] == repository.definition_id
    assert listed == [created]
    assert fetched == created
    assert "parameters" not in created
    assert created["question"]
    assert created["semantic_request"]
    assert created["parameter_schema"]


def test_replay_is_idempotent_and_approved_artifact_is_owner_scoped():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    first_context = context(owner)
    payload = ReplayAnalysisRequest(
        as_of=date(2026, 7, 1),
        idempotency_key="run-1",
        parameters={"scenario": "success_changed"},
    )
    with patch.object(analysis_api, "_analysis_repository", return_value=repository):
        first = analysis_api.replay_analysis_definition(
            repository.definition_id, payload, first_context
        )
        second = analysis_api.replay_analysis_definition(
            repository.definition_id, payload, context(owner)
        )

    assert first == second
    assert first["request_id"] == first_context.request_id
    assert first["status"] == "SUCCEEDED"
    assert first["as_of"] == date(2026, 7, 1)
    assert first["artifact_id"]
    assert repository.parameters == {"scenario": "success_changed"}
    assert set(repository.finished[1]) == {"plan", "query", "package"}
    assert "result" not in first
    assert "sql" not in first
    with patch.object(analysis_api, "_analysis_repository", return_value=repository):
        artifact = analysis_api.get_analysis_run_artifact(first["request_id"], context(owner))
    assert artifact["request_id"] == first["request_id"]
    assert artifact["artifact_id"] == first["artifact_id"]
    assert artifact["table"].rows
    assert artifact["metrics"] == artifact["evidence"].metric_values
    assert "sql" not in artifact
    assert "parameters" not in artifact


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


def test_direct_analysis_persists_request_query_and_artifact_when_database_is_configured():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    request_context = context(owner)
    with patch.object(
        analysis_api, "_analysis_repository", return_value=repository
    ), patch.dict(
        "os.environ", {"APP_RUNTIME_DATABASE_URL": "postgresql://configured"}
    ):
        response = analysis_api.analysis(
            AnalysisRequest(question="합성 객실 운영 현황을 알려줘"),
            request_context,
        )

    assert response.data.status.value == "SUCCEEDED"
    assert repository.request_id == request_context.request_id
    assert repository.finished[0] is response
    assert set(repository.finished[1]) == {"plan", "query", "package"}


def test_direct_analysis_returns_distinct_retryable_error_when_artifact_persistence_fails():
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
        response = analysis_api.analysis(
            AnalysisRequest(question="합성 객실 운영 현황을 알려줘"),
            request_context,
        )

    payload = json.loads(response.body)
    assert response.status_code == 503
    assert payload["error"]["code"] == "ARTIFACT_PERSIST_FAILED"
    assert payload["error"]["retryable"] is True
    assert payload["meta"]["trace_id"] == request_context.trace_id
    assert repository.finished == "ARTIFACT_PERSIST_FAILED"


def test_terminal_audit_links_request_query_artifact_and_redacted_trace():
    owner = uuid4()
    repository = FakeAnalysisRepository(owner)
    request_context = context(owner)
    with patch.object(
        analysis_api, "_analysis_repository", return_value=repository
    ), patch.dict(
        "os.environ", {"APP_RUNTIME_DATABASE_URL": "postgresql://configured"}
    ):
        response = analysis_api.analysis(
            AnalysisRequest(question="합성 객실 운영 현황을 알려줘"),
            request_context,
        )

    class RecordingConnection:
        def __init__(self):
            self.statement = None
            self.parameters = None

        def execute(self, statement, parameters):
            self.statement = str(statement)
            self.parameters = parameters

    connection = RecordingConnection()
    query_execution_id = uuid4()
    artifact_id = response.data.artifact.artifact_id
    PostgresAnalysisRepository._save_audit(
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


def test_replay_requires_store_and_existing_owner_definition():
    owner_context = context()
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(HTTPException) as unavailable:
            analysis_api._analysis_repository(owner_context)
    assert unavailable.value.status_code == 503

    repository = FakeAnalysisRepository(owner_context.user_id)
    with patch.object(analysis_api, "_analysis_repository", return_value=repository):
        with pytest.raises(HTTPException) as missing:
            analysis_api.replay_analysis_definition(
                uuid4(),
                ReplayAnalysisRequest(as_of=date(2026, 7, 1), idempotency_key="run-2"),
                owner_context,
            )
    assert missing.value.status_code == 404


def test_replay_request_rejects_client_owned_status_and_blank_idempotency():
    with pytest.raises(ValidationError):
        ReplayAnalysisRequest.model_validate(
            {"as_of": "2026-07-01", "idempotency_key": "run", "status": "SUCCEEDED"}
        )
    with pytest.raises(ValidationError):
        ReplayAnalysisRequest(as_of=date(2026, 7, 1), idempotency_key=" ")
