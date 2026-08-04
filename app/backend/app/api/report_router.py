from __future__ import annotations

import os
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException

from app.context import analysis_context
from app.contracts import RequestContext, Role


report_router = APIRouter(include_in_schema=False)


def report_admin_context(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> RequestContext:
    if context.role is not Role.REPORT_ADMIN:
        raise HTTPException(status_code=403, detail="Report 관리 권한이 없습니다.")
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


@report_router.post("/reports/definitions")
def create_definition(
    payload: Annotated[dict[str, Any], Body()],
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).create_definition(payload))


@report_router.get("/reports/definitions")
def list_definitions(
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).list_definitions())


@report_router.post("/reports/definitions/{definition_id}/versions/{version}/approve")
def approve_version(
    definition_id: str,
    version: int,
    approved_at: Annotated[str, Body(embed=True)],
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    return _call(
        lambda: _router(context).approve_version(definition_id, version, approved_at)
    )


@report_router.post("/reports/definitions/{definition_id}/versions/{version}/drafts")
def create_next_draft(
    definition_id: str,
    version: int,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).create_next_draft(definition_id, version))


@report_router.get("/reports/definitions/{definition_id}/versions/{version}")
def get_version(
    definition_id: str,
    version: int,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).get_version(definition_id, version))


@report_router.put("/reports/definitions/{definition_id}/versions/{version}/blocks")
def replace_draft_blocks(
    definition_id: str,
    version: int,
    payload: Annotated[dict[str, Any], Body()],
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    return _call(
        lambda: _router(context).replace_draft_blocks(definition_id, version, payload)
    )


@report_router.get("/reports/runs")
def list_runs(
    context: Annotated[RequestContext, Depends(report_admin_context)],
    definition_id: str | None = None,
) -> dict[str, Any]:
    return _call(lambda: _router(context).list_runs(definition_id))


@report_router.post("/reports/runs/manual")
def create_manual_run_command(
    payload: Annotated[dict[str, Any], Body()],
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    if not isinstance(payload.get("idempotency_key"), str) or not payload["idempotency_key"].strip():
        raise HTTPException(status_code=422, detail="idempotency_key는 비어 있을 수 없습니다.")
    return _call(lambda: _router(context).create_manual_run_command(payload))


@report_router.get("/reports/runs/{run_id}")
def get_run(
    run_id: str,
    context: Annotated[RequestContext, Depends(report_admin_context)],
) -> dict[str, Any]:
    return _call(lambda: _router(context).get_run(run_id))


def create_run_internal(
    payload: dict[str, Any],
    context: RequestContext,
) -> dict[str, Any]:
    """Trusted worker adapter hook; intentionally not registered as HTTP."""
    return _call(lambda: _router(context).create_run(payload))
