from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request

from app.adapters.fake_data_platform import FakeDataPlatformAdapter
from app.adapters.fake_context_policy import FakeContextPolicyProvider
from app.contract_examples import (
    ANALYSIS_REQUEST_EXAMPLES,
    ANALYSIS_RESPONSE_EXAMPLES,
)
from app.context import analysis_context, request_context
from app.contracts import (
    AnalysisRequest,
    AnalysisResponse,
    ErrorResponse,
    HealthData,
    HealthResponse,
    ReadinessData,
    ReadinessResponse,
    RequestContext,
    response_meta,
)
from app.controllers.analysis_controller import AnalysisController
from app.services.analysis_service import AnalysisService
from app.services.context_gate import ContextGate
from app.services.routing_service import RoutingService
from app.services.readiness import AppDatabaseReadiness


router = APIRouter()
data_platform = FakeDataPlatformAdapter()
controller = AnalysisController(
    AnalysisService(
        data_platform,
        ContextGate(),
        FakeContextPolicyProvider(data_platform),
    ),
    RoutingService(),
)
readiness = AppDatabaseReadiness()


@router.get(
    "/health",
    response_model=HealthResponse,
    operation_id="getHealth",
)
def health(request: Request) -> HealthResponse:
    context = request_context(request)
    return HealthResponse(
        data=HealthData(status="healthy"),
        meta=response_meta(context),
    )


@router.get(
    "/readiness",
    response_model=ReadinessResponse,
    operation_id="getReadiness",
)
def ready(request: Request) -> ReadinessResponse:
    context = request_context(request)
    probe = readiness.check()
    status = "ready" if probe["app_postgres"] == "reachable" else "not_ready"
    return ReadinessResponse(
        data=ReadinessData(status=status, dependencies=probe),
        meta=response_meta(context),
    )


@router.post(
    "/analysis",
    response_model=AnalysisResponse,
    operation_id="submitAnalysis",
    responses={
        200: {
            "description": "분석 요청 처리 결과",
            "content": {
                "application/json": {
                    "examples": ANALYSIS_RESPONSE_EXAMPLES,
                }
            },
        },
        401: {"model": ErrorResponse, "description": "인증 정보 누락"},
        403: {"model": ErrorResponse, "description": "역할 또는 접근 권한 거부"},
        409: {"model": ErrorResponse, "description": "계약 버전 불일치"},
        422: {"model": ErrorResponse, "description": "요청 Context 또는 body 오류"},
        429: {"model": ErrorResponse, "description": "동시 실행 제한"},
        500: {"model": ErrorResponse, "description": "안전하게 정규화된 내부 오류"},
    },
)
def analysis(
    payload: Annotated[
        AnalysisRequest,
        Body(openapi_examples=ANALYSIS_REQUEST_EXAMPLES),
    ],
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> AnalysisResponse:
    return controller.submit(payload, context)
