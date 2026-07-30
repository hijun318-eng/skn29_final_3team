from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import Header, Request

from app.contracts import CONTRACT_VERSION, ErrorCode, RequestContext, Role


class ContextValidationError(ValueError):
    def __init__(self, code: ErrorCode, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def request_context(request: Request) -> RequestContext:
    return getattr(request.state, "context", RequestContext(request_id=request.state.request_id, trace_id=request.state.trace_id))


def analysis_context(
    request: Request,
    authorization: Annotated[str, Header()],
    user_id: Annotated[str, Header(alias="X-User-Id")],
    role: Annotated[str, Header(alias="X-Role")],
    as_of: Annotated[str, Header(alias="X-As-Of")],
    trace_id: Annotated[str, Header(alias="X-Trace-Id")],
    timezone: Annotated[str, Header(alias="X-Timezone")],
    contract_version: Annotated[str, Header(alias="X-Contract-Version")],
) -> RequestContext:
    if not authorization.startswith("Bearer ") or not authorization[7:].strip():
        raise ContextValidationError(ErrorCode.ACCESS_DENIED, "Bearer 인증 정보가 필요합니다.", 401)
    try:
        parsed_user_id = UUID(user_id)
        parsed_as_of = date.fromisoformat(as_of)
    except ValueError as exc:
        raise ContextValidationError(ErrorCode.CONTEXT_INCOMPLETE, "요청 Context 형식이 올바르지 않습니다.", 422) from exc
    try:
        parsed_role = Role(role)
    except ValueError as exc:
        raise ContextValidationError(ErrorCode.ACCESS_DENIED, "허용되지 않은 역할입니다.", 403) from exc
    if contract_version != CONTRACT_VERSION:
        raise ContextValidationError(ErrorCode.CONTRACT_VERSION_MISMATCH, "지원하지 않는 API 계약 버전입니다.", 409)
    if timezone != "Asia/Seoul" or not trace_id.strip():
        raise ContextValidationError(ErrorCode.CONTEXT_INCOMPLETE, "필수 Context 값이 올바르지 않습니다.", 422)
    context = RequestContext(request_id=request.state.request_id, trace_id=trace_id, user_id=parsed_user_id, role=parsed_role, as_of=parsed_as_of, timezone=timezone, contract_version=contract_version)
    request.state.context = context
    request.state.trace_id = trace_id
    return context
