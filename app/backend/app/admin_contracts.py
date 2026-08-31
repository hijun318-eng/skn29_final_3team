"""관리자 계정·연결 상태·감사 로그 API의 공개 입력과 응답 계약을 정의한다."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypeAlias
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator

from app.contracts import ResponseContractModel, ResponseMeta, Role
from app.contract_core import ContractModel


AssignableAccountRole: TypeAlias = Literal[
    Role.ANALYST,
    Role.PLATFORM_ADMIN,
]
ASSIGNABLE_ACCOUNT_ROLES: tuple[Role, ...] = (
    Role.ANALYST,
    Role.PLATFORM_ADMIN,
)


def require_assignable_account_role(role: Role) -> Role:
    """계정 writer가 분석 사용자·관리자 외 인증 Role을 새로 저장하지 못하게 한다."""

    if role not in ASSIGNABLE_ACCOUNT_ROLES:
        raise ValueError("계정 역할은 analyst 또는 platform_admin이어야 합니다.")
    return role


class CreateAccountRequest(ContractModel):
    """login ID, 초기 비밀번호와 분석 사용자·관리자 Role만 계정 생성에 허용한다."""

    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9._-]+$")
    password: SecretStr = Field(min_length=12, max_length=128)
    role: AssignableAccountRole = Role.ANALYST

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        """문자열 login ID의 공백과 대소문자를 저장 전 canonical 형태로 바꾼다."""

        return value.strip().lower() if isinstance(value, str) else value


class UpdateAccountRequest(ContractModel):
    """username·Role·활성 상태 중 명시적으로 전달된 필드만 변경한다."""

    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9._-]+$",
    )
    role: AssignableAccountRole | None = None
    active: bool | None = None

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        """선택적 login ID도 생성 계약과 같은 canonical 형태로 바꾼다."""

        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_change(self) -> "UpdateAccountRequest":
        """빈 PATCH가 성공처럼 기록되지 않도록 변경 필드를 하나 이상 요구한다."""

        if not self.model_fields_set or any(
            getattr(self, field_name) is None for field_name in self.model_fields_set
        ):
            raise ValueError("변경할 계정 필드가 필요합니다.")
        return self


class ResetPasswordRequest(ContractModel):
    """관리자가 지정 계정에 발급할 새 비밀번호를 길이 제한과 함께 수신한다."""

    password: SecretStr = Field(min_length=12, max_length=128)


class AccountData(ContractModel):
    """verifier와 세션 정보 없이 관리자 화면에 공개할 계정 상태를 표현한다."""

    subject: UUID
    username: str
    role: Role
    active: bool
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None = None
    deleted_at: datetime | None = None


class AccountListData(ContractModel):
    """계정 목록과 1-based pagination 위치 및 전체 건수를 함께 반환한다."""

    items: tuple[AccountData, ...]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class AccountResponse(ResponseContractModel):
    """단일 계정 변경 결과를 공통 추적 메타데이터와 함께 반환한다."""

    data: AccountData
    meta: ResponseMeta
    error: None = None


class AccountListResponse(ResponseContractModel):
    """계정 목록 결과를 공통 추적 메타데이터와 함께 반환한다."""

    data: AccountListData
    meta: ResponseMeta
    error: None = None


class ConnectionData(ContractModel):
    """승인된 고정 dependency의 공개 이름·상태·지연시간만 노출한다."""

    id: str
    name: str
    kind: str
    status: Literal["ready", "down"]
    latency_ms: int = Field(ge=0)
    checked_at: datetime


class ConnectionListData(ContractModel):
    """한 번의 관리자 점검에서 확인한 고정 dependency 상태 목록을 담는다."""

    items: tuple[ConnectionData, ...]


class ConnectionListResponse(ResponseContractModel):
    """연결 상태 목록을 공통 추적 메타데이터와 함께 반환한다."""

    data: ConnectionListData
    meta: ResponseMeta
    error: None = None


class AuditEventData(ContractModel):
    """append-only 감사 이벤트에서 자격 증명을 제외한 관리 조회 필드만 투영한다."""

    event_id: UUID
    occurred_at: datetime
    actor_subject: UUID | None
    action_code: str
    target_type: str
    target_id: str
    result: str
    details: dict[str, Any]


class AuditEventListData(ContractModel):
    """감사 이벤트 목록과 1-based pagination 위치 및 전체 건수를 반환한다."""

    items: tuple[AuditEventData, ...]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class AuditEventListResponse(ResponseContractModel):
    """감사 이벤트 목록을 공통 추적 메타데이터와 함께 반환한다."""

    data: AuditEventListData
    meta: ResponseMeta
    error: None = None


AuditOutcome = Literal[
    "SUCCEEDED",
    "FAILED",
    "DENIED",
    "CANCELLED",
    "IN_PROGRESS",
    "CLARIFICATION_REQUIRED",
    "UNKNOWN",
]


class AuditActorData(ContractModel):
    """계정 verifier나 세션 없이 감사 수행자의 공개 식별 정보만 표현한다."""

    subject: UUID | None
    display_name: str
    role: str


class AuditObjectData(ContractModel):
    """감사 이벤트가 직접 다룬 객체의 종류와 불변 식별자를 표현한다."""

    type: str
    id: str


class AuditCorrelationData(ContractModel):
    """여러 append-only 이벤트를 하나의 작업 이력으로 묶은 서버 기준을 표현한다."""

    type: str
    id: str


class AuditEvidenceData(ContractModel):
    """감사 이벤트와 실행·정책·산출물을 연결하는 비밀정보 없는 식별자를 표현한다."""

    request_id: UUID | None
    trace_id: str | None
    query_execution_id: UUID | None
    query_id: str | None
    artifact_id: UUID | None
    report_run_id: UUID | None
    context_release_id: UUID | None
    model_version_id: UUID | None
    sql_policy_version: str | None


class AuditTrailSummaryData(ContractModel):
    """최신순 감사 trail 목록에서 선택에 필요한 요약 필드만 표현한다."""

    trail_id: str
    headline: str
    started_at: datetime
    ended_at: datetime | None
    outcome: AuditOutcome
    event_count: int = Field(ge=1)
    actor: AuditActorData
    primary_object: AuditObjectData
    correlation: AuditCorrelationData


class AuditTrailPageData(ContractModel):
    """감사 trail 요약과 다음 keyset 위치를 나타내는 불투명 cursor를 반환한다."""

    items: tuple[AuditTrailSummaryData, ...]
    next_cursor: str | None


class AuditTrailPageResponse(ResponseContractModel):
    """감사 trail 목록을 공통 요청 추적 메타데이터와 함께 반환한다."""

    data: AuditTrailPageData
    meta: ResponseMeta
    error: None = None


class AuditTrailEventData(ContractModel):
    """단일 trail 안의 순서와 redacted 기술 근거가 검증된 이벤트를 표현한다."""

    event_id: UUID
    occurred_at: datetime
    sequence: int = Field(ge=0)
    action_code: str
    action_label: str
    summary: str
    outcome: AuditOutcome
    actor: AuditActorData
    object: AuditObjectData
    evidence: AuditEvidenceData
    details_redacted: dict[str, Any]


class AuditTrailDetailData(ContractModel):
    """선택한 trail의 시간 범위와 발생 순서대로 정렬된 이벤트를 반환한다."""

    trail_id: str
    headline: str
    started_at: datetime
    ended_at: datetime | None
    outcome: AuditOutcome
    events: tuple[AuditTrailEventData, ...]


class AuditTrailDetailResponse(ResponseContractModel):
    """단일 감사 trail 상세를 공통 요청 추적 메타데이터와 함께 반환한다."""

    data: AuditTrailDetailData
    meta: ResponseMeta
    error: None = None
