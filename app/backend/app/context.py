from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import Header, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import AuthenticationError, authenticate_token
from app.contracts import CONTRACT_VERSION, ErrorCode, RequestContext, Role


bearer_auth = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="서버가 AUTH_PRINCIPALS_FILE의 SHA-256 digest로 검증하는 Bearer token",
)


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
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_auth)],
    as_of: Annotated[str, Header(alias="X-As-Of")],
    trace_id: Annotated[str, Header(alias="X-Trace-Id")],
    timezone: Annotated[str, Header(alias="X-Timezone")],
    contract_version: Annotated[str, Header(alias="X-Contract-Version")],
    user_id: Annotated[str | None, Header(alias="X-User-Id", include_in_schema=False)] = None,
    role: Annotated[str | None, Header(alias="X-Role", include_in_schema=False)] = None,
    access_profile: Annotated[str | None, Header(alias="X-Access-Profile")] = None,
) -> RequestContext:
    try:
        principal = authenticate_token(credentials.credentials if credentials else None)
    except AuthenticationError as exc:
        code = ErrorCode.INTERNAL_ERROR if exc.status_code == 503 else ErrorCode.ACCESS_DENIED
        raise ContextValidationError(code, exc.message, exc.status_code) from exc
    try:
        parsed_as_of = date.fromisoformat(as_of)
    except ValueError as exc:
        raise ContextValidationError(ErrorCode.CONTEXT_INCOMPLETE, "요청 Context 형식이 올바르지 않습니다.", 422) from exc
    if user_id is not None:
        try:
            if UUID(user_id) != principal.subject:
                raise ValueError
        except ValueError as exc:
            raise ContextValidationError(ErrorCode.ACCESS_DENIED, "인증 주체가 일치하지 않습니다.", 403) from exc
    if role is not None:
        try:
            if Role(role) != principal.role:
                raise ValueError
        except ValueError as exc:
            raise ContextValidationError(ErrorCode.ACCESS_DENIED, "인증 역할이 일치하지 않습니다.", 403) from exc
    if contract_version != CONTRACT_VERSION:
        raise ContextValidationError(ErrorCode.CONTRACT_VERSION_MISMATCH, "지원하지 않는 API 계약 버전입니다.", 409)
    if timezone != "Asia/Seoul" or not trace_id.strip():
        raise ContextValidationError(ErrorCode.CONTEXT_INCOMPLETE, "필수 Context 값이 올바르지 않습니다.", 422)
    profile = None
    if access_profile is not None or principal.role is Role.HOTEL_ANALYST:
        from app.access_policy import resolve_access_profile
        try:
            profile = resolve_access_profile(principal.subject, principal.role, access_profile)
        except PermissionError as exc:
            raise ContextValidationError(ErrorCode.ACCESS_DENIED, "요청한 접근 Profile을 사용할 수 없습니다.", 403) from exc
        except RuntimeError as exc:
            raise ContextValidationError(ErrorCode.INTERNAL_ERROR, "접근 정책을 확인할 수 없습니다.", 503) from exc
    context = RequestContext(
        request_id=request.state.request_id, trace_id=trace_id, user_id=principal.subject,
        role=principal.role, as_of=parsed_as_of, timezone=timezone,
        contract_version=contract_version, access_profile=profile.name if profile else None,
        database_grants=profile.database_grants if profile else (),
        allowed_domains=profile.domains if profile else (),
        access_policy_version=profile.policy_version if profile else None,
        entitlement_hash=profile.entitlement_hash if profile else None,
        trino_principal=profile.trino_principal if profile else None,
        datahub_principal=profile.datahub_principal if profile else None,
    )
    request.state.context = context
    request.state.trace_id = trace_id
    return context
