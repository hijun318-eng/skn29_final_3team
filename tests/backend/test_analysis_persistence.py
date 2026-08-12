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
        entitlement_hash="entitlement-hash",
        assets=(SimpleNamespace(urn="urn:source", fqn="catalog.schema.table", columns=("id",)),),
        metrics=(),
        approved_join_ids=(),
        policy_version="policy-v1",
        time_version="2026-08-12",
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
