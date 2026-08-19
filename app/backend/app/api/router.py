"""health·readiness·인증·분석 실행 endpoint와 분석 보조 router를 FastAPI에 등록한다."""

from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.contract_examples import (
    ANALYSIS_REQUEST_EXAMPLES,
    ANALYSIS_RESPONSE_EXAMPLES,
)
from app.analysis_contracts import (
    AnalysisRunResponse,
    ReplayAnalysisRequest,
)
from app.context import SESSION_COOKIE, ContextValidationError, analysis_context, optional_session_context, request_context, session_context
from app.contracts import (
    AnalysisRequest,
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
from app.api.analysis_router_runtime import (
    active_analytics_context_release as _active_analytics_context_release,
    analysis_repository as _analysis_repository,
    data_platform as _data_platform,
    model as _model,
    repository_call as _repository_call,
    routing_service as _routing_service,
)
from app.api.analysis_router_support import (
    analysis_support_router,
    cancel_analysis_progress,
    cancel_analysis_progress_by_request,
    create_analysis_definition,
    get_analysis_definition,
    get_analysis_progress,
    get_analysis_progress_by_request,
    get_analysis_run,
    get_analysis_run_artifact,
    list_analysis_definitions,
    list_analysis_runs,
)
from app.controllers.analysis_controller import AnalysisController
from app.services.analysis_service import AnalysisService
from app.services.execution_control import ConcurrentExecutionGate
from app.services.readiness import AppDatabaseReadiness
from app.services.analysis_progress import analysis_progress


@lru_cache(maxsize=1)
def _controller() -> AnalysisController:
    return AnalysisController(
        AnalysisService(_data_platform(), _model()),
        _routing_service(),
    )


router = APIRouter()
readiness = AppDatabaseReadiness()
execution_gate = ConcurrentExecutionGate()


@router.get(
    "/health",
    response_model=HealthResponse,
    operation_id="getHealth",
)
def health(request: Request) -> HealthResponse:
    """모듈의 외부 의존성 도달 가능성과 최소 응답 계약을 점검한다."""
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
async def ready(request: Request) -> ReadinessResponse:
    """필수 운영 의존성을 probe하고 하나라도 준비되지 않으면 typed 503으로 닫는다."""
    context = request_context(request)
    probe = await readiness.check()
    status = (
        "ready"
        if all(value in {"ready", "not_required"} for value in probe.values())
        else "not_ready"
    )
    body = ReadinessResponse(
        data=ReadinessData(status=status, dependencies=probe),
        meta=response_meta(context),
        error=(
            None
            if status == "ready"
            else ErrorBody(
                code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                message="필수 서비스가 준비되지 않았습니다.",
                missing_requirements=tuple(
                    name
                    for name, value in probe.items()
                    if value not in {"ready", "not_required"}
                ),
            )
        ),
    )
    if status == "ready":
        return body
    return JSONResponse(status_code=503, content=body.model_dump(mode="json"))


@router.get(
    "/auth/session",
    response_model=SessionResponse,
    operation_id="getAuthenticatedSession",
)
def authenticated_session(
    request: Request,
    context: Annotated[RequestContext | None, Depends(optional_session_context)],
) -> SessionResponse:
    """검증된 세션의 role만 공개하며 자격 증명이 없을 때는 anonymous 상태를 반환한다."""
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
async def login(payload: LoginRequest, request: Request, response: Response) -> LoginResponse:
    """계정 자격 증명을 검증하고 revocation 가능한 서버 세션을 등록한다.

    원문 token은 secure 정책이 적용된 HTTP-only cookie로만 전달하며 인증 저장소 장애는
    정상 로그인으로 가장하지 않고 dependency 오류로 변환한다.
    """
    try:
        principal = await asyncio.to_thread(
            authenticate_credentials, payload.username, payload.password
        )
        session_token = issue_session_token(principal)
        await register_session(session_token, principal)
    except AuthenticationError as exc:
        code = ErrorCode.DEPENDENCY_UNAVAILABLE if exc.status_code == 503 else ErrorCode.AUTHENTICATION_REQUIRED
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
async def logout(
    request: Request,
    response: Response,
    _context: Annotated[RequestContext, Depends(session_context)],
) -> None:
    """현재 세션을 서버 저장소에서 먼저 폐기한 뒤 브라우저 cookie를 삭제한다."""
    try:
        await revoke_session(getattr(request.state, "session_token", None))
    except AuthenticationError as exc:
        raise ContextValidationError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            exc.message,
            exc.status_code,
        ) from exc
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
async def analysis(
    payload: Annotated[
        AnalysisRequest,
        Body(openapi_examples=ANALYSIS_REQUEST_EXAMPLES),
    ],
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> AnalysisResponse | JSONResponse:
    """호텔 분석가의 질문을 동시 실행 한도 안에서 라우팅·분석·영속화한다.

    진행 상태와 취소 신호를 pipeline에 전달하고, artifact 저장 실패는 성공 응답으로
    덮지 않으며 재시도 가능한 typed 503으로 반환한다.
    """
    if context.role is not Role.HOTEL_ANALYST:
        raise ContextValidationError(
            ErrorCode.ACCESS_DENIED,
            "분석 Agent는 호텔 분석가 역할만 사용할 수 있습니다.",
            403,
        )
    wait_seconds = float(os.getenv("ANALYSIS_QUEUE_WAIT_SECONDS", "0"))
    if not await execution_gate.acquire(wait_seconds):
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
            await _repository_call(
                lambda: repository.begin_request(
                    payload.question, payload.parameters, context
                )
            )
        response = await _controller().submit(
            payload,
            context,
            execution.update,
            lambda stage, outcome: analysis_progress.record(
                context.request_id, stage, outcome
            ),
            lambda: analysis_progress.cancelled(context.request_id),
        )
        final_status = response.data.status
        if repository is not None:
            try:
                await _repository_call(
                    lambda: repository.finish_run(context.request_id, response, execution)
                )
            except HTTPException as error:
                if error.status_code != 503:
                    raise
                final_status = AnalysisStatus.FAILED
                try:
                    await repository.fail_run(
                        context.request_id,
                        ErrorCode.ARTIFACT_PERSIST_FAILED.value,
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
            await _repository_call(lambda: repository.fail_run(context.request_id))
        raise
    finally:
        analysis_progress.finish(context.request_id, final_status)
        execution_gate.release()


@router.post(
    "/analysis/definitions/{definition_id}/runs",
    operation_id="analysisReplayDefinition",
    response_model=AnalysisRunResponse,
)
async def replay_analysis_definition(
    definition_id: UUID,
    payload: ReplayAnalysisRequest,
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict[str, Any]:
    """저장된 분석 정의를 현재 권한·Context release에서 새로운 run으로 재실행한다.

    활성 release가 달라졌거나 미선언 parameter가 들어오면 실행 전에 거부하고,
    idempotency key로 생성된 run만 controller에 전달한다.
    """
    repository = _analysis_repository(context)
    definition = await _repository_call(
        lambda: repository.get_definition(definition_id, replay=True)
    )
    saved_release = str(
        (definition.get("semantic_request") or {}).get("context_release") or ""
    )
    active_release = await _active_analytics_context_release()
    if saved_release != active_release:
        raise ContextValidationError(
            ErrorCode.SCHEMA_VERSION_MISMATCH,
            "저장된 Analysis Definition의 context release가 현재 활성 release와 다릅니다.",
            409,
        )
    unknown_parameters = set(payload.parameters) - set(definition["parameters"])
    if unknown_parameters:
        raise HTTPException(
            status_code=422,
            detail=f"정의되지 않은 Analysis parameter: {', '.join(sorted(unknown_parameters))}",
        )
    parameters = {**definition["parameters"], **payload.parameters}
    replay_context = context.model_copy(update={"as_of": payload.as_of})
    request_id, created = await _repository_call(
        lambda: repository.begin_run(
            definition,
            replay_context,
            payload.as_of,
            payload.idempotency_key,
            parameters,
        )
    )
    if not created:
        run = await _repository_call(lambda: repository.get_run(request_id))
        if run["status"] == "RECEIVED":
            raise HTTPException(status_code=409, detail="Analysis Run이 이미 실행 중입니다.")
        return run
    if not await execution_gate.acquire(
        float(os.getenv("ANALYSIS_QUEUE_WAIT_SECONDS", "0"))
    ):
        await _repository_call(lambda: repository.fail_run(request_id, "UNSUPPORTED"))
        raise HTTPException(status_code=429, detail="동시 분석은 최대 2건까지 실행할 수 있습니다.")
    execution: dict[str, Any] = {}
    try:
        response = await _controller().submit(
            AnalysisRequest(
                question=definition["question"],
                parameters=parameters,
            ),
            replay_context,
            execution.update,
        )
    except ContextValidationError as error:
        await _repository_call(
            lambda: repository.fail_run(
                request_id,
                "PERMISSION" if error.code is ErrorCode.ACCESS_DENIED else "UNSUPPORTED",
            )
        )
        raise
    except Exception:
        await _repository_call(lambda: repository.fail_run(request_id))
        raise
    finally:
        execution_gate.release()
    await _repository_call(lambda: repository.finish_run(request_id, response, execution))
    return await _repository_call(lambda: repository.get_run(request_id))


# =========================================================================
# Bounded Governed Multi-turn Endpoints (CONV-001 ~ CONV-010)
# =========================================================================

@router.post(
    "/conversations",
    operation_id="createConversation",
)
async def create_conversation(
    payload: dict[str, Any] = Body(...),
    context: RequestContext = Depends(session_context),
) -> dict[str, Any]:
    """새로운 분석 대화방을 생성한다."""
    from app.api.analysis_router_runtime import conversation_orchestrator
    title = str(payload.get("title") or "새 분석 대화").strip()
    orch = conversation_orchestrator(_controller())
    conv = await orch._repo.create_conversation(context.user_id, title)
    return {"status": "SUCCESS", "data": conv}


@router.get(
    "/conversations/{conversation_id}/turns",
    operation_id="getConversationTurns",
)
async def get_conversation_turns(
    conversation_id: UUID,
    context: RequestContext = Depends(session_context),
) -> dict[str, Any]:
    """대화방의 불변 턴 목록을 순서대로 조회해 프론트엔드 상태를 수화(Hydration)한다."""
    from app.api.analysis_router_runtime import conversation_orchestrator
    orch = conversation_orchestrator(_controller())
    conv = await orch._repo.get_conversation(conversation_id, context.user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="대화방을 찾을 수 없거나 접근 권한이 없습니다.")
    turns = await orch._repo.list_turns(conversation_id)
    return {
        "status": "SUCCESS",
        "data": {
            "conversation": conv,
            "turns": turns,
        },
    }


@router.post(
    "/conversations/{conversation_id}/commands",
    operation_id="executeConversationCommand",
)
async def execute_conversation_command(
    conversation_id: UUID,
    payload: dict[str, Any] = Body(...),
    context: RequestContext = Depends(session_context),
) -> dict[str, Any]:
    """대화방에서 발화 명령을 실행하여 라우트(ANALYSIS/PRESENTATION/REPORT_ACTION)를 수행한다."""
    from app.api.analysis_router_runtime import conversation_orchestrator
    orch = conversation_orchestrator(_controller())
    conv = await orch._repo.get_conversation(conversation_id, context.user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="대화방을 찾을 수 없거나 접근 권한이 없습니다.")
    if conv["status"] == "ARCHIVED":
        raise HTTPException(status_code=409, detail="아카이브된 대화방에서는 새 명령을 실행할 수 없습니다.")

    result = await orch.execute_command(conversation_id, payload, context)
    if result.get("status") == "CONFLICT":
        raise HTTPException(status_code=409, detail=result.get("message"))
    if result.get("status") == "BUSY":
        raise HTTPException(status_code=409, detail=result.get("message"))
    return {"status": "SUCCESS", "data": result}


router.include_router(analysis_support_router)
