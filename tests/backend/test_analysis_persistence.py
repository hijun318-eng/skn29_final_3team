from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from sys import path
from unittest.mock import MagicMock, patch
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
from app.adapters.analysis_repository import PostgresAnalysisRepository  # noqa: E402
from app.contracts import RequestContext  # noqa: E402


class InMemoryAnalysisRepository:
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
            "parameter_types": {"scenario": "string"},
            "created_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
        }
        self.question = "합성 객실 운영 현황을 알려줘"
        self.parameters = {"scenario": "success"}

    def begin_request(self, question, parameters, request_context):
        self.question = question
        self.parameters = parameters
        self.request_id = request_context.request_id
        return self.request_id

    def create_definition(self, title, question, parameters):
        self.definition.update(
            title=title,
            parameter_types={name: "string" for name in parameters},
        )
        self.question = question
        self.parameters = parameters
        return self.definition

    def list_definitions(self):
        return [self.definition]

    def get_definition(self, definition_id, *, replay=False):
        if definition_id != self.definition_id:
            raise KeyError("Analysis Definition을 찾을 수 없습니다.")
        if replay:
            return {**self.definition, "question": self.question, "parameters": self.parameters}
        return self.definition

    def begin_run(self, definition, context, as_of, idempotency_key):
        if self.request_id is not None:
            return self.request_id, False
        self.request_id = context.request_id
        self.as_of = as_of
        self.idempotency_key = idempotency_key
        return self.request_id, True

    def finish_run(self, request_id, response, execution):
        self.finished = (response, execution)

    def record_progress(self, request_id, stage, outcome):
        self.progress = getattr(self, "progress", []) + [(stage, outcome)]

    def get_progress(self, request_id):
        if request_id != self.request_id:
            raise KeyError("Analysis 요청을 찾을 수 없습니다.")
        return {
            "request_id": request_id,
            "status": "RECEIVED",
            "events": [
                {
                    "sequence": index,
                    "stage": stage,
                    "outcome": outcome,
                    "created_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
                }
                for index, (stage, outcome) in enumerate(self.progress, 1)
            ],
        }

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
        }

    def list_runs(self):
        return [] if self.request_id is None else [self.get_run(self.request_id)]

    def list_recent(self, limit=20, *, stale_before=None):
        if self.request_id is None:
            return []
        return [{
            "request_id": self.request_id,
            "trace_id": "analysis-persistence-trace",
            "question_text_redacted": "[REDACTED_EMAIL]의 객실 운영을 알려줘",
            "status": "RECEIVED",
            "started_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
            "as_of": date(2026, 8, 1),
            "access_profile": "pms_only",
        }][:limit]


def context(owner_id: UUID | None = None) -> RequestContext:
    return RequestContext(
        request_id=uuid4(),
        trace_id="analysis-persistence-trace",
        user_id=owner_id or uuid4(),
        as_of=date(2026, 8, 1),
    )


def test_definition_request_rejects_client_owned_fields_and_unsafe_parameter_names():
    base = {"title": "객실 운영", "question": "지난달 객실 운영을 알려줘"}
    for field in ("definition_id", "owner_id", "status", "request_id", "result"):
        with pytest.raises(ValidationError):
            CreateAnalysisDefinitionRequest.model_validate({**base, field: "client"})
    for name in ("sql", "result", "NotSnakeCase", "space key"):
        with pytest.raises(ValidationError):
            CreateAnalysisDefinitionRequest.model_validate(
                {**base, "parameters": {name: "client"}}
            )


def test_definition_routes_are_owner_scoped_repository_calls_without_values_in_contract():
    owner = uuid4()
    repository = InMemoryAnalysisRepository(owner)
    request = CreateAnalysisDefinitionRequest(
        title="객실 운영",
        question="user@example.com의 객실 운영을 알려줘",
        parameters={"scenario": "success"},
    )
    with patch.object(analysis_api, "_analysis_repository", return_value=repository):
        created = analysis_api.create_analysis_definition(request, context(owner))
        listed = analysis_api.list_analysis_definitions(context(owner))["items"]
        fetched = analysis_api.get_analysis_definition(repository.definition_id, context(owner))

    assert created["definition_id"] == repository.definition_id
    assert listed == [created]
    assert fetched == created
    assert "parameters" not in created
    assert "question" not in created
    assert "parameters" not in created


def test_replay_requires_store_and_existing_owner_definition():
    owner_context = context()
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(HTTPException) as unavailable:
            analysis_api._analysis_repository(owner_context)
    assert unavailable.value.status_code == 503

    repository = InMemoryAnalysisRepository(owner_context.user_id)
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


def test_progress_route_is_owner_scoped_and_returns_only_recorded_stage_events():
    owner = context()
    repository = InMemoryAnalysisRepository(owner.user_id)
    repository.request_id = owner.request_id
    repository.record_progress(owner.request_id, "DATAHUB", "STARTED")
    repository.record_progress(owner.request_id, "DATAHUB", "PASSED")

    with patch.object(analysis_api, "_analysis_repository", return_value=repository):
        progress = analysis_api.get_analysis_progress(owner.request_id, owner)

    assert [(item["stage"], item["outcome"]) for item in progress["events"]] == [
        ("DATAHUB", "STARTED"),
        ("DATAHUB", "PASSED"),
    ]
    with patch.object(analysis_api, "_analysis_repository", return_value=repository):
        with pytest.raises(HTTPException) as missing:
            analysis_api.get_analysis_progress(uuid4(), owner)
    assert missing.value.status_code == 404


def test_progress_repository_queries_are_owner_scoped():
    repository = PostgresAnalysisRepository.__new__(PostgresAnalysisRepository)
    repository._owner_id = uuid4()
    repository._engine = MagicMock()
    connection = repository._engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(KeyError):
        repository.get_progress(uuid4())

    statement, parameters = connection.execute.call_args.args
    assert "user_id = :owner_id" in str(statement)
    assert parameters["owner_id"] == repository._owner_id


def test_recent_analysis_is_owner_scoped_and_exposes_only_safe_resume_metadata():
    owner = context()
    repository = InMemoryAnalysisRepository(owner.user_id)
    repository.request_id = owner.request_id
    with patch.object(analysis_api, "_analysis_repository", return_value=repository):
        items = analysis_api.list_recent_analysis(owner, limit=20)["items"]

    assert items[0]["question_text_redacted"].startswith("[REDACTED_EMAIL]")
    assert set(items[0]) == {
        "request_id", "trace_id", "question_text_redacted", "status",
        "started_at", "as_of", "access_profile",
    }
    for forbidden in ("sql", "parameters", "result", "token"):
        assert forbidden not in items[0]


def test_recent_repository_query_filters_owner_and_never_selects_execution_payloads():
    repository = PostgresAnalysisRepository.__new__(PostgresAnalysisRepository)
    repository._owner_id = uuid4()
    repository._engine = MagicMock()
    connection = repository._engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value = []

    assert repository.list_recent(10) == []
    statement, parameters = connection.execute.call_args.args
    sql = str(statement).lower()
    assert "r.user_id = :owner_id" in sql
    assert "question_text_redacted" in sql
    for forbidden in ("sql_text", "parameters_json", "result_json", "token"):
        assert forbidden not in sql
    assert parameters == {"owner_id": repository._owner_id, "limit": 10}


def test_recent_repository_expires_only_received_requests_older_than_safe_timeout():
    repository = PostgresAnalysisRepository.__new__(PostgresAnalysisRepository)
    repository._owner_id = uuid4()
    repository._engine = MagicMock()
    connection = repository._engine.begin.return_value.__enter__.return_value
    stale_id = uuid4()
    update_result = MagicMock()
    update_result.scalars.return_value.all.return_value = [stale_id]
    audit_result = MagicMock()
    list_result = MagicMock()
    list_result.mappings.return_value = []
    connection.execute.side_effect = [update_result, audit_result, list_result]
    cutoff = datetime(2026, 8, 12, tzinfo=timezone.utc)

    assert repository.list_recent(20, stale_before=cutoff) == []
    update_sql = str(connection.execute.call_args_list[0].args[0])
    assert "status = 'FAILED'" in update_sql
    assert "status = 'RECEIVED'" in update_sql
    assert "started_at < :stale_before" in update_sql
    assert "analysis_stage_events" not in update_sql
    assert connection.execute.call_args_list[0].args[1] == {
        "owner_id": repository._owner_id,
        "stale_before": cutoff,
    }


def test_success_metadata_links_existing_release_package_and_model_without_payloads():
    release_id, package_id, model_id, request_id = (uuid4() for _ in range(4))
    connection = MagicMock()
    scalar = lambda value: MagicMock(scalar_one_or_none=lambda: value)
    package_scalar = MagicMock(scalar_one=lambda: package_id)
    connection.execute.side_effect = [
        scalar(release_id),
        MagicMock(),
        package_scalar,
        scalar(model_id),
        MagicMock(),
    ]
    package = SimpleNamespace(
        context_release="context-v1",
        context_release_id="00000000-0000-0000-0000-000000000201",
        entitlement_hash="entitlement-hash",
        assets=(SimpleNamespace(urn="urn:source", fqn="catalog.schema.table", columns=("id",)),),
        metrics=(),
        approved_join_ids=(),
        join_policies=(),
        policy_version="policy-v1",
        time_version="2026-08-12",
        time_policy_id="kr-calendar:v1:" + "a" * 64,
        route_type="GENERAL",
        template_id=None,
        calendar_id="gregorian-kr",
        timezone="Asia/Seoul",
        dataset_count=1,
        column_count=1,
        token_count=10,
        package_hash="a" * 64,
    )

    PostgresAnalysisRepository._link_execution_metadata(
        connection,
        request_id,
        {"plan": {"model_version": "MODEL-v1"}, "package": package},
    )

    update_sql, update_parameters = connection.execute.call_args.args
    assert "context_release_id = :release_id" in str(update_sql)
    assert update_parameters == {
        "request_id": request_id,
        "release_id": release_id,
        "package_id": package_id,
        "model_id": model_id,
        "policy_version": "policy-v1",
    }
    all_sql = " ".join(str(call.args[0]) for call in connection.execute.call_args_list)
    for forbidden in ("question_text_redacted", "generated_sql_redacted", "data_snapshot_json"):
        assert forbidden not in all_sql


def test_access_audit_records_only_entitlement_metadata_and_attempt_flags():
    connection = MagicMock()
    request_context = RequestContext(
        request_id=uuid4(), user_id=UUID(int=1), access_profile="pms_only",
        allowed_domains=("rooms",), access_policy_version="ACCESS-POLICY-v1.0.0",
        entitlement_hash="e" * 64,
    )
    profile = SimpleNamespace(
        name="pms_only", datahub_principal="urn:li:corpuser:answervice_pms_only",
        policy_version="ACCESS-POLICY-v1.0.0", entitlement_hash="e" * 64,
    )
    with patch("app.access_policy.resolve_access_profile", return_value=profile):
        PostgresAnalysisRepository._insert_access_audit(connection, request_context)

    statement, parameters = connection.execute.call_args.args
    details = __import__("json").loads(parameters["details"])
    assert "governance.audit_events" in str(statement)
    assert details == {
        "access_profile": "pms_only",
        "allowed_domains": ["rooms"],
        "datahub_actor": "urn:li:corpuser:answervice_pms_only",
        "allowed_urns": [],
        "policy_version": "ACCESS-POLICY-v1.0.0",
        "entitlement_hash": "e" * 64,
        "trino_role": "answervice_pms_only",
        "datahub_search_attempted": False,
        "trino_execution_attempted": False,
        "request_status": "RECEIVED",
    }
    serialized = str(parameters)
    for forbidden in ("question", "token", "select", "parameters", "result"):
        assert forbidden not in serialized.lower()
