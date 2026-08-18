"""동적 거버넌스 레코드, 릴리스와 요청별 문맥 패키지의 API 계약을 정의한다."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


CONTEXT_REGISTRY_VERSION = "CONTEXT-REGISTRY-v1.0.0-DRAFT"


class ContextRecordType(str, Enum):
    """자산·지표·시간·이력·조인·용어·열 정책 레코드가 담당하는 의미 범주를 구분한다."""
    ASSET_BINDING = "ASSET_BINDING"
    METRIC_DEFINITION = "METRIC_DEFINITION"
    TIME_POLICY = "TIME_POLICY"
    DIMENSION_HISTORY_POLICY = "DIMENSION_HISTORY_POLICY"
    JOIN_POLICY = "JOIN_POLICY"
    TERM_ALIAS = "TERM_ALIAS"
    COLUMN_POLICY_REF = "COLUMN_POLICY_REF"


class ContextRecordStatus(str, Enum):
    """거버넌스 레코드가 초안, 승인, 폐기 중 어느 수명주기에 있는지 표시한다."""
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    DEPRECATED = "DEPRECATED"


class ContextReleaseStatus(str, Enum):
    """문맥 릴리스의 편집, 게시, 퇴역 상태를 구분해 런타임 선택 가능 여부를 표현한다."""
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class RegistryModel(BaseModel):
    """레지스트리 요청과 응답에서 미선언 필드를 거부하는 fail-closed Pydantic 기반 모델이다."""
    model_config = ConfigDict(extra="forbid")


class CreateContextRecord(RegistryModel):
    """버전 있는 거버넌스 레코드의 유형·키·유효기간·소유 역할·멱등 키와 구조화 payload를 받는다."""
    record_type: ContextRecordType
    record_key: str = Field(min_length=1, max_length=160)
    version_no: int = Field(ge=1)
    payload: dict[str, Any]
    owner_role: str = Field(min_length=1, max_length=64)
    valid_from: datetime
    valid_to: datetime | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("record_key", "owner_role", "idempotency_key")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        """레코드 키, 소유 역할, 멱등 키를 정규화하고 공백 값은 영속 계층 진입 전에 거부한다."""
        value = value.strip()
        if not value:
            raise ValueError("값은 비어 있을 수 없습니다.")
        return value


class ContextRecord(RegistryModel):
    """저장된 거버넌스 레코드의 ID, 승인 정보, 유효기간, checksum과 멱등성을 반환한다."""
    context_record_id: UUID
    record_type: ContextRecordType
    record_key: str
    version_no: int
    payload: dict[str, Any]
    status: ContextRecordStatus
    owner_role: str
    approved_by: UUID | None
    approved_at: datetime | None
    valid_from: datetime
    valid_to: datetime | None
    checksum: str
    idempotency_key: str

    @classmethod
    def from_row(cls, row: Any) -> "ContextRecord":
        """DB 행의 JSON·승인·유효기간 열을 타입 검증된 문맥 레코드 응답으로 변환한다."""
        return cls(
            context_record_id=row["context_record_id"],
            record_type=row["record_type"],
            record_key=row["record_key"],
            version_no=row["version_no"],
            payload=row["payload_json"],
            status=row["status"],
            owner_role=row["owner_role"],
            approved_by=row["approved_by"],
            approved_at=row["approved_at"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            checksum=row["checksum"],
            idempotency_key=row["idempotency_key"],
        )


class RecordReference(RegistryModel):
    """릴리스에 포함할 레코드 ID와 정확히 64자리 SHA-256 checksum을 한 쌍으로 고정한다."""
    context_record_id: UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class CreateContextRelease(RegistryModel):
    """하나 이상의 checksum 고정 레코드로 새 문맥 릴리스를 만들고 선택적 롤백 대상을 지정한다."""
    release_key: str = Field(min_length=1, max_length=128)
    version_no: int = Field(ge=1)
    included_records: list[RecordReference] = Field(min_length=1)
    rollback_release_id: UUID | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("release_key", "idempotency_key")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        """릴리스 키와 멱등 키의 공백을 제거하고 빈 식별자가 저장되는 것을 차단한다."""
        value = value.strip()
        if not value:
            raise ValueError("값은 비어 있을 수 없습니다.")
        return value

    @field_validator("included_records")
    @classmethod
    def reject_duplicate_records(
        cls, value: list[RecordReference]
    ) -> list[RecordReference]:
        """같은 레코드 ID가 한 릴리스에 두 번 포함되어 해시 의미가 모호해지는 것을 거부한다."""
        identifiers = [item.context_record_id for item in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("release에는 같은 record를 중복 포함할 수 없습니다.")
        return value


class ContextRelease(RegistryModel):
    """게시 상태, 구성 레코드 checksum, 전체 릴리스 해시와 게시·롤백 계보를 반환한다."""
    context_release_id: UUID
    release_key: str
    version_no: int
    included_records: list[RecordReference]
    status: ContextReleaseStatus
    release_hash: str
    published_by: UUID | None
    published_at: datetime | None
    rollback_release_id: UUID | None
    idempotency_key: str

    @classmethod
    def from_row(cls, row: Any) -> "ContextRelease":
        """DB의 레코드 참조 JSON과 게시 메타데이터를 검증된 문맥 릴리스 응답으로 변환한다."""
        return cls(
            context_release_id=row["context_release_id"],
            release_key=row["release_key"],
            version_no=row["version_no"],
            included_records=row["included_record_refs_json"],
            status=row["status"],
            release_hash=row["release_hash"],
            published_by=row["published_by"],
            published_at=row["published_at"],
            rollback_release_id=row["rollback_release_id"],
            idempotency_key=row["idempotency_key"],
        )


class CreateContextPackage(RegistryModel):
    """요청·릴리스·사용자 범위와 동적 자산·지표·조인·정책을 크기 제한 안에서 패키징한다."""
    request_id: UUID
    context_release_id: UUID
    user_scope: dict[str, Any]
    assets: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    joins: list[dict[str, Any]]
    policies: list[dict[str, Any]]
    dataset_count: int = Field(ge=0, le=8)
    column_count: int = Field(ge=0, le=60)
    token_count: int = Field(ge=0, le=6000)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        """문맥 패키지 멱등 키의 공백을 제거하고 빈 키로 중복 생성되는 상황을 차단한다."""
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key는 비어 있을 수 없습니다.")
        return value


class ContextPackage(RegistryModel):
    """요청 시점의 사용자 범위와 승인 자산·지표·조인·정책을 불변 해시 및 생성 시각과 반환한다."""
    context_package_id: UUID
    request_id: UUID
    context_release_id: UUID
    user_scope: dict[str, Any]
    assets: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    joins: list[dict[str, Any]]
    policies: list[dict[str, Any]]
    dataset_count: int
    column_count: int
    token_count: int
    package_hash: str
    idempotency_key: str
    created_at: datetime

    @classmethod
    def from_row(cls, row: Any) -> "ContextPackage":
        """DB JSON 열과 크기 계수를 Pydantic 검증을 거친 문맥 패키지 응답으로 복원한다."""
        return cls(
            context_package_id=row["context_package_id"],
            request_id=row["request_id"],
            context_release_id=row["context_release_id"],
            user_scope=row["user_scope_json"],
            assets=row["assets_json"],
            metrics=row["metrics_json"],
            joins=row["joins_json"],
            policies=row["policies_json"],
            dataset_count=row["dataset_count"],
            column_count=row["column_count"],
            token_count=row["token_count"],
            package_hash=row["package_hash"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
        )
