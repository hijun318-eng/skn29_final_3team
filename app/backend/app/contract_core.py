"""분석 API 전반이 공유하는 요청 문맥, 상태, 오류 분류와 검증 규칙을 정의한다."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import TypeAlias
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CONTRACT_VERSION = "OPENAPI-v1.0.0"
OPENAPI_DOCUMENT_VERSION = "OPENAPI-v1.1.0-DRAFT"
Scalar: TypeAlias = str | int | float | bool | None


class ContractModel(BaseModel):
    """알 수 없는 입력 필드를 거부해 계약 확장이나 오타가 묵시적으로 통과하지 않게 한다."""
    model_config = ConfigDict(extra="forbid")


class AnalysisStatus(str, Enum):
    """분석 요청의 수신부터 성공·차단·실패·취소까지 외부에 노출할 수명주기를 열거한다."""
    RECEIVED = "RECEIVED"
    ROUTED = "ROUTED"
    SUCCEEDED = "SUCCEEDED"
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"


class PipelineStage(str, Enum):
    """추적 로그에서 라우팅, 문맥 구성, 정책 게이트, 실행, 증거 저장 단계를 식별한다."""
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
    """각 파이프라인 단계가 통과했는지 정책상 차단됐는지 실행 실패했는지 구분한다."""
    PASSED = "PASSED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class Role(str, Enum):
    """인증 주체에게 부여할 수 있는 분석·보고서·데이터 관리 역할의 허용 집합이다."""
    ANALYST = "analyst"
    REPORT_ADMIN = "report_admin"
    DATA_ADMIN = "data_admin"
    PLATFORM_ADMIN = "platform_admin"


class Capability(str, Enum):
    """역할 이름과 분리해 API·데이터·보고서 경계가 검사할 수 있는 서비스 권한이다."""

    RUN_ANALYSIS = "analysis.run"
    READ_ANALYSIS = "analysis.read"
    DRAFT_REPORT = "report.draft"
    MANAGE_REPORT = "report.manage"
    MANAGE_DATA = "data.manage"
    MANAGE_SYSTEM = "system.manage"


class RouteType(str, Enum):
    """질문을 동적 일반 분석으로 처리할지 승인된 템플릿 정의로 처리할지 표시한다."""
    GENERAL = "GENERAL"
    TEMPLATE = "TEMPLATE"


class ErrorCode(str, Enum):
    """인증, 문맥, 모델, SQL, 쿼리, 증거, 의존성 실패를 안정적인 API 코드로 분류한다."""
    CONTEXT_INCOMPLETE = "CONTEXT_INCOMPLETE"
    CONTEXT_SOURCE_FAILED = "CONTEXT_SOURCE_FAILED"
    SEMANTIC_CONTRACT_INVALID = "SEMANTIC_CONTRACT_INVALID"
    DATA_ASSET_NOT_FOUND = "DATA_ASSET_NOT_FOUND"
    OUT_OF_DATA_RANGE = "OUT_OF_DATA_RANGE"
    SOURCE_NOT_READY = "SOURCE_NOT_READY"
    GRAIN_VIOLATION = "GRAIN_VIOLATION"
    FILTER_VALUE_NOT_FOUND = "FILTER_VALUE_NOT_FOUND"
    METRIC_NOT_AVAILABLE = "METRIC_NOT_AVAILABLE"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    ACCESS_DENIED = "ACCESS_DENIED"
    MODEL_CONTRACT_INVALID = "MODEL_CONTRACT_INVALID"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_ENDPOINT_UNAVAILABLE = "MODEL_ENDPOINT_UNAVAILABLE"
    MODEL_OUTPUT_UNGROUNDED = "MODEL_OUTPUT_UNGROUNDED"
    REPORT_ASSISTANT_MODEL_AUTHENTICATION_FAILED = "REPORT_ASSISTANT_MODEL_AUTHENTICATION_FAILED"
    REPORT_ASSISTANT_MODEL_RATE_LIMITED = "REPORT_ASSISTANT_MODEL_RATE_LIMITED"
    REPORT_ASSISTANT_MODEL_REQUEST_REJECTED = "REPORT_ASSISTANT_MODEL_REQUEST_REJECTED"
    REPORT_ASSISTANT_MODEL_TIMEOUT = "REPORT_ASSISTANT_MODEL_TIMEOUT"
    REPORT_ASSISTANT_MODEL_TRANSPORT_FAILED = "REPORT_ASSISTANT_MODEL_TRANSPORT_FAILED"
    REPORT_ASSISTANT_MODEL_CONTRACT_INVALID = "REPORT_ASSISTANT_MODEL_CONTRACT_INVALID"
    REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID = "REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID"
    EXTERNAL_TRANSFER_OUTCOME_UNKNOWN = "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN"
    REPORT_ASSISTANT_TURN_MODEL_FAILED = "REPORT_ASSISTANT_TURN_MODEL_FAILED"
    REPORT_ASSISTANT_TURN_MODEL_INVALID = "REPORT_ASSISTANT_TURN_MODEL_INVALID"
    REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED = (
        "REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED"
    )
    REPORT_ASSISTANT_PAGE_RENDER_FAILED = "REPORT_ASSISTANT_PAGE_RENDER_FAILED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    UNREPAIRABLE = "UNREPAIRABLE"
    SQL_POLICY_BLOCKED = "SQL_POLICY_BLOCKED"
    SQL_REPAIR_FAILED = "SQL_REPAIR_FAILED"
    TRINO_CONNECTION_FAILED = "TRINO_CONNECTION_FAILED"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    QUERY_SOURCE_FAILED = "QUERY_SOURCE_FAILED"
    EMPTY_RESULT = "EMPTY_RESULT"
    PRESENTATION_NOT_SUPPORTED = "PRESENTATION_NOT_SUPPORTED"
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
    LAST_ADMIN_REQUIRED = "LAST_ADMIN_REQUIRED"
    CONVERSATION_CONFLICT = "CONVERSATION_CONFLICT"
    CONVERSATION_BUSY = "CONVERSATION_BUSY"
    CONVERSATION_ARCHIVED = "CONVERSATION_ARCHIVED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    REPORT_DRAFT_CONFLICT = "REPORT_DRAFT_CONFLICT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ClarificationType(str, Enum):
    """사용자에게 추가로 확인해야 할 정보가 지표인지 조회 기간인지 지정한다."""
    METRIC = "metric"
    PERIOD = "period"


class DisambiguationOption(ContractModel):
    """모호성 해소를 위해 사용자에게 제시하는 구조화된 선택지 계약이다."""
    label: str
    clarification_type: ClarificationType
    description: str | None = None
    metric_id: str | None = None
    period_start: str | None = None
    period_end_exclusive: str | None = None
    value: str | None = None


class RequiredAction(str, Enum):
    """오류를 해소하기 위해 클라이언트가 재시도·인증·권한 요청 등 무엇을 해야 하는지 명시한다."""
    NONE = "NONE"
    RETRY = "RETRY"
    AUTHENTICATE = "AUTHENTICATE"
    REQUEST_ACCESS = "REQUEST_ACCESS"
    PROVIDE_CONTEXT = "PROVIDE_CONTEXT"
    MODIFY_REQUEST = "MODIFY_REQUEST"
    CONTACT_SUPPORT = "CONTACT_SUPPORT"
    CONTACT_ADMIN = "CONTACT_ADMIN"


class RequestContext(ContractModel):
    """요청·추적 식별자, 인증 주체, 기준일, 시간대와 계약 버전을 한 분석 실행에 고정한다."""
    request_id: UUID = Field(default_factory=uuid4)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    require_fresh_query: bool = False
    conversation_id: UUID | None = None
    user_id: UUID = UUID(int=0)
    role: Role = Role.ANALYST
    as_of: date = Field(default_factory=date.today)
    timezone: str = "Asia/Seoul"
    contract_version: str = CONTRACT_VERSION
    permission_snapshot_id: str | None = None
    product_release_id: str | None = None
    semantic_release_id: str | None = None
    command_id: UUID | None = None


class ResolvedSlots(ContractModel):
    """멀티턴 대화에서 이전 턴의 슬롯을 구조화된 형태로 상속할 때 사용한다.

    지표가 확정된 슬롯은 MetricResolver의 pre-resolved fast-path로 전달해 Node 1
    재해석을 생략하고, 지표가 비어 있는 슬롯은 직전 기간·결과 형태만 Node 1의 typed
    대화 컨텍스트로 제공한다. 두 경로 모두 active governance 대조 검증을 유지한다.
    """
    metric_id: str | None = None
    metric_ids: tuple[str, ...] = ()
    dimension_ids: tuple[str, ...] = ()
    user_filters: tuple[dict[str, str], ...] = ()
    period_start: str | None = None
    period_end_exclusive: str | None = None
    comparison_period_start: str | None = None
    comparison_period_end_exclusive: str | None = None
    analysis_operation: str | None = None
    analysis_time_bucket: str | None = None
    result_limit: int | None = None

    @model_validator(mode="after")
    def validate_analysis_shape(self) -> "ResolvedSlots":
        """단일·복수 지표 호환 필드와 연산별 LIMIT 불변식을 검증한다."""

        metrics = self.metric_ids or ((self.metric_id,) if self.metric_id else ())
        if (
            not 0 <= len(metrics) <= 4
            or len(metrics) != len(set(metrics))
            or any(not isinstance(item, str) or not item.strip() for item in metrics)
        ):
            raise ValueError("resolved metric_ids는 고유한 비어 있지 않은 ID 4개 이하여야 합니다.")
        if self.metric_id is not None and metrics != (self.metric_id,):
            raise ValueError("metric_id는 단일 metric_ids의 호환 projection이어야 합니다.")
        operations = {
            "aggregate",
            "breakdown",
            "time_trend",
            "top_n",
            "bottom_n",
            "period_comparison",
        }
        if self.analysis_operation is not None and self.analysis_operation not in operations:
            raise ValueError("analysis_operation이 지원 계약 범위를 벗어났습니다.")
        time_buckets = {"day", "week", "month", "quarter", "year"}
        if self.analysis_time_bucket is not None and self.analysis_time_bucket not in time_buckets:
            raise ValueError("analysis_time_bucket이 지원 계약 범위를 벗어났습니다.")
        if (self.analysis_operation == "time_trend") != (
            self.analysis_time_bucket is not None
        ):
            raise ValueError(
                "time_trend 연산과 analysis_time_bucket은 함께 지정해야 합니다."
            )
        comparison_values = (
            self.comparison_period_start,
            self.comparison_period_end_exclusive,
        )
        if any(comparison_values) != all(comparison_values):
            raise ValueError("비교 기간 시작일과 종료일은 함께 지정해야 합니다.")
        if all(comparison_values) != (
            self.analysis_operation == "period_comparison"
        ):
            raise ValueError(
                "period_comparison 연산과 비교 기간 슬롯은 함께 지정해야 합니다."
            )
        if self.result_limit is not None and (
            self.analysis_operation not in {"top_n", "bottom_n"}
            or isinstance(self.result_limit, bool)
            or not 1 <= self.result_limit <= 100
        ):
            raise ValueError("result_limit은 top_n·bottom_n에서만 1~100으로 지정할 수 있습니다.")
        return self

    @property
    def resolved_metric_ids(self) -> tuple[str, ...]:
        """신규 복수 필드와 기존 단일 필드를 하나의 권위 목록으로 반환한다."""

        return self.metric_ids or ((self.metric_id,) if self.metric_id else ())


class AnalysisRequest(ContractModel):
    """자연어 질문과 선택적 템플릿·스칼라 매개변수를 수신하며 빈 질문과 잘못된 기간을 거부한다."""
    question: str = Field(min_length=1, max_length=1000)
    template_id: str | None = Field(default=None, max_length=128)
    parameters: dict[str, Scalar] = Field(default_factory=dict)
    resolved_slots: ResolvedSlots | None = None

    @field_validator("question", mode="before")
    @classmethod
    def validate_question(cls, value: object) -> object:
        """문자열 질문의 양끝 공백을 제거하고 내용이 없으면 Pydantic 검증 오류를 발생시킨다."""
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("분석 질문을 입력해 주세요.")
        return value

    @model_validator(mode="after")
    def validate_period(self) -> "AnalysisRequest":
        """기간 매개변수 두 개가 함께 온 ISO 날짜이며 시작일이 종료일보다 앞서는지 검증한다."""
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
    """안정적인 오류 코드, 사용자 메시지, 보완 요구사항과 추적 식별자를 API 실패로 전달한다."""
    code: ErrorCode
    message: str
    missing_requirements: tuple[str, ...] = ()
    required_action: RequiredAction = RequiredAction.NONE
    retryable: bool = False
    suggestions: tuple[str, ...] = ()
    clarification_type: ClarificationType | None = None
    disambiguation_options: tuple[DisambiguationOption, ...] = ()
    exact_page_count: int | None = Field(
        default=None, ge=1, le=20, exclude_if=lambda value: value is None
    )
    verified_page_count: int | None = Field(
        default=None, ge=1, exclude_if=lambda value: value is None
    )
    trace_id: str = ""

    def model_post_init(self, __context: object) -> None:
        """호출자가 생략한 재시도 가능성과 후속 조치를 오류 코드의 중앙 정책에서 파생한다."""
        if "retryable" not in self.model_fields_set:
            object.__setattr__(self, "retryable", self.code in _RETRYABLE_ERROR_CODES)
        if "required_action" not in self.model_fields_set:
            object.__setattr__(
                self,
                "required_action",
                _REQUIRED_ACTION_BY_ERROR.get(self.code, RequiredAction.NONE),
            )


_RETRYABLE_ERROR_CODES = {
    ErrorCode.CONTEXT_SOURCE_FAILED,
    ErrorCode.MODEL_TIMEOUT,
    ErrorCode.MODEL_ENDPOINT_UNAVAILABLE,
    ErrorCode.REPORT_ASSISTANT_MODEL_RATE_LIMITED,
    ErrorCode.REPORT_ASSISTANT_MODEL_TIMEOUT,
    ErrorCode.REPORT_ASSISTANT_MODEL_TRANSPORT_FAILED,
    ErrorCode.REPORT_ASSISTANT_TURN_MODEL_FAILED,
    ErrorCode.REPORT_ASSISTANT_TURN_MODEL_INVALID,
    ErrorCode.REPORT_ASSISTANT_PAGE_RENDER_FAILED,
    ErrorCode.CIRCUIT_OPEN,
    ErrorCode.TRINO_CONNECTION_FAILED,
    ErrorCode.QUERY_TIMEOUT,
    ErrorCode.QUERY_SOURCE_FAILED,
    ErrorCode.ARTIFACT_PERSIST_FAILED,
    ErrorCode.PARTIAL_FAILURE,
    ErrorCode.RATE_LIMITED,
    ErrorCode.DEPENDENCY_UNAVAILABLE,
    ErrorCode.SOURCE_NOT_READY,
    ErrorCode.CONVERSATION_CONFLICT,
    ErrorCode.CONVERSATION_BUSY,
    ErrorCode.REPORT_DRAFT_CONFLICT,
}

_REQUIRED_ACTION_BY_ERROR = {
    ErrorCode.CONTEXT_SOURCE_FAILED: RequiredAction.CONTACT_SUPPORT,
    ErrorCode.SEMANTIC_CONTRACT_INVALID: RequiredAction.CONTACT_SUPPORT,
    ErrorCode.AUTHENTICATION_REQUIRED: RequiredAction.AUTHENTICATE,
    ErrorCode.ACCESS_DENIED: RequiredAction.REQUEST_ACCESS,
    ErrorCode.CONTEXT_INCOMPLETE: RequiredAction.PROVIDE_CONTEXT,
    ErrorCode.INSUFFICIENT_CONTEXT: RequiredAction.PROVIDE_CONTEXT,
    ErrorCode.DATA_ASSET_NOT_FOUND: RequiredAction.PROVIDE_CONTEXT,
    ErrorCode.OUT_OF_DATA_RANGE: RequiredAction.MODIFY_REQUEST,
    ErrorCode.GRAIN_VIOLATION: RequiredAction.MODIFY_REQUEST,
    ErrorCode.FILTER_VALUE_NOT_FOUND: RequiredAction.MODIFY_REQUEST,
    ErrorCode.METRIC_NOT_AVAILABLE: RequiredAction.MODIFY_REQUEST,
    ErrorCode.SOURCE_NOT_READY: RequiredAction.RETRY,
    ErrorCode.CONTRACT_VERSION_MISMATCH: RequiredAction.MODIFY_REQUEST,
    ErrorCode.SCHEMA_VERSION_MISMATCH: RequiredAction.MODIFY_REQUEST,
    ErrorCode.RESOURCE_NOT_FOUND: RequiredAction.MODIFY_REQUEST,
    ErrorCode.RESOURCE_CONFLICT: RequiredAction.MODIFY_REQUEST,
    ErrorCode.LAST_ADMIN_REQUIRED: RequiredAction.MODIFY_REQUEST,
    ErrorCode.CONVERSATION_CONFLICT: RequiredAction.RETRY,
    ErrorCode.CONVERSATION_BUSY: RequiredAction.RETRY,
    ErrorCode.CONVERSATION_ARCHIVED: RequiredAction.MODIFY_REQUEST,
    ErrorCode.IDEMPOTENCY_CONFLICT: RequiredAction.MODIFY_REQUEST,
    ErrorCode.REPORT_DRAFT_CONFLICT: RequiredAction.RETRY,
    ErrorCode.REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED: RequiredAction.MODIFY_REQUEST,
    ErrorCode.REPORT_ASSISTANT_PAGE_RENDER_FAILED: RequiredAction.RETRY,
    ErrorCode.SQL_POLICY_BLOCKED: RequiredAction.MODIFY_REQUEST,
    ErrorCode.MODEL_TIMEOUT: RequiredAction.RETRY,
    ErrorCode.MODEL_ENDPOINT_UNAVAILABLE: RequiredAction.RETRY,
    ErrorCode.REPORT_ASSISTANT_MODEL_AUTHENTICATION_FAILED: RequiredAction.CONTACT_ADMIN,
    ErrorCode.REPORT_ASSISTANT_MODEL_RATE_LIMITED: RequiredAction.RETRY,
    ErrorCode.REPORT_ASSISTANT_MODEL_REQUEST_REJECTED: RequiredAction.CONTACT_ADMIN,
    ErrorCode.REPORT_ASSISTANT_MODEL_TIMEOUT: RequiredAction.RETRY,
    ErrorCode.REPORT_ASSISTANT_MODEL_TRANSPORT_FAILED: RequiredAction.RETRY,
    ErrorCode.REPORT_ASSISTANT_MODEL_CONTRACT_INVALID: RequiredAction.CONTACT_ADMIN,
    ErrorCode.REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID: RequiredAction.CONTACT_ADMIN,
    ErrorCode.REPORT_ASSISTANT_TURN_MODEL_FAILED: RequiredAction.RETRY,
    ErrorCode.REPORT_ASSISTANT_TURN_MODEL_INVALID: RequiredAction.RETRY,
    ErrorCode.CIRCUIT_OPEN: RequiredAction.RETRY,
    ErrorCode.TRINO_CONNECTION_FAILED: RequiredAction.RETRY,
    ErrorCode.QUERY_TIMEOUT: RequiredAction.RETRY,
    ErrorCode.QUERY_SOURCE_FAILED: RequiredAction.RETRY,
    ErrorCode.EMPTY_RESULT: RequiredAction.MODIFY_REQUEST,
    ErrorCode.ARTIFACT_PERSIST_FAILED: RequiredAction.RETRY,
    ErrorCode.PARTIAL_FAILURE: RequiredAction.RETRY,
    ErrorCode.RATE_LIMITED: RequiredAction.RETRY,
    ErrorCode.DEPENDENCY_UNAVAILABLE: RequiredAction.RETRY,
    ErrorCode.INTERNAL_ERROR: RequiredAction.CONTACT_SUPPORT,
}
