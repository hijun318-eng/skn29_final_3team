from __future__ import annotations

import os
from typing import Annotated, Any, Callable
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.adapters.fake_data_platform import FakeDataPlatformAdapter
from app.adapters.fake_model import FakeModelAdapter
from app.contract_examples import (
    ANALYSIS_REQUEST_EXAMPLES,
    ANALYSIS_RESPONSE_EXAMPLES,
)
from app.analysis_contracts import (
    AnalysisDefinitionListResponse,
    AnalysisDefinitionResponse,
    AnalysisRunListResponse,
    AnalysisRunResponse,
    CreateAnalysisDefinitionRequest,
    ReplayAnalysisRequest,
)
from app.context import ContextValidationError, analysis_context, request_context
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
    if os.getenv("DATA_PLATFORM_MODE") == "versioned-trino":
        return RoutingService.for_versioned_trino_demo()
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
    if database_url:
        return RoutingService.from_database(database_url)
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
    mode = (os.getenv("MODEL_MODE") or os.getenv("LLM") or "fake").strip().lower()
    if mode == "fake":
        return FakeModelAdapter()
    from app.adapters.contract_model import ContractModelAdapter, TemplateOnlyModelAdapter

    if mode == "template-only":
        return TemplateOnlyModelAdapter()

    if mode == "contract-fake":
        return ContractModelAdapter()
    if mode == "openai":
        return ContractModelAdapter.from_openai(
            os.getenv("OPENAI_ENDPOINT")
            or os.getenv("MODEL_ENDPOINT")
            or "https://api.openai.com",
            os.getenv("OPENAI_API_KEY")
            or os.getenv("LLM_API_KEY")
            or os.getenv("MODEL_API_TOKEN"),
            os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            float(os.getenv("MODEL_TIMEOUT_SECONDS", "30")),
            os.getenv("NODE2_MODEL_ENDPOINT") or os.getenv("SLLM_ENDPOINT"),
            os.getenv("NODE2_MODEL_API_TOKEN") or os.getenv("SLLM_API_KEY"),
            os.getenv("NODE2_MODEL", "Qwen/Qwen3-4B"),
        )
    raise ValueError(f"unsupported MODEL_MODE: {mode}")


router = APIRouter()
controller = AnalysisController(
    AnalysisService(_data_platform(), _model()),
    _routing_service(),
)
readiness = AppDatabaseReadiness()
execution_gate = ConcurrentExecutionGate()


def _analysis_repository(context: RequestContext):
    from app.adapters.analysis_repository import PostgresAnalysisRepository

    database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="Analysis 저장소를 사용할 수 없습니다.")
    return PostgresAnalysisRepository(database_url, context.user_id)


def _repository_call(action: Callable[[], Any]) -> Any:
    from app.adapters.analysis_repository import AnalysisRepositoryUnavailable

    try:
        return action()
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except AnalysisRepositoryUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


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
    repository = None
    execution: dict[str, Any] = {}
    try:
        if os.getenv("APP_RUNTIME_DATABASE_URL"):
            repository = _analysis_repository(context)
            _repository_call(lambda: repository.begin_request(payload.question, context))
        response = controller.submit(payload, context, execution.update)
        if repository is not None:
            _repository_call(
                lambda: repository.finish_run(context.request_id, response, execution)
            )
        return response
    except Exception:
        if repository is not None:
            _repository_call(lambda: repository.fail_run(context.request_id))
        raise
    finally:
        execution_gate.release()


@router.post(
    "/analysis/definitions",
    operation_id="analysisCreateDefinition",
    response_model=AnalysisDefinitionResponse,
)
def create_analysis_definition(
    payload: CreateAnalysisDefinitionRequest,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    repository = _analysis_repository(context)
    return _repository_call(
        lambda: repository.create_definition(
            payload.title,
            payload.question,
            payload.model_dump(mode="json")["parameters"],
        )
    )


@router.get(
    "/analysis/definitions",
    operation_id="analysisListDefinitions",
    response_model=AnalysisDefinitionListResponse,
)
def list_analysis_definitions(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    repository = _analysis_repository(context)
    return {"items": _repository_call(repository.list_definitions)}


@router.get(
    "/analysis/definitions/{definition_id}",
    operation_id="analysisGetDefinition",
    response_model=AnalysisDefinitionResponse,
)
def get_analysis_definition(
    definition_id: UUID,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    repository = _analysis_repository(context)
    return _repository_call(lambda: repository.get_definition(definition_id))


@router.post(
    "/analysis/definitions/{definition_id}/runs",
    operation_id="analysisReplayDefinition",
    response_model=AnalysisRunResponse,
)
def replay_analysis_definition(
    definition_id: UUID,
    payload: ReplayAnalysisRequest,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    repository = _analysis_repository(context)
    definition = _repository_call(
        lambda: repository.get_definition(definition_id, replay=True)
    )
    replay_context = context.model_copy(update={"as_of": payload.as_of})
    request_id, created = _repository_call(
        lambda: repository.begin_run(
            definition,
            replay_context,
            payload.as_of,
            payload.idempotency_key,
        )
    )
    if not created:
        run = _repository_call(lambda: repository.get_run(request_id))
        if run["status"] == "RECEIVED":
            raise HTTPException(status_code=409, detail="Analysis Run이 이미 실행 중입니다.")
        return run
    if not execution_gate.acquire(float(os.getenv("ANALYSIS_QUEUE_WAIT_SECONDS", "0"))):
        _repository_call(lambda: repository.fail_run(request_id, "UNSUPPORTED"))
        raise HTTPException(status_code=429, detail="동시 분석은 최대 2건까지 실행할 수 있습니다.")
    execution: dict[str, Any] = {}
    try:
        response = controller.submit(
            AnalysisRequest(
                question=definition["question"],
                parameters=definition["parameters"],
            ),
            replay_context,
            execution.update,
        )
    except ContextValidationError as error:
        _repository_call(
            lambda: repository.fail_run(
                request_id,
                "PERMISSION" if error.code is ErrorCode.ACCESS_DENIED else "UNSUPPORTED",
            )
        )
        raise
    except Exception:
        _repository_call(lambda: repository.fail_run(request_id))
        raise
    finally:
        execution_gate.release()
    _repository_call(lambda: repository.finish_run(request_id, response, execution))
    return _repository_call(lambda: repository.get_run(request_id))


@router.get(
    "/analysis/runs",
    operation_id="analysisListRuns",
    response_model=AnalysisRunListResponse,
)
def list_analysis_runs(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    repository = _analysis_repository(context)
    return {"items": _repository_call(repository.list_runs)}


@router.get(
    "/analysis/runs/{request_id}",
    operation_id="analysisGetRun",
    response_model=AnalysisRunResponse,
)
def get_analysis_run(
    request_id: UUID,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    repository = _analysis_repository(context)
    return _repository_call(lambda: repository.get_run(request_id))
