from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts import Scalar


ANALYSIS_PERSISTENCE_VERSION = "ANALYSIS-PERSISTENCE-v1.0.0-DRAFT"
_PARAMETER_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_SERVER_FIELDS = {
    "artifact_id",
    "owner_id",
    "query_id",
    "request_id",
    "result",
    "sql",
    "status",
}


class AnalysisPersistenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateAnalysisDefinitionRequest(AnalysisPersistenceModel):
    title: str = Field(min_length=1, max_length=255)
    question: str = Field(min_length=1, max_length=1000)
    parameters: dict[str, Scalar] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Scalar]) -> dict[str, Scalar]:
        invalid = {
            name
            for name in value
            if not _PARAMETER_NAME.fullmatch(name) or name in _SERVER_FIELDS
        }
        if invalid:
            raise ValueError("parameter 이름은 승인된 snake_case만 허용합니다.")
        return value


class ReplayAnalysisRequest(AnalysisPersistenceModel):
    as_of: date
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def reject_blank_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("idempotency_key는 비어 있을 수 없습니다.")
        return value


class AnalysisDefinitionResponse(AnalysisPersistenceModel):
    contract_version: str = ANALYSIS_PERSISTENCE_VERSION
    definition_id: UUID
    version: int
    status: Literal["approved"]
    title: str
    parameter_types: dict[str, Literal["string", "boolean", "number", "null"]]
    created_at: datetime


class AnalysisDefinitionListResponse(AnalysisPersistenceModel):
    contract_version: str = ANALYSIS_PERSISTENCE_VERSION
    items: list[AnalysisDefinitionResponse]


class AnalysisRunResponse(AnalysisPersistenceModel):
    contract_version: str = ANALYSIS_PERSISTENCE_VERSION
    request_id: UUID
    definition_id: UUID
    definition_version: int
    status: Literal["RECEIVED", "SUCCEEDED", "PARTIAL", "FAILED", "BLOCKED"]
    as_of: date
    timezone: str
    trace_id: str
    query_id: str | None = None
    artifact_id: UUID | None = None
    error_type: str | None = None
    started_at: datetime
    completed_at: datetime | None = None


class AnalysisRunListResponse(AnalysisPersistenceModel):
    contract_version: str = ANALYSIS_PERSISTENCE_VERSION
    items: list[AnalysisRunResponse]
