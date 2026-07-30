from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.adapters.fake_data_platform import FakeDataPlatformAdapter
from app.context import analysis_context, request_context
from app.contracts import AnalysisRequest, ApiResponse, RequestContext, response_meta
from app.controllers.analysis_controller import AnalysisController
from app.services.analysis_service import AnalysisService
from app.services.routing_service import RoutingService
from app.services.readiness import AppDatabaseReadiness


router = APIRouter()
controller = AnalysisController(AnalysisService(FakeDataPlatformAdapter()), RoutingService())
readiness = AppDatabaseReadiness()


@router.get("/health", response_model=ApiResponse)
def health(request: Request) -> ApiResponse:
    context = request_context(request)
    return ApiResponse(data={"status": "healthy"}, meta=response_meta(context))


@router.get("/readiness", response_model=ApiResponse)
def ready(request: Request) -> ApiResponse:
    context = request_context(request)
    probe = readiness.check()
    status = "ready" if probe["app_postgres"] == "reachable" else "not_ready"
    return ApiResponse(data={"status": status, "dependencies": probe}, meta=response_meta(context))


@router.post("/analysis", response_model=ApiResponse)
def analysis(payload: AnalysisRequest, context: Annotated[RequestContext, Depends(analysis_context)]) -> ApiResponse:
    return controller.submit(payload, context)
