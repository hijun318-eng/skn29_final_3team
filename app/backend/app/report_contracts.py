"""보고서 정의·실행·스케줄·문서 승인·AI 초안 API의 입출력 형식을 검증한다."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """저장 요청의 근거 별칭을 bounded 고유 식별자로 제한한다."""

        if len(set(value)) != len(value) or any(
            not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", ref) for ref in value
        ):
            raise ValueError("Report block 근거 별칭 계약이 올바르지 않습니다.")
        return value


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
    type: Literal["table", "chart", "artifact", "text"]
    x: int
    y: int
    w: int
    h: int
    content: str
    evidence_refs: tuple[str, ...] = ()


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
    """보고서가 렌더링할 분석 내용과 공개 가능한 증거만 반환한다.

    query ID와 checksum은 저장소 내부 lineage 검증에만 사용하며 브라우저 계약에는 넣지 않는다.
    """
    contract_version: str
    artifact_id: UUID
    title: str
    summary: str
    metrics: tuple[MetricValue, ...] = ()
    table: TableResult
    chart: ChartSpec | None = None
    evidence: Evidence


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


ReportAssistantReviewCategory = Literal[
    "duplicate_text",
    "verbose_summary",
    "title_mismatch",
    "inconsistent_metric_expression",
    "unsupported_claim",
]


class ReportAssistantReviewFinding(ReportContractModel):
    """현재 보고서를 저장하지 않고 발견한 품질 문제와 사용자가 선택할 수정 지시다."""

    category: ReportAssistantReviewCategory
    severity: Literal["info", "warning"]
    block_id: str | None = None
    title: str = Field(min_length=1, max_length=255)
    detail: str = Field(min_length=1, max_length=1000)
    suggested_instruction: str = Field(min_length=1, max_length=500)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=16)


class ReportAssistantReviewResponse(ReportContractModel):
    """세션 상태나 Report revision을 바꾸지 않는 bounded 품질 검토 결과다."""

    assistant_request_id: UUID
    summary: str = Field(min_length=1, max_length=1000)
    findings: tuple[ReportAssistantReviewFinding, ...] = Field(max_length=10)
    suggestions: tuple[str, ...] = Field(default=(), max_length=3)
    trace: ReportAssistantTraceResponse


class ReportAssistantDraftResponse(ReportContractModel):
    """AI 요청 ID, 성공 상태, 생성된 보고서 정의와 모델 호출 추적을 한 응답으로 반환한다."""
    assistant_request_id: UUID
    status: Literal["success"]
    definition: ReportDefinitionResponse
    trace: ReportAssistantTraceResponse


ReportAssistantPhase = Literal[
    "ready",
    "waiting_patch_approval",
    "waiting_approval",
    "running_data_agent",
    "waiting_artifact",
    "saving_revision",
    "completed",
    "failed",
    "cancelled",
]


class ReportAssistantRequiredAction(str, Enum):
    """실패한 Assistant 세션에서 사용자가 수행할 수 있는 안전한 다음 조치다."""

    NONE = "NONE"
    RETRY = "RETRY"
    REFRESH = "REFRESH"
    REAUTHENTICATE = "REAUTHENTICATE"
    REOPEN_LATEST_REPORT = "REOPEN_LATEST_REPORT"
    CONTACT_ADMIN = "CONTACT_ADMIN"


class ReportAssistantRetryPolicy(ReportContractModel):
    """오류 code를 자동 실행 없는 재시도 가능 여부와 사용자 조치로 변환한다."""

    retryable: bool
    required_action: ReportAssistantRequiredAction


def report_assistant_retry_policy(error_code: str | None) -> ReportAssistantRetryPolicy:
    """서버 오류 code 하나에 대해 fail-closed 재시도 정책을 반환한다."""

    retryable = {
        "ANALYSIS_FAILED",
        "ANALYSIS_RATE_LIMITED",
        "ASSISTANT_CONCURRENCY_LIMITED",
        "ASSISTANT_EXECUTION_INTERRUPTED",
        "ASSISTANT_RATE_LIMITED",
        "REPORT_ASSISTANT_COMPOSE_FAILED",
        "REPORT_ASSISTANT_TURN_MODEL_FAILED",
        "REPORT_ASSISTANT_TURN_MODEL_INVALID",
    }
    actions = {
        "ACCESS_DENIED": ReportAssistantRequiredAction.REAUTHENTICATE,
        "ANALYSIS_ACCESS_DENIED": ReportAssistantRequiredAction.REAUTHENTICATE,
        "ARTIFACT_CHECKSUM_INVALID": ReportAssistantRequiredAction.CONTACT_ADMIN,
        "ARTIFACT_LINEAGE_MISMATCH": ReportAssistantRequiredAction.CONTACT_ADMIN,
        "ARTIFACT_NOT_FOUND": ReportAssistantRequiredAction.CONTACT_ADMIN,
        "ASSISTANT_COST_BUDGET_EXCEEDED": ReportAssistantRequiredAction.CONTACT_ADMIN,
        "ASSISTANT_STATE_CONFLICT": ReportAssistantRequiredAction.REFRESH,
        "ASSISTANT_TOKEN_BUDGET_EXCEEDED": ReportAssistantRequiredAction.CONTACT_ADMIN,
        "REPORT_REVISION_CONFLICT": ReportAssistantRequiredAction.REOPEN_LATEST_REPORT,
    }
    if error_code in retryable:
        return ReportAssistantRetryPolicy(
            retryable=True,
            required_action=ReportAssistantRequiredAction.RETRY,
        )
    return ReportAssistantRetryPolicy(
        retryable=False,
        required_action=actions.get(error_code, ReportAssistantRequiredAction.NONE),
    )


class CreateReportAssistantSessionRequest(ReportContractModel):
    """보고서 초안과 대표·추가 승인 Artifact 최대 다섯 개를 Assistant 세션에 결속한다."""

    definition_id: UUID
    definition_version: int = Field(ge=1)
    artifact_id: UUID
    additional_artifact_ids: tuple[UUID, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def require_unique_artifacts(self) -> "CreateReportAssistantSessionRequest":
        """대표 Artifact 중복과 추가 Artifact 간 중복을 모델 호출 전에 거부한다."""

        artifact_ids = (self.artifact_id, *self.additional_artifact_ids)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("Assistant Artifact는 중복될 수 없습니다.")
        return self


class ReportAssistantMessageRequest(ReportContractModel):
    """새 요청 또는 현재 patch를 교체할 500자 이하의 보고서 변경 지시를 제출한다."""

    instruction: str = Field(min_length=1, max_length=500)
    expected_patch_request_id: UUID | None = None
    selected_block_id: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("instruction")
    @classmethod
    def reject_blank_instruction(cls, value: str) -> str:
        """변경 지시의 양끝 공백을 제거하고 공백뿐인 입력을 모델 호출 전에 거부한다."""

        if not value.strip():
            raise ValueError("instruction은 비어 있을 수 없습니다.")
        return value.strip()


class ReportAssistantReviewRequest(ReportContractModel):
    """비저장 품질 검토가 참고할 현재 편집기 선택 블록을 선택적으로 지정한다."""

    selected_block_id: str | None = Field(default=None, min_length=1, max_length=255)


class ReportAssistantAnalysisScope(ReportContractModel):
    """승인 전에 사용자에게 공개할 조회 기간·지표·분석 범위를 제한된 문자열로 표현한다."""

    period: str = Field(min_length=1, max_length=255)
    metrics: tuple[str, ...] = Field(min_length=1, max_length=10)
    dimensions: tuple[str, ...] = Field(default=(), max_length=10)

    @field_validator("period")
    @classmethod
    def normalize_period(cls, value: str) -> str:
        """사용자 승인 카드에 의미 없는 공백 기간이 표시되지 않도록 정규화한다."""

        if not value.strip():
            raise ValueError("period는 비어 있을 수 없습니다.")
        return value.strip()

    @field_validator("metrics", "dimensions")
    @classmethod
    def normalize_scope_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """지표·차원 표시값의 공백과 중복을 거부해 승인 범위를 명확하게 유지한다."""

        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("scope 항목은 비어 있을 수 없습니다.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("scope 항목은 중복될 수 없습니다.")
        return normalized


class ReportAssistantAnalysisPlan(ReportContractModel):
    """새 데이터 실행 전에 질문·이유·범위를 request ID와 함께 고정한다."""

    request_id: UUID
    question: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=500)
    scope: ReportAssistantAnalysisScope

    @field_validator("question", "reason")
    @classmethod
    def normalize_plan_text(cls, value: str) -> str:
        """모델 계획의 질문·이유를 정규화하고 공백뿐인 출력을 승인 전에 거부한다."""

        if not value.strip():
            raise ValueError("analysis plan 문구는 비어 있을 수 없습니다.")
        return value.strip()


class ReportAssistantPatchPreviewItem(ReportContractModel):
    """식별자·SQL 없이 사용자가 승인 전에 확인할 operation별 변경 전후를 반환한다."""

    index: int = Field(ge=0, le=11)
    operation: Literal[
        "set_report_title", "add_text", "update_text", "add_artifact_view",
        "reposition_block", "remove_block", "duplicate_block",
        "restore_previous_revision",
    ]
    target: str = Field(min_length=1, max_length=255)
    before: str | None = Field(default=None, max_length=4000)
    after: str | None = Field(default=None, max_length=4000)
    impact_category: Literal["CONTENT", "LAYOUT", "DESTRUCTIVE"]
    evidence_required: bool
    evidence_count: int = Field(ge=0, le=16)

    @model_validator(mode="after")
    def bind_evidence_requirement(self) -> "ReportAssistantPatchPreviewItem":
        """근거 필요 operation은 하나 이상, 구조 operation은 0개의 공개 근거 개수만 허용한다."""

        if self.evidence_required != (self.evidence_count > 0):
            raise ValueError("patch 영향의 근거 필요 여부와 근거 개수가 일치하지 않습니다.")
        return self


class ReportAssistantSessionResponse(ReportContractModel):
    """서버가 소유하는 Assistant phase와 승인 대기 계획 및 revision 결과를 반환한다."""

    assistant_request_id: UUID
    phase: ReportAssistantPhase
    definition_id: UUID
    definition_version: int
    base_revision: int
    artifact_id: UUID
    artifact_ids: tuple[UUID, ...] = ()
    analysis_plan: ReportAssistantAnalysisPlan | None = None
    patch_request_id: UUID | None = None
    patch_summary: str | None = Field(default=None, min_length=1, max_length=1000)
    patch_operations: tuple[
        Literal[
            "set_report_title", "add_text", "update_text", "add_artifact_view",
            "reposition_block", "remove_block", "duplicate_block",
            "restore_previous_revision",
        ], ...
    ] = ()
    patch_evidence_refs: tuple[str, ...] = ()
    patch_preview: tuple[ReportAssistantPatchPreviewItem, ...] = ()
    approved_operation_indexes: tuple[int, ...] = ()
    result_artifact_id: UUID | None = None
    result_revision: int | None = None
    error_code: str | None = None
    retryable: bool = False
    required_action: ReportAssistantRequiredAction = ReportAssistantRequiredAction.NONE
    retry_of_assistant_request_id: UUID | None = None

    @model_validator(mode="after")
    def require_plan_during_data_flow(self) -> "ReportAssistantSessionResponse":
        """데이터 실행 관련 phase가 승인된 계획 없이 노출되는 상태를 거부한다."""

        if self.phase in {
            "waiting_approval",
            "running_data_agent",
            "waiting_artifact",
        } and self.analysis_plan is None:
            raise ValueError("데이터 실행 phase에는 analysis_plan이 필요합니다.")
        has_patch = bool(self.patch_request_id and self.patch_summary and self.patch_operations)
        if self.phase == "waiting_patch_approval" and not has_patch:
            raise ValueError("patch 승인 대기 phase에는 변경 미리보기가 필요합니다.")
        if self.phase == "waiting_patch_approval" and len(self.patch_preview) != len(
            self.patch_operations
        ):
            raise ValueError("patch 승인 대기 phase에는 operation별 미리보기가 필요합니다.")
        if self.phase == "saving_revision" and self.analysis_plan is None and not has_patch:
            raise ValueError("revision 저장 phase에는 분석 계획 또는 patch 미리보기가 필요합니다.")
        if self.approved_operation_indexes and (
            tuple(sorted(set(self.approved_operation_indexes)))
            != self.approved_operation_indexes
            or not self.patch_operations
            or self.approved_operation_indexes[-1] >= len(self.patch_operations)
        ):
            raise ValueError("승인 operation 선택이 저장 patch 범위를 벗어났습니다.")
        return self


class ReportAssistantApprovalRequest(ReportContractModel):
    """현재 승인 대기 계획에 대한 사용자의 승인 또는 거절 한 번만 입력받는다."""

    request_id: UUID
    approved: bool


class ReportAssistantPatchApprovalRequest(ReportAssistantApprovalRequest):
    """patch 승인 시 선택할 0-based operation 인덱스를 정렬된 고유 목록으로 받는다."""

    operation_indexes: tuple[int, ...] | None = Field(default=None, min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_operation_selection(self) -> "ReportAssistantPatchApprovalRequest":
        """기존 전체 승인 호환을 유지하며 명시 선택은 승인 요청에서만 허용한다."""

        if self.operation_indexes is not None:
            if not self.approved:
                raise ValueError("거절 요청에는 operation 선택을 포함할 수 없습니다.")
            if tuple(sorted(set(self.operation_indexes))) != self.operation_indexes:
                raise ValueError("operation 인덱스는 중복 없이 오름차순이어야 합니다.")
            if self.operation_indexes[0] < 0:
                raise ValueError("operation 인덱스는 0 이상이어야 합니다.")
        return self


class ReportAssistantProposalResponse(ReportContractModel):
    """검증된 변경 종류·사용자 메시지와 저장된 서버 세션 상태를 함께 반환한다."""

    change_kind: Literal["clarification", "existing_artifact", "new_data"]
    message: str = Field(min_length=1, max_length=1000)
    suggestions: tuple[str, ...] = Field(default=(), max_length=3)
    session: ReportAssistantSessionResponse


class ReportAssistantEvaluationResponse(ReportContractModel):
    """원문 prompt·SQL 없이 한 Assistant 요청의 모델·승인·Revision 결과를 연결한다."""

    evaluation_id: UUID
    assistant_request_id: UUID
    data_request_id: UUID | None = None
    patch_request_id: UUID | None = None
    definition_id: UUID | None = None
    definition_version: int | None = None
    artifact_id: UUID | None = None
    prompt_id: str | None = None
    prompt_version: str | None = None
    model_version: str | None = None
    route: Literal["existing_artifact", "new_data"] | None = None
    operation_types: tuple[str, ...] = ()
    contract_valid: bool
    approval_decision: Literal["approved", "rejected", "pending"]
    final_phase: str
    revision_created: bool
    duplicate_revision_prevented: bool
    model_attempts: int | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: Decimal | None = None
    cost_is_estimate: bool
    error_code: str | None = None
    evaluated_at: datetime


class ReportAssistantOperationsSummaryResponse(ReportContractModel):
    """관리자용 기간·분모와 nullable 품질·비용 집계를 반환한다."""

    period_start: datetime
    period_end: datetime
    denominator: int
    total_requests: int
    contract_success_rate: float | None = None
    patch_validation_success_rate: float | None = None
    approval_rate: float | None = None
    rejection_rate: float | None = None
    revision_success_rate: float | None = None
    duplicate_revision_prevention_rate: float | None = None
    failure_rate_by_error_code: dict[str, float]
    average_model_latency_ms: float | None = None
    p95_model_latency_ms: float | None = None
    average_model_attempts: float | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    estimated_cost_total: Decimal | None = None


class ReportAssistantFailureListResponse(ReportContractModel):
    """관리자에게 bounded 기간의 안전한 실패 평가만 반환한다."""

    period_start: datetime
    period_end: datetime
    items: tuple[ReportAssistantEvaluationResponse, ...]


class ReportAssistantPatchPlacement(ReportContractModel):
    """새 블록의 상대 위치와 폭 의도만 받아 실제 grid 좌표는 서버가 계산하게 한다."""

    after_block_id: str | None = Field(default=None, min_length=1)
    width: Literal["half", "full"] = "full"


class ReportAssistantSetTitleOperation(ReportContractModel):
    """현재 draft 제목을 근거와 무관한 다른 필드 변경 없이 교체한다."""

    op: Literal["set_report_title"]
    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        """공백 제목을 거부하고 저장될 제목의 바깥 공백을 제거한다."""

        if not value.strip():
            raise ValueError("보고서 제목은 비어 있을 수 없습니다.")
        return value.strip()


class ReportAssistantAddTextOperation(ReportContractModel):
    """모델이 제안한 근거 기반 문구를 새 text block으로 추가한다."""

    op: Literal["add_text"]
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=4000)
    evidence_refs: tuple[
        Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")], ...
    ] = Field(default=(), max_length=16)
    placement: ReportAssistantPatchPlacement = Field(
        default_factory=ReportAssistantPatchPlacement
    )

    @field_validator("title", "content")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        """빈 제목·본문을 patch 적용 전에 거부하고 바깥 공백을 제거한다."""

        if not value.strip():
            raise ValueError("text block 제목과 내용은 비어 있을 수 없습니다.")
        return value.strip()

    @field_validator("evidence_refs")
    @classmethod
    def require_unique_evidence_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """같은 근거 별칭의 중복을 거부해 승인 카드와 감사 patch를 결정적으로 유지한다."""

        if len(set(value)) != len(value):
            raise ValueError("text block 근거 별칭은 중복될 수 없습니다.")
        return value


class ReportAssistantUpdateTextOperation(ReportContractModel):
    """현재 보고서에 존재하는 text block 하나의 제목 또는 내용을 수정한다."""

    op: Literal["update_text"]
    block_id: str = Field(min_length=1)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    evidence_refs: tuple[
        Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")], ...
    ] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def require_change(self) -> "ReportAssistantUpdateTextOperation":
        """실제 변경값이 없거나 공백뿐인 text 수정 요청을 거부한다."""

        if self.title is None and self.content is None:
            raise ValueError("update_text에는 title 또는 content가 필요합니다.")
        if self.title is not None and not self.title.strip():
            raise ValueError("text block 제목은 비어 있을 수 없습니다.")
        if self.content is not None and not self.content.strip():
            raise ValueError("text block 내용은 비어 있을 수 없습니다.")
        if self.content is None and self.evidence_refs:
            raise ValueError("본문을 변경하지 않는 update_text에는 근거 별칭을 추가할 수 없습니다.")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("text block 근거 별칭은 중복될 수 없습니다.")
        self.title = self.title.strip() if self.title is not None else None
        self.content = self.content.strip() if self.content is not None else None
        return self


class ReportAssistantAddArtifactViewOperation(ReportContractModel):
    """서버가 제공한 별칭의 검증 Artifact만 chart·table·bundle 블록으로 추가한다."""

    op: Literal["add_artifact_view"]
    artifact_ref: str = Field(min_length=1, max_length=128)
    view: Literal["chart", "table", "artifact"]
    title: str = Field(min_length=1, max_length=255)
    placement: ReportAssistantPatchPlacement = Field(
        default_factory=ReportAssistantPatchPlacement
    )

    @field_validator("artifact_ref", "title")
    @classmethod
    def normalize_artifact_view_text(cls, value: str) -> str:
        """빈 Artifact 별칭과 block 제목을 적용기 진입 전에 거부한다."""

        if not value.strip():
            raise ValueError("Artifact 별칭과 block 제목은 비어 있을 수 없습니다.")
        return value.strip()


class ReportAssistantRepositionBlockOperation(ReportContractModel):
    """기존 block을 서버 계산 상대 위치로 옮기고 12열 기준 폭만 조정한다."""

    op: Literal["reposition_block"]
    block_id: str = Field(min_length=1)
    after_block_id: str | None = Field(default=None, min_length=1)
    width: Literal["half", "full"] = "full"

    @model_validator(mode="after")
    def reject_self_anchor(self) -> "ReportAssistantRepositionBlockOperation":
        """이동 대상 자신을 기준 위치로 지정한 순환 배치를 적용 전에 거부한다."""

        if self.after_block_id == self.block_id:
            raise ValueError("이동 block은 자기 자신 뒤에 배치할 수 없습니다.")
        return self


class ReportAssistantRemoveBlockOperation(ReportContractModel):
    """현재 draft의 기존 block 하나를 서버 검증 뒤 제거한다."""

    op: Literal["remove_block"]
    block_id: str = Field(min_length=1)


class ReportAssistantDuplicateBlockOperation(ReportContractModel):
    """기존 block의 내용과 lineage를 보존하고 서버 ID로 바로 뒤에 복제한다."""

    op: Literal["duplicate_block"]
    block_id: str = Field(min_length=1)


class ReportAssistantRestorePreviousRevisionOperation(ReportContractModel):
    """직전 저장 version의 스냅샷을 새 CAS revision으로 복원하도록 요청한다."""

    op: Literal["restore_previous_revision"]


ReportAssistantPatchOperation = Annotated[
    ReportAssistantSetTitleOperation
    | ReportAssistantAddTextOperation
    | ReportAssistantUpdateTextOperation
    | ReportAssistantAddArtifactViewOperation
    | ReportAssistantRepositionBlockOperation
    | ReportAssistantRemoveBlockOperation
    | ReportAssistantDuplicateBlockOperation
    | ReportAssistantRestorePreviousRevisionOperation,
    Field(discriminator="op"),
]


class ReportAssistantPatch(ReportContractModel):
    """모델의 보고서 변경 의도를 서버가 허용한 최소 연산 목록으로 제한한다."""

    summary: str = Field(min_length=1, max_length=1000)
    operations: tuple[ReportAssistantPatchOperation, ...] = Field(
        min_length=1,
        max_length=12,
    )

    @field_validator("summary")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        """사용자에게 공개할 patch 요약의 빈 값을 거부하고 공백을 정규화한다."""

        if not value.strip():
            raise ValueError("Report patch 요약은 비어 있을 수 없습니다.")
        return value.strip()

    @model_validator(mode="after")
    def isolate_revision_restore(self) -> "ReportAssistantPatch":
        """전체 snapshot 복원과 부분 변경을 한 patch에서 섞어 적용 순서가 모호해지는 것을 막는다."""

        restore_count = sum(
            operation.op == "restore_previous_revision"
            for operation in self.operations
        )
        if restore_count and (restore_count != 1 or len(self.operations) != 1):
            raise ValueError("이전 revision 복원은 단독 연산이어야 합니다.")
        return self


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
