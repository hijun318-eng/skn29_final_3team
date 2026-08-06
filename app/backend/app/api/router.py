from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

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
    EmptyData,
    ErrorBody,
    ErrorCode,
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
from app.services.execution_control import ConcurrentExecutionGate
from app.services.routing_service import RoutingService
from app.services.readiness import AppDatabaseReadiness


def _routing_service() -> RoutingService:
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
    if database_url:
        return RoutingService.from_database(database_url)
    if os.getenv("DATA_PLATFORM_MODE") == "versioned-trino":
        return RoutingService.for_versioned_trino_demo()
    return RoutingService()


def _data_platform():
    mode = os.getenv("DATA_PLATFORM_MODE", "fake")
    if mode == "fake":
        return FakeDataPlatformAdapter()
    if mode not in {"real", "versioned-trino"}:
        raise ValueError(f"unsupported DATA_PLATFORM_MODE: {mode}")
    from app.adapters.i2_data_platform import I2DataPlatformAdapter

    return I2DataPlatformAdapter(
        os.getenv("TRINO_URL", "http://trino:8080"),
        os.getenv("TRINO_USER", "answervice"),
        os.getenv("DATAHUB_GMS_URL", "http://datahub-gms:8080"),
        os.getenv("DATAHUB_API_TOKEN"),
        require_live_metadata=mode == "real",
    )


def _model():
    mode = os.getenv("MODEL_MODE", "fake")
    if mode == "fake":
        return FakeModelAdapter()
    from app.adapters.contract_model import ContractModelAdapter

    if mode == "contract-fake":
        return ContractModelAdapter()
    if mode == "openai":
        return ContractModelAdapter.from_openai(
            os.getenv("MODEL_ENDPOINT", ""),
            os.getenv("MODEL_API_TOKEN"),
            float(os.getenv("MODEL_TIMEOUT_SECONDS", "15")),
        )
    raise ValueError(f"unsupported MODEL_MODE: {mode}")


router = APIRouter()
controller = AnalysisController(
    AnalysisService(_data_platform(), _model()),
    _routing_service(),
)
readiness = AppDatabaseReadiness()
execution_gate = ConcurrentExecutionGate()


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
) -> AnalysisResponse | JSONResponse:
    wait_seconds = float(os.getenv("ANALYSIS_QUEUE_WAIT_SECONDS", "0"))
    if not execution_gate.acquire(wait_seconds):
        response = ErrorResponse(
            data=EmptyData(),
            meta=response_meta(context),
            error=ErrorBody(
                code=ErrorCode.RATE_LIMITED,
                message="동시 분석은 최대 2건까지 실행할 수 있습니다.",
                retryable=True,
            ),
        )
        return JSONResponse(status_code=429, content=response.model_dump(mode="json"))
    try:
        return controller.submit(payload, context)
    finally:
        execution_gate.release()
