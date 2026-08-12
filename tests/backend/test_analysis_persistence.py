from __future__ import annotations

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

    def begin_request(self, question, request_context):
        self.question = question
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
