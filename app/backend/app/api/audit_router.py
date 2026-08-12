from __future__ import annotations

import os
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.audit_contracts import (
    AuditSearchResponse,
    AuditTraceResponse,
    EffectiveAccessResponse,
)
from app.context import analysis_context
from app.contracts import RequestContext


audit_router = APIRouter(prefix="/operations/audit", tags=["operations-audit"])


@audit_router.get(
    "/access", operation_id="auditGetEffectiveAccess", response_model=EffectiveAccessResponse
)
def get_effective_access(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, str]:
    from app.access_policy import effective_access

    try:
        return effective_access(context.user_id, context.role)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail="접근 정책을 확인할 수 없습니다.") from error


def _repository(context: RequestContext):
    from app.adapters.audit_repository import PostgresAuditRepository

    database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="감사 저장소를 사용할 수 없습니다.")
    return PostgresAuditRepository(database_url, context.user_id)


@audit_router.get("", operation_id="auditSearchRequests", response_model=AuditSearchResponse)
def search_audit_requests(
    context: Annotated[RequestContext, Depends(analysis_context)],
    request_id: str | None = None,
    status: str | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
) -> dict:
    try:
        if started_from and started_to and started_from > started_to:
            raise ValueError("started_from은 started_to보다 늦을 수 없습니다.")
        return {
            "items": _repository(context).search(
                request_id, status, started_from, started_to
            )
        }
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail="감사 저장소를 사용할 수 없습니다.") from error


@audit_router.get(
    "/{request_id}", operation_id="auditGetRequestTrace", response_model=AuditTraceResponse
)
def get_audit_trace(
    request_id: str,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict:
    try:
        return _repository(context).get(request_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error.args[0])) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail="감사 저장소를 사용할 수 없습니다.") from error
