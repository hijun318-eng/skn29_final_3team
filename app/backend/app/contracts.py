"""분석·상태·인증 API 응답과 실행 증거를 직렬화하는 공개 계약을 정의한다."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from pydantic import Field, model_validator

from app.contract_core import (
    CONTRACT_VERSION,
    OPENAPI_DOCUMENT_VERSION,
    AnalysisRequest,
    AnalysisStatus,
    ClarificationType,
    ContractModel,
    ErrorBody,
    ErrorCode,
    PipelineStage,
    RequestContext,
    RequiredAction,
    ResolvedSlots,
    Role,
    RouteType,
    Scalar,
    StageOutcome,
    _REQUIRED_ACTION_BY_ERROR,
    _RETRYABLE_ERROR_CODES,
)


class ResponseMeta(ContractModel):
    """모든 API 응답에 요청·추적 ID, 분석 기준일, 계약 버전과 UTC 생성 시각을 부착한다."""
    request_id: UUID
    trace_id: str
    as_of: date
    contract_version: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SourceReference(ContractModel):
    """분석에 사용한 데이터 자산을 URN·FQN과 스키마·시드 버전으로 재현 가능하게 식별한다."""
    urn: str
    fqn: str
    name: str
    schema_version: str
    seed_version: str
    synthetic: bool | None = None


class MetricReference(ContractModel):
    """거버넌스 지표 ID를 결과 열, 표시명, 정의와 선택적 단위에 연결한다."""
    metric_id: str
    result_field: str
    label: str
    definition: str
    unit: str | None = None


class MetricValue(MetricReference):
    """지표 정의와 실제 스칼라 결과값을 함께 제공해 값의 의미를 독립적으로 해석하게 한다."""
    value: Scalar


class PeriodEvidence(ContractModel):
    """실행 SQL에 적용된 반개구간 조회 기간을 시작일과 미포함 종료일로 기록한다."""
    start: date
    end_exclusive: date


class SamplingEvidence(ContractModel):
    """결과 샘플링 여부와 반환 행 수, 확인 가능한 경우 전체 행 수를 증거로 남긴다."""
    applied: bool = False
    returned_rows: int = Field(default=0, ge=0)
    total_rows: int | None = Field(default=None, ge=0)


class MaskingEvidence(ContractModel):
    """민감 필드 마스킹 적용 여부와 가려진 필드 목록을 응답 소비자에게 공개한다."""
    applied: bool = False
    fields: tuple[str, ...] = ()


class ModelInvocationEvidence(ContractModel):
    """각 AI 노드가 사용한 모델과 프롬프트의 식별자·버전을 실행 증거로 고정한다."""
    node: str
    model_version: str
    prompt_id: str
    prompt_version: str


class GateEvidence(ContractModel):
    """문맥, SQL, 결과 검증 게이트의 최종 판정을 G1·G2·G3 순서로 제공한다."""
    g1: StageOutcome
    g2: StageOutcome
    g3: StageOutcome


class GateHistoryEvidence(ContractModel):
    """복구 시도를 포함해 각 검증 게이트에서 발생한 판정 이력을 순서대로 보존한다."""
    g1: tuple[StageOutcome, ...]
    g2: tuple[StageOutcome, ...]
    g3: tuple[StageOutcome, ...]


class TableResult(ContractModel):
    """열 순서와 스칼라 행 집합을 분리해 분석 결과 표의 직렬화 형태를 고정한다."""
    columns: tuple[str, ...]
    rows: tuple[dict[str, Scalar], ...]


class ChartSpec(ContractModel):
    """검증된 표 결과를 그릴 차트 유형, X축 필드와 하나 이상의 Y축 필드만 전달한다."""
    chart_type: str
    x_field: str
    y_fields: tuple[str, ...]


class Evidence(ContractModel):
    """기준일·필터·자산·지표·정책·모델·게이트·샘플링을 묶어 결과의 계보를 증명한다."""
    as_of: date
    timezone: str | None = None
    period: PeriodEvidence | None = None
    filters: dict[str, Scalar] = Field(default_factory=dict)
    sources: tuple[SourceReference, ...] = ()
    query_id: str | None = None
    artifact_id: UUID | None = None
    context_release: str | None = None
    product_release_id: str | None = None
    evidence_cutoff: date | None = None
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
    """요약과 선택적 지표·표·차트를 필수 실행 증거와 결합한 최종 분석 산출물이다."""
    summary: str
    metrics: tuple[MetricValue, ...] = ()
    table: TableResult | None = None
    chart: ChartSpec | None = None
    evidence: Evidence


class GateRequirements(ContractModel):
    """선택된 라우트에서 문맥 게이트와 SQL 게이트의 수행 필요 여부를 클라이언트에 알린다."""
    g1_required: bool
    g2_required: bool


class TraceStep(ContractModel):
    """파이프라인 단계별 판정과 공개 가능한 상세 사유를 시간 순서 추적으로 표현한다."""
    stage: PipelineStage
    outcome: StageOutcome
    detail: str | None = None


class ArtifactReference(ContractModel):
    """저장된 분석 산출물을 실행 쿼리와 승인된 문맥 해시에 결속하는 참조다."""
    artifact_id: UUID
    query_id: str
    context_hash: str


class AnalysisData(ContractModel):
    """현재 상태, 전이 이력, 선택 경로, 게이트, 결과와 산출물 참조를 분석 응답 본문에 담는다."""
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
    """진행 조회 시 실행 식별자, 시작 시각, 경과 시간, 취소 요청과 누적 추적을 반환한다."""
    trace_id: str
    request_id: UUID
    status: AnalysisStatus
    started_at: datetime
    elapsed_seconds: float = Field(ge=0)
    cancel_requested: bool
    trace: tuple[TraceStep, ...] = ()


class HealthData(ContractModel):
    """프로세스 생존 여부를 나타내는 최소 상태 문자열을 health 응답에 제공한다."""
    status: str


class ReadinessData(ContractModel):
    """서비스 준비 상태와 각 외부 의존성의 점검 결과를 readiness 응답으로 제공한다."""
    status: str
    dependencies: dict[str, str]


class SessionData(ContractModel):
    """현재 인증 세션 상태와 서버가 확인한 역할을 반환하며 미확인 역할은 비워 둔다."""
    status: str = "authenticated"
    role: Role | None = None


class LoginRequest(ContractModel):
    """허용 문자와 길이가 제한된 사용자명 및 비밀번호를 로그인 경계에서 검증한다."""
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9._-]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginData(SessionData):
    """로그인 성공 시 확정된 세션 상태와 역할을 SessionData 형식으로 반환한다."""
    pass


class EmptyData(ContractModel):
    """오류 응답에서도 data 필드를 객체로 유지하기 위한 필드 없는 계약 모델이다."""
    pass


class ResponseContractModel(ContractModel):
    """data·meta·error 응답 계열이 같은 추적 ID를 공유하도록 후처리하는 기반 모델이다."""
    @model_validator(mode="after")
    def bind_error_trace(self) -> "ResponseContractModel":
        """오류에 trace_id가 없을 때만 응답 메타데이터 값을 채워 명시 입력을 덮어쓰지 않는다."""
        error = getattr(self, "error", None)
        meta = getattr(self, "meta", None)
        if error is not None and meta is not None and not error.trace_id:
            object.__setattr__(error, "trace_id", meta.trace_id)
        return self


class AnalysisResponse(ResponseContractModel):
    """분석 상태·결과 본문과 공통 메타데이터, 선택적 구조화 오류를 반환한다."""
    data: AnalysisData
    meta: ResponseMeta
    error: ErrorBody | None = None


class AnalysisProgressResponse(ResponseContractModel):
    """비동기 분석의 현재 진행 정보와 공통 메타데이터, 선택적 오류를 반환한다."""
    data: AnalysisProgressData
    meta: ResponseMeta
    error: ErrorBody | None = None


class HealthResponse(ResponseContractModel):
    """프로세스 health 본문을 공통 응답 메타데이터 및 선택적 오류와 감싼다."""
    data: HealthData
    meta: ResponseMeta
    error: ErrorBody | None = None


class ReadinessResponse(ResponseContractModel):
    """의존성 readiness 본문을 공통 응답 메타데이터 및 선택적 오류와 감싼다."""
    data: ReadinessData
    meta: ResponseMeta
    error: ErrorBody | None = None


class SessionResponse(ResponseContractModel):
    """현재 세션 인증 상태와 서버 확인 역할을 공통 응답 봉투로 반환한다."""
    data: SessionData
    meta: ResponseMeta
    error: ErrorBody | None = None


class LoginResponse(ResponseContractModel):
    """로그인 결과 세션을 공통 메타데이터와 선택적 구조화 오류로 반환한다."""
    data: LoginData
    meta: ResponseMeta
    error: ErrorBody | None = None


class ErrorResponse(ResponseContractModel):
    """정상 데이터가 없는 실패를 빈 data 객체, 공통 메타데이터와 필수 오류 본문으로 전달한다."""
    data: EmptyData = Field(default_factory=EmptyData)
    meta: ResponseMeta
    error: ErrorBody


def response_meta(context: RequestContext) -> ResponseMeta:
    """요청 문맥의 식별자·기준일·계약 버전을 새 UTC 타임스탬프가 포함된 응답 메타로 복사한다."""
    return ResponseMeta(
        request_id=context.request_id,
        trace_id=context.trace_id,
        as_of=context.as_of,
        contract_version=context.contract_version,
    )
