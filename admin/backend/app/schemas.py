from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AdminRole(StrEnum):
    ADMIN = "ADMIN"
    VIEWER = "VIEWER"


def _email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 255 or "@" not in normalized or normalized.startswith("@"):
        raise ValueError("유효한 이메일을 입력하세요.")
    return normalized


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    password: str = Field(min_length=8, max_length=128)

    _normalize_email = field_validator("email")(_email)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    email: str
    password: str = Field(min_length=12, max_length=128)
    role: AdminRole
    is_active: bool = True

    _normalize_email = field_validator("email")(_email)


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = None
    password: str | None = Field(default=None, min_length=12, max_length=128)
    role: AdminRole | None = None
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return _email(value) if value is not None else None

    @model_validator(mode="after")
    def require_change(self) -> "UserPatch":
        if not self.model_fields_set:
            raise ValueError("변경할 값을 입력하세요.")
        return self


class UserOut(BaseModel):
    id: UUID
    name: str
    email: str
    role: AdminRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ConnectionOut(BaseModel):
    key: str
    name: str
    type: str
    status: str
    latency_ms: int | None


class ConnectionList(BaseModel):
    checked_at: datetime
    items: list[ConnectionOut]


class AuditEventOut(BaseModel):
    id: int
    occurred_at: datetime
    actor_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    result: str
    detail: dict[str, Any]
    request_id: str | None


class AuditPage(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    items: list[AuditEventOut]
