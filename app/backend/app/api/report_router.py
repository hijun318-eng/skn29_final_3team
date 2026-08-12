from __future__ import annotations

import os
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.context import analysis_context
from app.contracts import (
    EmptyData,
    ErrorBody,
    ErrorCode,
    ErrorResponse,
    RequestContext,
    Role,
    response_meta,
)
from app.report_contracts import (
    ApproveReportVersionRequest,
    CreateManualRunRequest,
    CreateReportDefinitionRequest,
    ManualRunCommandResponse,
    ReplaceReportBlocksRequest,
    ReportDefinitionListResponse,
    ReportDefinitionResponse,
    ReportRunListResponse,
    ReportRunResponse,
    ReportScheduleListResponse,
    ReportScheduleResponse,
    UpsertReportScheduleRequest,
)


report_router = APIRouter()


def report_owner_context(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> RequestContext:
    if context.role not in {Role.HOTEL_ANALYST, Role.REPORT_ADMIN}:
        raise HTTPException(status_code=403, detail="Report 사용 권한이 없습니다.")
    return context


def _router(context: RequestContext):
    from app.adapters.report_repository import PostgresReportRepository
    from src.report.router import create_report_router

    database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="Report 저장소를 사용할 수 없습니다.")
    return create_report_router(PostgresReportRepository(database_url, context.user_id))


def _call(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    from src.report.router import ReportRouteError

    try:
        return action()
    except ReportRouteError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@report_router.post(
    "/reports/definitions",
    operation_id="reportCreateDefinition",
    response_model=ReportDefinitionResponse,
)
def create_definition(
    payload: CreateReportDefinitionRequest,
    context: Annotated[RequestContext, Depends(report_owner_context)],
) -> dict[str, Any]:
    return _call(
        lambda: _router(context).create_definition(
            payload.model_dump(mode="json", exclude_none=True)
        )
    )


@report_router.get(
    "/reports/definitions",
    operation_id="reportListDefinitions",
    response_model=ReportDefinitionListResponse,
)
def list_definitions(
    context: Annotated[RequestContext, Depends(report_owner_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).list_definitions())


@report_router.post(
    "/reports/definitions/{definition_id}/versions/{version}/approve",
    operation_id="reportApproveVersion",
    response_model=ReportDefinitionResponse,
)
def approve_version(
    definition_id: str,
    version: int,
    payload: ApproveReportVersionRequest,
    context: Annotated[RequestContext, Depends(report_owner_context)],
) -> dict[str, Any]:
    return _call(
        lambda: _router(context).approve_version(
            definition_id, version, payload.approved_at.isoformat()
        )
    )


@report_router.post(
    "/reports/definitions/{definition_id}/versions/{version}/drafts",
    operation_id="reportCreateNextDraft",
    response_model=ReportDefinitionResponse,
)
def create_next_draft(
    definition_id: str,
    version: int,
    context: Annotated[RequestContext, Depends(report_owner_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).create_next_draft(definition_id, version))


@report_router.get(
    "/reports/definitions/{definition_id}/versions/{version}",
    operation_id="reportGetDefinitionVersion",
    response_model=ReportDefinitionResponse,
)
def get_version(
    definition_id: str,
    version: int,
    context: Annotated[RequestContext, Depends(report_owner_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).get_version(definition_id, version))


@report_router.put(
    "/reports/definitions/{definition_id}/versions/{version}/blocks",
    operation_id="reportReplaceDraftBlocks",
    response_model=ReportDefinitionResponse,
)
def replace_draft_blocks(
    definition_id: str,
    version: int,
    payload: ReplaceReportBlocksRequest,
    context: Annotated[RequestContext, Depends(report_owner_context)],
) -> dict[str, Any]:
    return _call(
        lambda: _router(context).replace_draft_blocks(
            definition_id,
            version,
            payload.model_dump(mode="json", exclude_none=True),
        )
    )


@report_router.get(
    "/reports/runs",
    operation_id="reportListRuns",
    response_model=ReportRunListResponse,
)
def list_runs(
    context: Annotated[RequestContext, Depends(report_owner_context)],
    definition_id: str | None = None,
) -> dict[str, Any]:
    return _call(lambda: _router(context).list_runs(definition_id))


@report_router.post(
    "/reports/runs/manual",
    operation_id="reportCreateManualRunCommand",
    response_model=ManualRunCommandResponse,
)
def create_manual_run_command(
    payload: CreateManualRunRequest,
    context: Annotated[RequestContext, Depends(report_owner_context)],
) -> dict[str, Any]:
    return _call(
        lambda: _router(context).create_manual_run_command(payload.model_dump(mode="json"))
    )


@report_router.put(
    "/reports/definitions/{definition_id}/versions/{version}/schedule",
    operation_id="reportUpsertSchedule",
    response_model=ReportScheduleResponse,
    responses={
        409: {"model": ErrorResponse, "description": "수동 실행 또는 재실행 binding 미확인"},
    },
)
def upsert_schedule(
    definition_id: str,
    version: int,
    payload: UpsertReportScheduleRequest,
    context: Annotated[RequestContext, Depends(report_owner_context)],
) -> dict[str, Any] | JSONResponse:
    try:
        return _call(
            lambda: _router(context).upsert_schedule(
                definition_id, version, payload.model_dump(mode="json")
            )
        )
    except HTTPException as error:
        if error.status_code != 409:
            raise
        body = ErrorResponse(
            data=EmptyData(),
            meta=response_meta(context),
            error=ErrorBody(
                code=ErrorCode.REPORT_SCHEDULE_NOT_READY,
                message=str(error.detail),
            ),
        )
        return JSONResponse(status_code=409, content=body.model_dump(mode="json"))


@report_router.get(
    "/reports/schedules",
    operation_id="reportListSchedules",
    response_model=ReportScheduleListResponse,
)
def list_schedules(
    context: Annotated[RequestContext, Depends(report_owner_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).list_schedules())


@report_router.get(
    "/reports/runs/{run_id}",
    operation_id="reportGetRun",
    response_model=ReportRunResponse,
)
def get_run(
    run_id: str,
    context: Annotated[RequestContext, Depends(report_owner_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).get_run(run_id))


def create_run_internal(
    payload: dict[str, Any],
    context: RequestContext,
) -> dict[str, Any]:
    """Trusted worker adapter hook; intentionally not registered as HTTP."""
    return _call(lambda: _router(context).create_run(payload))
