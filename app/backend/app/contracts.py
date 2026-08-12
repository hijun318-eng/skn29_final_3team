from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import TypeAlias
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


CONTRACT_VERSION = "OPENAPI-v1.0.0"
OPENAPI_DOCUMENT_VERSION = "OPENAPI-v1.2.0-DRAFT"
Scalar: TypeAlias = str | int | float | bool | None


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ROUTED = "ROUTED"
    SUCCEEDED = "SUCCEEDED"
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PipelineStage(str, Enum):
    ROUTER = "ROUTER"
    CONTROLLER = "CONTROLLER"
    CONTEXT = "CONTEXT"
    G1 = "G1"
    MODEL = "MODEL"
    G2 = "G2"
    REPAIR = "REPAIR"
    QUERY = "QUERY"
    G3 = "G3"
    ARTIFACT = "ARTIFACT"


class StageOutcome(str, Enum):
    PASSED = "PASSED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class Role(str, Enum):
    HOTEL_ANALYST = "hotel_analyst"
    REPORT_ADMIN = "report_admin"
    DATA_ADMIN = "data_admin"


class RouteType(str, Enum):
    GENERAL = "GENERAL"
    TEMPLATE = "TEMPLATE"


class ErrorCode(str, Enum):
    CONTEXT_INCOMPLETE = "CONTEXT_INCOMPLETE"
    ACCESS_DENIED = "ACCESS_DENIED"
    SQL_POLICY_BLOCKED = "SQL_POLICY_BLOCKED"
    QUERY_SOURCE_FAILED = "QUERY_SOURCE_FAILED"
    RESULT_EVIDENCE_MISSING = "RESULT_EVIDENCE_MISSING"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    RATE_LIMITED = "RATE_LIMITED"
    CONTRACT_VERSION_MISMATCH = "CONTRACT_VERSION_MISMATCH"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    REPORT_SCHEDULE_NOT_READY = "REPORT_SCHEDULE_NOT_READY"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class RequestContext(ContractModel):
    request_id: UUID = Field(default_factory=uuid4)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    conversation_id: UUID | None = None
    user_id: UUID = UUID(int=0)
    role: Role = Role.HOTEL_ANALYST
    as_of: date = Field(default_factory=date.today)
    timezone: str = "Asia/Seoul"
    contract_version: str = CONTRACT_VERSION
    access_profile: str | None = None
    database_grants: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()
    access_policy_version: str | None = None
    entitlement_hash: str | None = None
    trino_principal: str | None = None
    datahub_principal: str | None = None


class AnalysisRequest(ContractModel):
    question: str = Field(min_length=1, max_length=1000)
    template_id: str | None = Field(default=None, max_length=128)
    parameters: dict[str, Scalar] = Field(default_factory=dict)
    selected_metric_ids: tuple[str, ...] = Field(default=(), max_length=8)


class ClarificationOption(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=200)
    question_suffix: str = Field(min_length=1, max_length=200)


class ErrorBody(ContractModel):
    code: ErrorCode
    message: str
    retryable: bool = False
    clarification_options: tuple[ClarificationOption, ...] = ()


class ResponseMeta(ContractModel):
    request_id: UUID
    trace_id: str
    as_of: date
    contract_version: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SourceReference(ContractModel):
    urn: str
    fqn: str
    name: str
    schema_version: str
    seed_version: str


class MetricValue(ContractModel):
    metric_id: str
    label: str
    value: Scalar
    unit: str | None = None


class PeriodEvidence(ContractModel):
    start: date
    end_exclusive: date


class SamplingEvidence(ContractModel):
    applied: bool = False
    returned_rows: int = Field(default=0, ge=0)
    total_rows: int | None = Field(default=None, ge=0)


class MaskingEvidence(ContractModel):
    applied: bool = False
    fields: tuple[str, ...] = ()


class TableResult(ContractModel):
    columns: tuple[str, ...]
    rows: tuple[dict[str, Scalar], ...]


class ChartSpec(ContractModel):
    chart_type: str
    x_field: str
    y_fields: tuple[str, ...]


class Evidence(ContractModel):
    as_of: date
    period: PeriodEvidence | None = None
    filters: dict[str, Scalar] = Field(default_factory=dict)
    sources: tuple[SourceReference, ...] = ()
    query_id: str | None = None
    artifact_id: UUID | None = None
    context_release: str | None = None
    policy_version: str | None = None
    model_version: str | None = None
    sampling: SamplingEvidence = Field(default_factory=SamplingEvidence)
    masking: MaskingEvidence = Field(default_factory=MaskingEvidence)
    cached: bool = False


class AnalysisResult(ContractModel):
    summary: str
    metrics: tuple[MetricValue, ...] = ()
    table: TableResult | None = None
    chart: ChartSpec | None = None
    evidence: Evidence


class GateRequirements(ContractModel):
    g1_required: bool
    g2_required: bool


class TraceStep(ContractModel):
    stage: PipelineStage
    outcome: StageOutcome
    detail: str | None = None


class ArtifactReference(ContractModel):
    artifact_id: UUID
    query_id: str
    context_hash: str


class AnalysisData(ContractModel):
    status: AnalysisStatus
    transitions: tuple[AnalysisStatus, ...]
    route: RouteType | None = None
    template_id: str | None = None
    gates: GateRequirements | None = None
    result: AnalysisResult | None = None
    trace: tuple[TraceStep, ...] = ()
    repair_count: int = Field(default=0, ge=0, le=1)
    artifact: ArtifactReference | None = None


class HealthData(ContractModel):
    status: str


class ReadinessData(ContractModel):
    status: str
    dependencies: dict[str, str]


class EmptyData(ContractModel):
    pass


class AnalysisResponse(ContractModel):
    data: AnalysisData
    meta: ResponseMeta
    error: ErrorBody | None = None


class HealthResponse(ContractModel):
    data: HealthData
    meta: ResponseMeta
    error: ErrorBody | None = None


class ReadinessResponse(ContractModel):
    data: ReadinessData
    meta: ResponseMeta
    error: ErrorBody | None = None


class ErrorResponse(ContractModel):
    data: EmptyData = Field(default_factory=EmptyData)
    meta: ResponseMeta
    error: ErrorBody


def response_meta(context: RequestContext) -> ResponseMeta:
    return ResponseMeta(
        request_id=context.request_id,
        trace_id=context.trace_id,
        as_of=context.as_of,
        contract_version=context.contract_version,
    )
