"""동일 사용자 세션으로 보호되는 관리자 계정·연결·감사 HTTP API를 등록한다."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.admin_account_repository import (
    AdminAccountConflict,
    AdminAccountNotFound,
    AdminAccountRepository,
    LastActiveAdminConflict,
)
from app.admin_contracts import (
    AccountData,
    AccountListData,
    AccountListResponse,
    AccountResponse,
    AuditEventData,
    AuditEventListData,
    AuditEventListResponse,
    ConnectionData,
    ConnectionListData,
    ConnectionListResponse,
    CreateAccountRequest,
    ResetPasswordRequest,
    UpdateAccountRequest,
)
from app.authorization import has_capability
from app.context import ContextValidationError, session_context
from app.contracts import Capability, ErrorCode, RequestContext, response_meta
from app.database import get_database_session
from app.services.admin_connections import probe_admin_connections


admin_router = APIRouter(prefix="/admin", tags=["admin"])


def system_manage_context(
    context: Annotated[RequestContext, Depends(session_context)],
) -> RequestContext:
    """모든 관리자 HTTP 작업을 서버의 ``system.manage`` Capability로 강제한다."""

    if not has_capability(context.role, Capability.MANAGE_SYSTEM):
        raise HTTPException(status_code=403, detail="시스템 관리 권한이 필요합니다.")
    return context


def _account_http_error(error: Exception) -> HTTPException | ContextValidationError:
    """repository의 공개 가능한 계정 오류를 안정적인 HTTP 상태로 변환한다."""

    if isinstance(error, AdminAccountNotFound):
        return HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    if isinstance(error, LastActiveAdminConflict):
        return ContextValidationError(
            ErrorCode.LAST_ADMIN_REQUIRED,
            "마지막 활성 관리자는 변경하거나 삭제할 수 없습니다.",
            409,
        )
    if isinstance(error, AdminAccountConflict):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=503, detail="계정 저장소를 사용할 수 없습니다.")


@admin_router.get(
    "/accounts",
    response_model=AccountListResponse,
    operation_id="listAdminAccounts",
)
async def list_accounts(
    context: Annotated[RequestContext, Depends(system_manage_context)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    search: Annotated[str, Query(max_length=128)] = "",
) -> AccountListResponse:
    """삭제되지 않은 analyst/admin 계정을 login ID로 검색해 페이지 단위로 반환한다."""

    try:
        rows, total = await AdminAccountRepository(session).list_accounts(
            page=page, page_size=page_size, search=search
        )
    except SQLAlchemyError as error:
        raise _account_http_error(error) from error
    return AccountListResponse(
        data=AccountListData(
            items=tuple(AccountData.model_validate(row) for row in rows),
            page=page,
            page_size=page_size,
            total=total,
        ),
        meta=response_meta(context),
    )


@admin_router.post(
    "/accounts",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createAdminAccount",
)
async def create_account(
    payload: CreateAccountRequest,
    context: Annotated[RequestContext, Depends(system_manage_context)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> AccountResponse:
    """analyst/admin 계정을 생성하고 verifier 원문 없이 단일 계정 상태만 반환한다."""

    try:
        account = await AdminAccountRepository(session).create_account(
            username=payload.username,
            password=payload.password.get_secret_value(),
            role=payload.role,
            actor=context,
        )
    except (AdminAccountConflict, SQLAlchemyError) as error:
        raise _account_http_error(error) from error
    return AccountResponse(
        data=AccountData.model_validate(account), meta=response_meta(context)
    )


@admin_router.patch(
    "/accounts/{subject}",
    response_model=AccountResponse,
    operation_id="updateAdminAccount",
)
async def update_account(
    subject: UUID,
    payload: UpdateAccountRequest,
    context: Annotated[RequestContext, Depends(system_manage_context)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> AccountResponse:
    """username·Role·활성 상태를 변경하고 권한 변경 session을 즉시 폐기한다."""

    try:
        account = await AdminAccountRepository(session).update_account(
            subject,
            changes=payload.model_dump(exclude_unset=True),
            actor=context,
        )
    except (AdminAccountNotFound, AdminAccountConflict, SQLAlchemyError) as error:
        raise _account_http_error(error) from error
    return AccountResponse(
        data=AccountData.model_validate(account), meta=response_meta(context)
    )


@admin_router.post(
    "/accounts/{subject}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="resetAdminAccountPassword",
)
async def reset_account_password(
    subject: UUID,
    payload: ResetPasswordRequest,
    context: Annotated[RequestContext, Depends(system_manage_context)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> Response:
    """새 PBKDF2 verifier로 비밀번호를 교체하고 대상의 모든 기존 session을 폐기한다."""

    try:
        await AdminAccountRepository(session).reset_password(
            subject,
            password=payload.password.get_secret_value(),
            actor=context,
        )
    except (AdminAccountNotFound, SQLAlchemyError) as error:
        raise _account_http_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.delete(
    "/accounts/{subject}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteAdminAccount",
)
async def delete_account(
    subject: UUID,
    context: Annotated[RequestContext, Depends(system_manage_context)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> Response:
    """마지막 활성 관리자 보호 후 계정을 soft-delete하고 모든 session을 폐기한다."""

    try:
        await AdminAccountRepository(session).delete_account(subject, actor=context)
    except (AdminAccountNotFound, AdminAccountConflict, SQLAlchemyError) as error:
        raise _account_http_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get(
    "/connections",
    response_model=ConnectionListResponse,
    operation_id="listAdminConnections",
)
async def list_connections(
    context: Annotated[RequestContext, Depends(system_manage_context)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> ConnectionListResponse:
    """서버 고정 dependency를 실제로 probe하고 URL 없는 결과를 감사한 뒤 반환한다."""

    rows = await probe_admin_connections()
    try:
        await AdminAccountRepository(session).record_connection_check(
            actor=context,
            connections=rows,
        )
    except SQLAlchemyError as error:
        raise _account_http_error(error) from error
    return ConnectionListResponse(
        data=ConnectionListData(
            items=tuple(ConnectionData.model_validate(row) for row in rows)
        ),
        meta=response_meta(context),
    )


@admin_router.get(
    "/audit-events",
    response_model=AuditEventListResponse,
    operation_id="listAdminAuditEvents",
)
async def list_audit_events(
    context: Annotated[RequestContext, Depends(system_manage_context)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    search: Annotated[str, Query(max_length=128)] = "",
    result: Annotated[
        str,
        Query(pattern=r"^(|SUCCESS|SUCCEEDED|FAILED|DENIED|UNKNOWN)$"),
    ] = "",
) -> AuditEventListResponse:
    """append-only 감사 로그를 action·대상·actor·결과로 검색해 최신순 반환한다."""

    try:
        rows, total = await AdminAccountRepository(session).list_audit_events(
            page=page,
            page_size=page_size,
            search=search,
            result_filter=result,
        )
    except SQLAlchemyError as error:
        raise _account_http_error(error) from error
    return AuditEventListResponse(
        data=AuditEventListData(
            items=tuple(AuditEventData.model_validate(row) for row in rows),
            page=page,
            page_size=page_size,
            total=total,
        ),
        meta=response_meta(context),
    )
