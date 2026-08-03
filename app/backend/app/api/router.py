from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request

from app.adapters.fake_data_platform import FakeDataPlatformAdapter
from app.adapters.fake_model import FakeModelAdapter
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
from app.services.routing_service import RoutingService
from app.services.readiness import AppDatabaseReadiness


def _routing_service() -> RoutingService:
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
    return (
        RoutingService.from_database(database_url)
        if database_url
        else RoutingService()
    )


def _data_platform():
    if os.getenv("DATA_PLATFORM_MODE", "fake") == "fake":
        return FakeDataPlatformAdapter()
    from app.adapters.i2_data_platform import I2DataPlatformAdapter

    return I2DataPlatformAdapter(
        os.getenv("TRINO_URL", "http://trino:8080"),
        os.getenv("TRINO_USER", "answervice"),
    )


def _model():
    if os.getenv("MODEL_MODE", "fake") == "fake":
        return FakeModelAdapter()
    from app.adapters.contract_model import ContractModelAdapter

    return ContractModelAdapter()


router = APIRouter()
controller = AnalysisController(
    AnalysisService(_data_platform(), _model()),
    _routing_service(),
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
    status = (
        "ready"
        if all(value in {"ready", "not_required"} for value in probe.values())
        else "not_ready"
    )
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
