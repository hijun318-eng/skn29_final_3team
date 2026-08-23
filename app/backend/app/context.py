"""HTTP 자격 증명과 server-owned 시간·trace·계약 version을 권한 있는 RequestContext로 조립한다."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime
import os
import re
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, Header, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticationError, authenticate_token
from app.auth_principal_store import Principal
from app.contracts import CONTRACT_VERSION, ErrorCode, RequestContext, Role
from app.database import get_database_session


bearer_auth = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="서버가 AUTH_PRINCIPALS_FILE의 SHA-256 digest로 검증하는 Bearer token",
)
SESSION_COOKIE = "answervice_session"
_TRACE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_KST = ZoneInfo("Asia/Seoul")
_PHASE10_ACCEPTANCE_MODE = "phase10-p0-gold"
DatabaseSession = Annotated[AsyncSession, Depends(get_database_session)]
TokenAuthenticator = Callable[[str | None], Awaitable[Principal]]


def token_authenticator() -> TokenAuthenticator:
    """HTTP 인증 경계가 사용할 운영 token 검증 함수를 dependency로 제공한다."""
    return authenticate_token


def valid_trace_id(value: str | None) -> bool:
    """외부 trace ID가 허용 문자와 1~64자 길이 계약을 정확히 만족하는지 확인한다."""
    return bool(value and _TRACE_ID.fullmatch(value))


def _server_kst_date() -> date:
    """서버 기준일을 반환하되 격리 Phase 10 평가의 봉인 기준일만 허용한다.

    일반 실행은 항상 KST 시계를 사용한다. Candidate Compose가 정확한 acceptance mode와
    봉인 Gold에서 읽은 날짜를 함께 제공한 경우에만 재현 가능한 평가 시계를 사용하며,
    한쪽만 설정되거나 날짜가 잘못되면 실제 시각으로 조용히 fallback하지 않는다.
    """

    mode = os.getenv("ANSWERVICE_ACCEPTANCE_MODE")
    configured_as_of = os.getenv("ANSWERVICE_ACCEPTANCE_AS_OF")
    if mode is None and configured_as_of is None:
        return datetime.now(_KST).date()
    if mode != _PHASE10_ACCEPTANCE_MODE or not configured_as_of:
        raise ContextValidationError(
            ErrorCode.CONTEXT_INCOMPLETE,
            "격리 Acceptance 기준일 설정이 완전하지 않습니다.",
            500,
        )
    try:
        return date.fromisoformat(configured_as_of)
    except ValueError as error:
        raise ContextValidationError(
            ErrorCode.CONTEXT_INCOMPLETE,
            "격리 Acceptance 기준일 형식이 올바르지 않습니다.",
            500,
        ) from error


def _request_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    return credentials.credentials if credentials else request.cookies.get(SESSION_COOKIE)


class ContextValidationError(ValueError):
    """인증·권한·header·계약 version 위반을 공개 error code와 HTTP 상태로 전달한다."""
    def __init__(self, code: ErrorCode, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def request_context(request: Request) -> RequestContext:
    """middleware가 확정한 Context를 읽고, 인증 전 요청에는 request/trace 식별자만 채운다."""
    return getattr(request.state, "context", RequestContext(request_id=request.state.request_id, trace_id=request.state.trace_id))


async def session_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_auth)],
    authenticator: Annotated[TokenAuthenticator, Depends(token_authenticator)],
) -> RequestContext:
    """Bearer 또는 cookie token을 서버 인증기에 맡겨 권한 Context를 생성한다.

    client header의 role이나 subject를 신뢰하지 않으며, 검증된 주체와 원문 token 참조만
    request state에 보존한다. 인증 저장소 장애와 자격 증명 오류는 서로 다른 typed code다.
    """
    if getattr(request.state, "trace_id_invalid", False):
        raise ContextValidationError(
            ErrorCode.CONTEXT_INCOMPLETE,
            "X-Trace-Id 형식이 올바르지 않습니다.",
            422,
        )
    token = _request_token(request, credentials)
    try:
        principal = await authenticator(token)
    except AuthenticationError as exc:
        code = ErrorCode.DEPENDENCY_UNAVAILABLE if exc.status_code == 503 else ErrorCode.AUTHENTICATION_REQUIRED
        raise ContextValidationError(code, exc.message, exc.status_code) from exc
    context = RequestContext(
        request_id=request.state.request_id,
        trace_id=request.state.trace_id,
        user_id=principal.subject,
        role=principal.role,
        as_of=_server_kst_date(),
    )
    request.state.context = context
    request.state.session_token = token
    return context


async def optional_session_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_auth)],
    authenticator: Annotated[TokenAuthenticator, Depends(token_authenticator)],
) -> RequestContext | None:
    """자격 증명이 전혀 없을 때만 ``None``을 반환하고, 제공된 token은 반드시 완전 검증한다."""
    if _request_token(request, credentials) is None:
        return None
    return await session_context(request, credentials, authenticator)


async def analysis_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_auth)],
    trace_id: Annotated[str, Header(alias="X-Trace-Id")],
    timezone: Annotated[str, Header(alias="X-Timezone")],
    contract_version: Annotated[str, Header(alias="X-Contract-Version")],
    authenticator: Annotated[TokenAuthenticator, Depends(token_authenticator)],
    user_id: Annotated[str | None, Header(alias="X-User-Id", include_in_schema=False)] = None,
    role: Annotated[str | None, Header(alias="X-Role", include_in_schema=False)] = None,
) -> RequestContext:
    """분석 요청의 인증 주체와 계약 version·timezone·trace 경계를 함께 검증한다.

    호환용 ``X-User-Id``와 ``X-Role``이 전달돼도 인증 결과와 다르면 spoofing으로 거부하며,
    기준일은 질문이나 client가 아니라 서버의 Asia/Seoul 시계에서 정한다.
    """
    try:
        principal = await authenticator(_request_token(request, credentials))
    except AuthenticationError as exc:
        code = ErrorCode.DEPENDENCY_UNAVAILABLE if exc.status_code == 503 else ErrorCode.AUTHENTICATION_REQUIRED
        raise ContextValidationError(code, exc.message, exc.status_code) from exc
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
    if timezone != "Asia/Seoul" or not valid_trace_id(trace_id):
        raise ContextValidationError(ErrorCode.CONTEXT_INCOMPLETE, "필수 Context 값이 올바르지 않습니다.", 422)
    context = RequestContext(request_id=request.state.request_id, trace_id=trace_id, user_id=principal.subject, role=principal.role, as_of=_server_kst_date(), timezone=timezone, contract_version=contract_version)
    request.state.context = context
    request.state.trace_id = trace_id
    return context
