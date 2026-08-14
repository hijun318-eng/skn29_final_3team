from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import TypeAlias
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CONTRACT_VERSION = "OPENAPI-v1.0.0"
OPENAPI_DOCUMENT_VERSION = "OPENAPI-v1.1.0-DRAFT"
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
    CONTEXT_SOURCE_FAILED = "CONTEXT_SOURCE_FAILED"
    DATA_ASSET_NOT_FOUND = "DATA_ASSET_NOT_FOUND"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    ACCESS_DENIED = "ACCESS_DENIED"
    MODEL_CONTRACT_INVALID = "MODEL_CONTRACT_INVALID"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_ENDPOINT_UNAVAILABLE = "MODEL_ENDPOINT_UNAVAILABLE"
    MODEL_OUTPUT_UNGROUNDED = "MODEL_OUTPUT_UNGROUNDED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    UNREPAIRABLE = "UNREPAIRABLE"
    SQL_POLICY_BLOCKED = "SQL_POLICY_BLOCKED"
    SQL_REPAIR_FAILED = "SQL_REPAIR_FAILED"
    TRINO_CONNECTION_FAILED = "TRINO_CONNECTION_FAILED"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    QUERY_SOURCE_FAILED = "QUERY_SOURCE_FAILED"
    RESULT_VALIDATION_FAILED = "RESULT_VALIDATION_FAILED"
    RESULT_EVIDENCE_MISSING = "RESULT_EVIDENCE_MISSING"
    ARTIFACT_PERSIST_FAILED = "ARTIFACT_PERSIST_FAILED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    RATE_LIMITED = "RATE_LIMITED"
    REQUEST_CANCELLED = "REQUEST_CANCELLED"
    CONTRACT_VERSION_MISMATCH = "CONTRACT_VERSION_MISMATCH"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ClarificationType(str, Enum):
    METRIC = "metric"
    PERIOD = "period"


class RequiredAction(str, Enum):
    NONE = "NONE"
    RETRY = "RETRY"
    AUTHENTICATE = "AUTHENTICATE"
    REQUEST_ACCESS = "REQUEST_ACCESS"
    PROVIDE_CONTEXT = "PROVIDE_CONTEXT"
    MODIFY_REQUEST = "MODIFY_REQUEST"
    CONTACT_SUPPORT = "CONTACT_SUPPORT"


class RequestContext(ContractModel):
    request_id: UUID = Field(default_factory=uuid4)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    conversation_id: UUID | None = None
    user_id: UUID = UUID(int=0)
    role: Role = Role.HOTEL_ANALYST
    as_of: date = Field(default_factory=date.today)
    timezone: str = "Asia/Seoul"
    contract_version: str = CONTRACT_VERSION


class AnalysisRequest(ContractModel):
    question: str = Field(min_length=1, max_length=1000)
    template_id: str | None = Field(default=None, max_length=128)
    parameters: dict[str, Scalar] = Field(default_factory=dict)

    @field_validator("question", mode="before")
    @classmethod
    def validate_question(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("분석 질문을 입력해 주세요.")
        return value

    @model_validator(mode="after")
    def validate_period(self) -> "AnalysisRequest":
        start_value = self.parameters.get("period_start")
        end_value = self.parameters.get("period_end_exclusive")
        if start_value is None and end_value is None:
            return self
        if not isinstance(start_value, str) or not isinstance(end_value, str):
            raise ValueError("period_start와 period_end_exclusive를 함께 입력해 주세요.")
        if any(
            len(value) != 10 or value[4] != "-" or value[7] != "-"
            for value in (start_value, end_value)
        ):
            raise ValueError("조회 기간은 YYYY-MM-DD 형식이어야 합니다.")
        try:
            start = date.fromisoformat(start_value)
            end = date.fromisoformat(end_value)
        except ValueError as exc:
            raise ValueError("유효한 조회 기간을 입력해 주세요.") from exc
        if start >= end:
            raise ValueError("종료일(미포함)은 시작일보다 늦어야 합니다.")
        return self


class ErrorBody(ContractModel):
    code: ErrorCode
    message: str
    missing_requirements: tuple[str, ...] = ()
    required_action: RequiredAction = RequiredAction.NONE
    retryable: bool = False
    suggestions: tuple[str, ...] = ()
    clarification_type: ClarificationType | None = None
    trace_id: str = ""

    def model_post_init(self, __context: object) -> None:
        if "retryable" not in self.model_fields_set:
            object.__setattr__(self, "retryable", self.code in _RETRYABLE_ERROR_CODES)
        if "required_action" not in self.model_fields_set:
            object.__setattr__(
                self,
                "required_action",
                _REQUIRED_ACTION_BY_ERROR.get(self.code, RequiredAction.NONE),
            )


_RETRYABLE_ERROR_CODES = {
    ErrorCode.MODEL_TIMEOUT,
    ErrorCode.MODEL_ENDPOINT_UNAVAILABLE,
    ErrorCode.CIRCUIT_OPEN,
    ErrorCode.TRINO_CONNECTION_FAILED,
    ErrorCode.QUERY_TIMEOUT,
    ErrorCode.QUERY_SOURCE_FAILED,
    ErrorCode.ARTIFACT_PERSIST_FAILED,
    ErrorCode.PARTIAL_FAILURE,
    ErrorCode.RATE_LIMITED,
    ErrorCode.DEPENDENCY_UNAVAILABLE,
}

_REQUIRED_ACTION_BY_ERROR = {
    ErrorCode.AUTHENTICATION_REQUIRED: RequiredAction.AUTHENTICATE,
    ErrorCode.ACCESS_DENIED: RequiredAction.REQUEST_ACCESS,
    ErrorCode.CONTEXT_INCOMPLETE: RequiredAction.PROVIDE_CONTEXT,
    ErrorCode.INSUFFICIENT_CONTEXT: RequiredAction.PROVIDE_CONTEXT,
    ErrorCode.DATA_ASSET_NOT_FOUND: RequiredAction.PROVIDE_CONTEXT,
    ErrorCode.CONTRACT_VERSION_MISMATCH: RequiredAction.MODIFY_REQUEST,
    ErrorCode.SCHEMA_VERSION_MISMATCH: RequiredAction.MODIFY_REQUEST,
    ErrorCode.RESOURCE_NOT_FOUND: RequiredAction.MODIFY_REQUEST,
    ErrorCode.RESOURCE_CONFLICT: RequiredAction.MODIFY_REQUEST,
    ErrorCode.SQL_POLICY_BLOCKED: RequiredAction.MODIFY_REQUEST,
    ErrorCode.MODEL_TIMEOUT: RequiredAction.RETRY,
    ErrorCode.MODEL_ENDPOINT_UNAVAILABLE: RequiredAction.RETRY,
    ErrorCode.CIRCUIT_OPEN: RequiredAction.RETRY,
    ErrorCode.TRINO_CONNECTION_FAILED: RequiredAction.RETRY,
    ErrorCode.QUERY_TIMEOUT: RequiredAction.RETRY,
    ErrorCode.QUERY_SOURCE_FAILED: RequiredAction.RETRY,
    ErrorCode.ARTIFACT_PERSIST_FAILED: RequiredAction.RETRY,
    ErrorCode.PARTIAL_FAILURE: RequiredAction.RETRY,
    ErrorCode.RATE_LIMITED: RequiredAction.RETRY,
    ErrorCode.DEPENDENCY_UNAVAILABLE: RequiredAction.RETRY,
    ErrorCode.INTERNAL_ERROR: RequiredAction.CONTACT_SUPPORT,
}


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
    synthetic: bool | None = None


class MetricReference(ContractModel):
    metric_id: str
    result_field: str
    label: str
    definition: str
    unit: str | None = None


class MetricValue(MetricReference):
    value: Scalar


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


class ModelInvocationEvidence(ContractModel):
    node: str
    model_version: str
    prompt_id: str
    prompt_version: str


class GateEvidence(ContractModel):
    g1: StageOutcome
    g2: StageOutcome
    g3: StageOutcome


class GateHistoryEvidence(ContractModel):
    g1: tuple[StageOutcome, ...]
    g2: tuple[StageOutcome, ...]
    g3: tuple[StageOutcome, ...]


class TableResult(ContractModel):
    columns: tuple[str, ...]
    rows: tuple[dict[str, Scalar], ...]


class ChartSpec(ContractModel):
    chart_type: str
    x_field: str
    y_fields: tuple[str, ...]


class Evidence(ContractModel):
    as_of: date
    timezone: str | None = None
    period: PeriodEvidence | None = None
    filters: dict[str, Scalar] = Field(default_factory=dict)
    sources: tuple[SourceReference, ...] = ()
    query_id: str | None = None
    artifact_id: UUID | None = None
    context_release: str | None = None
    policy_version: str | None = None
    model_version: str | None = None
    metrics: tuple[MetricReference, ...] = ()
    metric_values: tuple[MetricValue, ...] = ()
    models: tuple[ModelInvocationEvidence, ...] = ()
    gates: GateEvidence | None = None
    gate_history: GateHistoryEvidence | None = None
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


class AnalysisProgressData(ContractModel):
    trace_id: str
    request_id: UUID
    status: AnalysisStatus
    started_at: datetime
    elapsed_seconds: float = Field(ge=0)
    cancel_requested: bool
    trace: tuple[TraceStep, ...] = ()


class HealthData(ContractModel):
    status: str


class ReadinessData(ContractModel):
    status: str
    dependencies: dict[str, str]


class SessionData(ContractModel):
    status: str = "authenticated"
    role: Role | None = None


class LoginRequest(ContractModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9._-]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginData(SessionData):
    pass


class EmptyData(ContractModel):
    pass


class ResponseContractModel(ContractModel):
    @model_validator(mode="after")
    def bind_error_trace(self) -> "ResponseContractModel":
        error = getattr(self, "error", None)
        meta = getattr(self, "meta", None)
        if error is not None and meta is not None and not error.trace_id:
            object.__setattr__(error, "trace_id", meta.trace_id)
        return self


class AnalysisResponse(ResponseContractModel):
    data: AnalysisData
    meta: ResponseMeta
    error: ErrorBody | None = None


class AnalysisProgressResponse(ResponseContractModel):
    data: AnalysisProgressData
    meta: ResponseMeta
    error: ErrorBody | None = None


class HealthResponse(ResponseContractModel):
    data: HealthData
    meta: ResponseMeta
    error: ErrorBody | None = None


class ReadinessResponse(ResponseContractModel):
    data: ReadinessData
    meta: ResponseMeta
    error: ErrorBody | None = None


class SessionResponse(ResponseContractModel):
    data: SessionData
    meta: ResponseMeta
    error: ErrorBody | None = None


class LoginResponse(ResponseContractModel):
    data: LoginData
    meta: ResponseMeta
    error: ErrorBody | None = None


class ErrorResponse(ResponseContractModel):
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
