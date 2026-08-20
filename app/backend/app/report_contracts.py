"""보고서 정의·실행·스케줄·문서 승인·AI 초안 API의 입출력 형식을 검증한다."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts import ChartSpec, Evidence, MetricValue, TableResult
from src.report.domain import BlockFailureCode


ReportOrientation = Literal["portrait", "landscape"]
CurrencyDisplayUnit = Literal[
    "auto", "one", "thousand", "million", "hundredMillion", "billion"
]


class ReportContractModel(BaseModel):
    """보고서 API에서 선언되지 않은 클라이언트 필드를 거부하는 공통 Pydantic 기반 모델이다."""
    model_config = ConfigDict(extra="forbid")


class ReportBlockRequest(ReportContractModel):
    """12열 격자에 배치할 표·차트·산출물·텍스트 블록의 위치, 크기와 데이터 참조를 입력받는다."""
    block_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    artifact_id: str | None = None
    query_id: str | None = None
    columns: int | None = Field(default=None, ge=1, le=12)
    type: Literal["table", "chart", "artifact", "text"] = "table"
    x: int = Field(default=0, ge=0, le=11)
    y: int = Field(default=0, ge=0)
    w: int | None = Field(default=None, ge=1, le=12)
    h: int = Field(default=1, ge=1)
    content: str = ""


class CreateReportDefinitionRequest(ReportContractModel):
    """새 보고서 정의의 식별자·제목·블록과 페이지 방향·통화 표시 단위를 입력받는다."""
    definition_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    blocks: list[ReportBlockRequest] = Field(default_factory=list)
    orientation: ReportOrientation = "portrait"
    currency_display_unit: CurrencyDisplayUnit = "auto"


class CreateReportFromArtifactRequest(ReportContractModel):
    """기존 분석 산출물 ID와 사용자 제목으로 첫 보고서 정의를 생성하도록 요청한다."""
    artifact_id: UUID
    title: str = Field(min_length=1, max_length=255)


class ReplaceReportBlocksRequest(ReportContractModel):
    """초안의 제목·전체 블록 배열·페이지 방향·통화 단위를 한 저장 요청으로 변경한다."""
    blocks: list[ReportBlockRequest]
    title: str | None = Field(default=None, min_length=1, max_length=255)
    orientation: ReportOrientation | None = None
    currency_display_unit: CurrencyDisplayUnit | None = None


class ApproveReportVersionRequest(ReportContractModel):
    """보고서 버전 승인 시각과 선택적 최종 페이지 방향을 서버에 전달한다."""
    approved_at: datetime
    orientation: ReportOrientation | None = None


class CreateManualRunRequest(ReportContractModel):
    """보고서 정의 버전과 멱등 키만 받아 서버 기준일의 수동 실행을 등록한다."""
    definition_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1)

    @field_validator("idempotency_key")
    @classmethod
    def reject_blank_idempotency_key(cls, value: str) -> str:
        """공백뿐인 멱등 키를 거부해 동일 실행 판별이 빈 값에 의존하지 않도록 한다."""
        if not value.strip():
            raise ValueError("idempotency_key는 비어 있을 수 없습니다.")
        return value


class ReportBlockResponse(ReportContractModel):
    """정규화된 블록 유형·격자 좌표·크기·내용과 분석 산출물 참조를 응답으로 반환한다."""
    block_id: str
    title: str
    artifact_id: str | None
    columns: int
    query_id: str | None
    type: Literal["table", "chart", "artifact", "text"]
    x: int
    y: int
    w: int
    h: int
    content: str


class ReportDefinitionResponse(ReportContractModel):
    """보고서 정의 버전의 초안·승인 상태, 블록, 승인 시각과 문서 표시 설정을 반환한다."""
    contract_version: str
    definition_id: str
    version: int
    status: Literal["draft", "approved"]
    title: str
    blocks: list[ReportBlockResponse]
    approved_at: datetime | None
    orientation: ReportOrientation
    currency_display_unit: CurrencyDisplayUnit


class ReportDefinitionListResponse(ReportContractModel):
    """계약 버전과 함께 접근 가능한 보고서 정의 버전 목록을 반환한다."""
    contract_version: str
    items: list[ReportDefinitionResponse]


class ReportArtifactVersionResponse(ReportContractModel):
    """승인 문서가 사용한 분석 산출물과 쿼리를 64자리 checksum에 결속해 재현성을 증명한다."""
    artifact_id: UUID
    artifact_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_id: str


class ReportDocumentResponse(ReportContractModel):
    """승인된 보고서 문서의 렌더러, 원본·HTML·PDF checksum과 사용 산출물 버전을 반환한다."""
    definition_id: UUID
    definition_version: int
    orientation: Literal["portrait", "landscape"]
    currency_display_unit: CurrencyDisplayUnit
    renderer_version: str
    source_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    html_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    pdf_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_versions: list[ReportArtifactVersionResponse]
    confirmed_at: datetime


class ReportArtifactResponse(ReportContractModel):
    """보고서가 참조할 분석 요약·지표·표·차트·증거를 산출물 ID 및 checksum과 반환한다."""
    contract_version: str
    artifact_id: UUID
    query_id: str
    title: str
    summary: str
    metrics: tuple[MetricValue, ...] = ()
    table: TableResult
    chart: ChartSpec | None = None
    evidence: Evidence
    artifact_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReportBlockRunResponse(ReportContractModel):
    """개별 블록 실행의 성공·부분·실패 상태와 산출물 증거 또는 구조화 실패 사유를 반환한다."""
    block_id: str
    artifact_id: str | None
    query_id: str | None
    snapshot_checksum: str | None
    status: Literal["success", "partial", "failed", "cancelled"]
    request_id: UUID | None = None
    failure_code: BlockFailureCode | None = None
    failure_message: str | None = Field(default=None, max_length=300)


class ReportRunResponse(ReportContractModel):
    """보고서 실행의 정의 버전, 기준 시각, 정책·문맥·watermark와 블록별 결과를 반환한다."""
    contract_version: str
    run_id: str
    definition_id: str
    definition_version: int
    as_of: datetime
    policy_version: str
    context_hash: str
    watermark: dict[str, str]
    status: Literal["queued", "running", "success", "partial", "failed", "cancelled"]
    blocks: list[ReportBlockRunResponse]


class ReportRunListResponse(ReportContractModel):
    """동일 보고서 계약 버전으로 직렬화된 실행 이력 목록을 반환한다."""
    contract_version: str
    items: list[ReportRunResponse]


class CreateReportScheduleRequest(ReportContractModel):
    """승인 정의 버전에 대한 일·주·월 주기와 offset 포함 다음 실행 시각을 등록한다."""
    schedule_id: UUID
    definition_id: UUID
    version: int = Field(ge=1)
    cadence: Literal["daily", "weekly", "monthly"]
    next_run_at: datetime
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"

    @field_validator("next_run_at")
    @classmethod
    def require_aware_next_run_at(cls, value: datetime) -> datetime:
        """스케줄 시각에 UTC offset이 없으면 시간대 해석이 모호하므로 저장 전에 거부한다."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("next_run_at에는 timezone offset이 필요합니다.")
        return value


class ReportScheduleResponse(ReportContractModel):
    """스케줄 식별자, 대상 정의 버전, 주기, 다음 실행, 활성 여부와 마지막 실행을 반환한다."""
    schedule_id: UUID
    definition_id: UUID
    version: int
    cadence: Literal["daily", "weekly", "monthly"]
    next_run_at: datetime
    timezone: Literal["Asia/Seoul"]
    enabled: bool
    last_run_id: UUID | None = None


class ReportScheduleListResponse(ReportContractModel):
    """조회 권한 범위 안의 보고서 스케줄들을 배열로 반환한다."""
    items: list[ReportScheduleResponse]


class UpdateReportScheduleRequest(ReportContractModel):
    """기존 스케줄의 활성화 여부만 변경하도록 제한된 입력을 받는다."""
    enabled: bool


class RunDueReportScheduleResponse(ReportContractModel):
    """스케줄 평가 결과와 실제 실행 여부, 실행된 경우 생성된 보고서 실행을 함께 반환한다."""
    schedule: ReportScheduleResponse
    executed: bool
    run: ReportRunResponse | None = None


class CreateReportAssistantDraftRequest(ReportContractModel):
    """검증된 분석 산출물과 500자 이하 편집 지시로 AI 보고서 초안 생성을 요청한다."""
    artifact_id: UUID
    instruction: str = Field(default="경영 검토용 보고서 초안을 구성해 줘", min_length=1, max_length=500)

    @field_validator("instruction")
    @classmethod
    def reject_blank_instruction(cls, value: str) -> str:
        """AI 초안 지시의 양끝 공백을 제거하고 의미 없는 빈 지시는 모델 호출 전에 거부한다."""
        if not value.strip():
            raise ValueError("instruction은 비어 있을 수 없습니다.")
        return value.strip()


class ReportAssistantTraceResponse(ReportContractModel):
    """AI 초안에 사용한 모델·프롬프트 버전과 해시, 시도 횟수·지연 시간을 감사 증거로 반환한다."""
    model_version: str
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    attempts: int
    duration_ms: float


class ReportAssistantDraftResponse(ReportContractModel):
    """AI 요청 ID, 성공 상태, 생성된 보고서 정의와 모델 호출 추적을 한 응답으로 반환한다."""
    assistant_request_id: UUID
    status: Literal["success"]
    definition: ReportDefinitionResponse
    trace: ReportAssistantTraceResponse


class ManualRunCommandResponse(ReportContractModel):
    """수동 실행 명령의 멱등 키, 대상 정의, 기준 시각, 상태와 생성된 실행 ID를 반환한다."""
    contract_version: str
    command_id: str
    definition_id: str
    version: int
    as_of: datetime
    idempotency_key: str
    status: Literal["queued", "running", "success", "partial", "failed", "cancelled"]
    run_id: str | None = None
