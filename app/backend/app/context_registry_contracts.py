from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


CONTEXT_REGISTRY_VERSION = "CONTEXT-REGISTRY-v1.0.0-DRAFT"


class ContextRecordType(str, Enum):
    ASSET_BINDING = "ASSET_BINDING"
    METRIC_DEFINITION = "METRIC_DEFINITION"
    TIME_POLICY = "TIME_POLICY"
    DIMENSION_HISTORY_POLICY = "DIMENSION_HISTORY_POLICY"
    JOIN_POLICY = "JOIN_POLICY"
    TERM_ALIAS = "TERM_ALIAS"
    COLUMN_POLICY_REF = "COLUMN_POLICY_REF"


class ContextRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    DEPRECATED = "DEPRECATED"


class ContextReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateContextRecord(RegistryModel):
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
        value = value.strip()
        if not value:
            raise ValueError("값은 비어 있을 수 없습니다.")
        return value


class ContextRecord(RegistryModel):
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
    context_record_id: UUID
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class CreateContextRelease(RegistryModel):
    release_key: str = Field(min_length=1, max_length=128)
    version_no: int = Field(ge=1)
    included_records: list[RecordReference] = Field(min_length=1)
    rollback_release_id: UUID | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("release_key", "idempotency_key")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("값은 비어 있을 수 없습니다.")
        return value

    @field_validator("included_records")
    @classmethod
    def reject_duplicate_records(
        cls, value: list[RecordReference]
    ) -> list[RecordReference]:
        identifiers = [item.context_record_id for item in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("release에는 같은 record를 중복 포함할 수 없습니다.")
        return value


class ContextRelease(RegistryModel):
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
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key는 비어 있을 수 없습니다.")
        return value


class ContextPackage(RegistryModel):
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
