"""승인된 분석 정의의 생성·재실행·이력·산출물 API 형식을 검증한다."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts import ChartSpec, Evidence, MetricValue, Scalar, TableResult


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


def _validate_parameters(value: dict[str, Scalar]) -> dict[str, Scalar]:
    invalid = {
        name
        for name in value
        if not _PARAMETER_NAME.fullmatch(name) or name in _SERVER_FIELDS
    }
    if invalid:
        raise ValueError("parameter 이름은 승인된 snake_case만 허용합니다.")
    return value


class AnalysisPersistenceModel(BaseModel):
    """분석 영속 API에서 선언하지 않은 필드를 거부해 서버 소유 상태의 주입을 막는다."""
    model_config = ConfigDict(extra="forbid")


class CreateAnalysisDefinitionRequest(AnalysisPersistenceModel):
    """기존 분석 요청을 재사용 가능한 정의로 저장할 때 제목과 원본 요청 ID만 수신한다."""
    title: str = Field(min_length=1, max_length=255)
    source_request_id: UUID


class ReplayAnalysisRequest(AnalysisPersistenceModel):
    """정의 재실행의 기준일·멱등 키와 허용된 스칼라 매개변수를 입력받아 중복 실행을 통제한다."""
    as_of: date
    idempotency_key: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Scalar] = Field(default_factory=dict)

    @field_validator("idempotency_key")
    @classmethod
    def reject_blank_key(cls, value: str) -> str:
        """공백뿐인 멱등 키를 거부해 서로 다른 재실행 요청이 같은 빈 키로 합쳐지지 않게 한다."""
        if not value.strip():
            raise ValueError("idempotency_key는 비어 있을 수 없습니다.")
        return value

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Scalar]) -> dict[str, Scalar]:
        """매개변수 이름을 snake_case로 제한하고 서버가 생성하는 ID·SQL·상태 필드의 주입을 거부한다."""
        return _validate_parameters(value)


class AnalysisDefinitionResponse(AnalysisPersistenceModel):
    """승인된 분석 정의의 버전, 질문, 매개변수 형식과 구조화 의미 요청을 조회 결과로 제공한다."""
    contract_version: str = ANALYSIS_PERSISTENCE_VERSION
    definition_id: UUID
    version: int
    status: Literal["approved"]
    title: str
    question: str
    parameter_types: dict[str, Literal["string", "boolean", "number", "null"]]
    semantic_request: dict[str, Any]
    parameter_schema: dict[str, str]
    created_at: datetime


class AnalysisDefinitionListResponse(AnalysisPersistenceModel):
    """동일 계약 버전으로 직렬화된 승인 분석 정의 목록을 반환한다."""
    contract_version: str = ANALYSIS_PERSISTENCE_VERSION
    items: list[AnalysisDefinitionResponse]


class AnalysisRunResponse(AnalysisPersistenceModel):
    """정의 버전별 재실행 상태, 기준일·시간대, 추적·쿼리·산출물 ID와 완료 시각을 반환한다."""
    contract_version: str = ANALYSIS_PERSISTENCE_VERSION
    request_id: UUID
    definition_id: UUID
    definition_version: int
    status: Literal["RECEIVED", "SUCCEEDED", "PARTIAL", "FAILED", "BLOCKED", "CANCELLED"]
    as_of: date
    timezone: str
    trace_id: str
    query_id: str | None = None
    artifact_id: UUID | None = None
    error_type: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    question: str
    period_start: date | None = None
    period_end_exclusive: date | None = None


class AnalysisRunListResponse(AnalysisPersistenceModel):
    """분석 재실행 이력 항목들을 영속 계약 버전과 함께 목록으로 반환한다."""
    contract_version: str = ANALYSIS_PERSISTENCE_VERSION
    items: list[AnalysisRunResponse]


class AnalysisRunArtifactResponse(AnalysisPersistenceModel):
    """성공 또는 부분 성공 실행의 표·차트·지표·증거를 산출물 및 쿼리 ID와 SHA-256에 결속한다."""
    contract_version: str = ANALYSIS_PERSISTENCE_VERSION
    request_id: UUID
    trace_id: str
    status: Literal["SUCCEEDED", "PARTIAL"]
    question: str
    summary: str
    metrics: tuple[MetricValue, ...] = ()
    table: TableResult
    chart: ChartSpec | None = None
    evidence: Evidence
    artifact_id: UUID
    query_id: str
    artifact_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
