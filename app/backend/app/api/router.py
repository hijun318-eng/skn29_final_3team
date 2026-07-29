from __future__ import annotations

from fastapi import APIRouter, Request

from app.adapters.fake_data_platform import FakeDataPlatformAdapter
from app.context import request_context
from app.contracts import AnalysisRequest, ApiResponse, response_meta
from app.controllers.analysis_controller import AnalysisController
from app.services.analysis_service import AnalysisService
from app.services.readiness import AppDatabaseReadiness


router = APIRouter()
controller = AnalysisController(AnalysisService(FakeDataPlatformAdapter()))
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
def analysis(payload: AnalysisRequest, request: Request) -> ApiResponse:
    return controller.submit(payload, request_context(request))
