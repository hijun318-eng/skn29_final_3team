from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated, Any, Callable
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.contract_examples import (
    ANALYSIS_REQUEST_EXAMPLES,
    ANALYSIS_RESPONSE_EXAMPLES,
)
from app.analysis_contracts import (
    AnalysisDefinitionListResponse,
    AnalysisDefinitionResponse,
    AnalysisRunListResponse,
    AnalysisRunArtifactResponse,
    AnalysisRunResponse,
    CreateAnalysisDefinitionRequest,
    ReplayAnalysisRequest,
)
from app.context import SESSION_COOKIE, ContextValidationError, analysis_context, optional_session_context, request_context, session_context
from app.contracts import (
    AnalysisRequest,
    AnalysisProgressResponse,
    AnalysisResponse,
    AnalysisStatus,
    EmptyData,
    ErrorBody,
    ErrorCode,
    ErrorResponse,
    HealthData,
    HealthResponse,
    LoginData,
    LoginRequest,
    LoginResponse,
    ReadinessData,
    ReadinessResponse,
    RequestContext,
    Role,
    SessionData,
    SessionResponse,
    response_meta,
)
from app.auth import AuthenticationError, authenticate_credentials, issue_session_token, register_session, revoke_session
from app.controllers.analysis_controller import AnalysisController
from app.services.analysis_service import AnalysisService
from app.services.execution_control import ConcurrentExecutionGate
from app.services.routing_service import RoutingService
from app.services.readiness import AppDatabaseReadiness
from app.services.analysis_progress import analysis_progress


def _routing_service() -> RoutingService:
    database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
    if database_url:
        return RoutingService.from_database(database_url)
    return RoutingService()


def _data_platform():
    from app.adapters.i2_data_platform import I2DataPlatformAdapter

    return I2DataPlatformAdapter(
        os.getenv("TRINO_URL", "http://trino:8080"),
        os.getenv("TRINO_USER", "answervice"),
        os.getenv("DATAHUB_GMS_URL", "http://datahub-gms:8080"),
        os.getenv("DATAHUB_API_TOKEN"),
        require_live_metadata=True,
        allow_template_assets=False,
    )


def _model():
    from app.adapters.contract_model import ContractModelAdapter

    node2_model = os.getenv("NODE2_MODEL", "")
    if node2_model:
        node2_provider = os.getenv("NODE2_MODEL_PROVIDER", "openai")
        use_openai_credentials = node2_provider == "openai"
        return ContractModelAdapter.from_endpoints(
            openai_endpoint=os.getenv("OPENAI_ENDPOINT", ""),
            openai_token=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", ""),
            node2_endpoint=os.getenv(
                "OPENAI_ENDPOINT" if use_openai_credentials else "NODE2_MODEL_ENDPOINT",
                "",
            ),
            node2_token=os.getenv(
                "OPENAI_API_KEY" if use_openai_credentials else "NODE2_MODEL_API_TOKEN",
                "",
            ),
            node2_model=node2_model,
            node2_provider=node2_provider,
            timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "60")),
        )
    return ContractModelAdapter.from_openai(
        endpoint=os.getenv("OPENAI_ENDPOINT", ""),
        token=os.getenv("OPENAI_API_KEY", ""),
        model=os.getenv("OPENAI_MODEL", ""),
        timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "60")),
    )


@lru_cache(maxsize=1)
def _controller() -> AnalysisController:
    return AnalysisController(
        AnalysisService(_data_platform(), _model()),
        _routing_service(),
    )


router = APIRouter()
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


@router.get(
    "/auth/session",
    response_model=SessionResponse,
    operation_id="getAuthenticatedSession",
)
def authenticated_session(
    request: Request,
    context: Annotated[RequestContext | None, Depends(optional_session_context)],
) -> SessionResponse:
    if context is None:
        return SessionResponse(data=SessionData(status="anonymous"), meta=response_meta(request_context(request)))
    return SessionResponse(
        data=SessionData(role=context.role),
        meta=response_meta(context),
    )


@router.post(
    "/auth/login",
    response_model=LoginResponse,
    operation_id="createAuthenticatedSession",
    responses={401: {"model": ErrorResponse, "description": "아이디 또는 비밀번호 불일치"}},
)
def login(payload: LoginRequest, request: Request, response: Response) -> LoginResponse:
    try:
        principal = authenticate_credentials(payload.username, payload.password)
        session_token = issue_session_token(principal)
        register_session(session_token, principal)
    except AuthenticationError as exc:
        code = ErrorCode.INTERNAL_ERROR if exc.status_code == 503 else ErrorCode.AUTHENTICATION_REQUIRED
        raise ContextValidationError(code, exc.message, exc.status_code) from exc
    context = RequestContext(
        request_id=request.state.request_id,
        trace_id=request.state.trace_id,
        user_id=principal.subject,
        role=principal.role,
    )
    request.state.context = context
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        httponly=True,
        secure=os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() == "true",
        samesite="strict",
        max_age=min(86_400, max(900, int(os.getenv("AUTH_SESSION_TTL_SECONDS", "28800")))),
        path="/",
    )
    return LoginResponse(
        data=LoginData(role=principal.role),
        meta=response_meta(context),
    )


@router.post("/auth/logout", status_code=204, operation_id="deleteAuthenticatedSession")
def logout(
    request: Request,
    response: Response,
    _context: Annotated[RequestContext, Depends(session_context)],
) -> None:
    try:
        revoke_session(getattr(request.state, "session_token", None))
    except AuthenticationError as exc:
        raise ContextValidationError(ErrorCode.INTERNAL_ERROR, exc.message, exc.status_code) from exc
    response.delete_cookie(
        SESSION_COOKIE,
        secure=os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() == "true",
        samesite="strict",
        path="/",
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
    if context.role is not Role.HOTEL_ANALYST:
        raise ContextValidationError(
            ErrorCode.ACCESS_DENIED,
            "분석 Agent는 호텔 분석가 역할만 사용할 수 있습니다.",
            403,
        )
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
    analysis_progress.start(
        context.trace_id, context.user_id, context.role, context.request_id
    )
    repository = None
    execution: dict[str, Any] = {}
    final_status = AnalysisStatus.FAILED
    try:
        if os.getenv("APP_RUNTIME_DATABASE_URL"):
            repository = _analysis_repository(context)
            _repository_call(
                lambda: repository.begin_request(
                    payload.question, payload.parameters, context
                )
            )
        response = _controller().submit(
            payload,
            context,
            execution.update,
            lambda stage, outcome: analysis_progress.record(
                context.trace_id, stage, outcome
            ),
            lambda: analysis_progress.cancelled(context.trace_id),
        )
        final_status = response.data.status
        if repository is not None:
            try:
                _repository_call(
                    lambda: repository.finish_run(context.request_id, response, execution)
                )
            except HTTPException as error:
                if error.status_code != 503:
                    raise
                final_status = AnalysisStatus.FAILED
                try:
                    repository.fail_run(
                        context.request_id, ErrorCode.ARTIFACT_PERSIST_FAILED.value
                    )
                except Exception:
                    pass
                failure = ErrorResponse(
                    data=EmptyData(),
                    meta=response_meta(context),
                    error=ErrorBody(
                        code=ErrorCode.ARTIFACT_PERSIST_FAILED,
                        message="분석 결과를 저장하지 못했습니다.",
                        retryable=True,
                    ),
                )
                return JSONResponse(
                    status_code=503,
                    content=failure.model_dump(mode="json"),
                )
        return response
    except Exception:
        if repository is not None:
            _repository_call(lambda: repository.fail_run(context.request_id))
        raise
    finally:
        analysis_progress.finish(context.trace_id, final_status)
        execution_gate.release()


@router.get(
    "/analysis/progress/{trace_id}",
    response_model=AnalysisProgressResponse,
    operation_id="getAnalysisProgress",
)
def get_analysis_progress(
    trace_id: str,
    context: Annotated[RequestContext, Depends(session_context)],
) -> AnalysisProgressResponse:
    try:
        data = analysis_progress.get(trace_id, context.user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="진행 중인 분석을 찾을 수 없습니다.") from error
    return AnalysisProgressResponse(data=data, meta=response_meta(context))


@router.post(
    "/analysis/progress/{trace_id}/cancel",
    response_model=AnalysisProgressResponse,
    operation_id="cancelAnalysisProgress",
)
def cancel_analysis_progress(
    trace_id: str,
    context: Annotated[RequestContext, Depends(session_context)],
) -> AnalysisProgressResponse:
    try:
        data = analysis_progress.cancel(trace_id, context.user_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="진행 중인 분석을 찾을 수 없습니다.") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail="이미 종료된 분석입니다.") from error
    return AnalysisProgressResponse(data=data, meta=response_meta(context))


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
        lambda: repository.create_definition_from_run(payload.source_request_id, payload.title)
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
    unknown_parameters = set(payload.parameters) - set(definition["parameters"])
    if unknown_parameters:
        raise HTTPException(
            status_code=422,
            detail=f"정의되지 않은 Analysis parameter: {', '.join(sorted(unknown_parameters))}",
        )
    parameters = {**definition["parameters"], **payload.parameters}
    replay_context = context.model_copy(update={"as_of": payload.as_of})
    request_id, created = _repository_call(
        lambda: repository.begin_run(
            definition,
            replay_context,
            payload.as_of,
            payload.idempotency_key,
            parameters,
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
        response = _controller().submit(
            AnalysisRequest(
                question=definition["question"],
                parameters=parameters,
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


@router.get(
    "/analysis/runs/{request_id}/artifact",
    operation_id="analysisGetRunArtifact",
    response_model=AnalysisRunArtifactResponse,
)
def get_analysis_run_artifact(
    request_id: UUID,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    repository = _analysis_repository(context)
    return _repository_call(lambda: repository.get_run_artifact(request_id))
