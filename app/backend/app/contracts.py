from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


CONTRACT_VERSION = "DRAFT-OPENAPI-v0.1"


class AnalysisStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ROUTED = "ROUTED"
    SUCCEEDED = "SUCCEEDED"
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
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
    INTERNAL_ERROR = "INTERNAL_ERROR"


class RequestContext(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    conversation_id: UUID | None = None
    user_id: UUID = UUID(int=0)
    role: Role = Role.HOTEL_ANALYST
    as_of: date = Field(default_factory=date.today)
    timezone: str = "Asia/Seoul"
    contract_version: str = CONTRACT_VERSION


class AnalysisRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    template_id: str | None = Field(default=None, max_length=128)
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool = False


class ResponseMeta(BaseModel):
    request_id: UUID
    trace_id: str
    as_of: date
    contract_version: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApiResponse(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    meta: ResponseMeta
    error: ErrorBody | None = None


def response_meta(context: RequestContext) -> ResponseMeta:
    return ResponseMeta(
        request_id=context.request_id,
        trace_id=context.trace_id,
        as_of=context.as_of,
        contract_version=context.contract_version,
    )
