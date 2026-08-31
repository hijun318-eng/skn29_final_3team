"""FastAPI control plane의 middleware, router, 수명주기와 안전한 오류 envelope를 조립한다."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.admin_router import admin_router
from app.api.router import _controller, execution_gate, router
from app.api.report_router import (
    report_router,
    validate_report_assistant_page_render_runtime,
)
from app.api.mcp_router import HEADER_MISMATCH, mcp_router
from app.api.rag_router import rag_router
from app.api.ml_router import router as ml_router
from app.context import ContextValidationError, request_context, valid_trace_id
from app.database import dispose_database
from app.contracts import (
    EmptyData,
    ErrorBody,
    ErrorCode,
    ErrorResponse,
    OPENAPI_DOCUMENT_VERSION,
    response_meta,
)
from app.report_contracts import (
    ReportAssistantExternalTransferDisclosureResponse,
    ReportAssistantExternalTransferError,
    ReportAssistantExternalTransferErrorResponse,
    report_assistant_retry_policy,
)
from app.services.report.scheduler import report_scheduler
from app.services.report.scheduler import _enabled as report_scheduler_enabled
from app.services.conversation.reconciler import conversation_recovery_worker
from app.runtime_release import validate_model_runtime_compatibility


_HTTP_ERROR_MAP = {
    400: (ErrorCode.CONTEXT_INCOMPLETE, "요청을 처리할 수 없습니다."),
    401: (ErrorCode.AUTHENTICATION_REQUIRED, "인증이 필요합니다."),
    403: (ErrorCode.ACCESS_DENIED, "요청한 작업을 수행할 권한이 없습니다."),
    404: (ErrorCode.RESOURCE_NOT_FOUND, "요청한 리소스를 찾을 수 없습니다."),
    410: (ErrorCode.RESOURCE_NOT_FOUND, "요청한 API는 지원이 종료되었습니다."),
    409: (ErrorCode.RESOURCE_CONFLICT, "현재 리소스 상태와 요청이 충돌합니다."),
    405: (ErrorCode.RESOURCE_CONFLICT, "지원하지 않는 HTTP 메서드입니다."),
    422: (ErrorCode.CONTEXT_INCOMPLETE, "요청 형식이나 필수 정보가 올바르지 않습니다."),
    429: (ErrorCode.RATE_LIMITED, "요청이 많습니다. 잠시 후 다시 시도해 주세요."),
    503: (ErrorCode.DEPENDENCY_UNAVAILABLE, "필수 서비스가 준비되지 않았습니다."),
}

_REPORT_ASSISTANT_MODEL_ERROR_CODES = frozenset(
    {
        ErrorCode.REPORT_ASSISTANT_MODEL_AUTHENTICATION_FAILED,
        ErrorCode.REPORT_ASSISTANT_MODEL_RATE_LIMITED,
        ErrorCode.REPORT_ASSISTANT_MODEL_REQUEST_REJECTED,
        ErrorCode.REPORT_ASSISTANT_MODEL_TIMEOUT,
        ErrorCode.REPORT_ASSISTANT_MODEL_TRANSPORT_FAILED,
        ErrorCode.REPORT_ASSISTANT_MODEL_CONTRACT_INVALID,
        ErrorCode.REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID,
        ErrorCode.REPORT_ASSISTANT_TURN_MODEL_FAILED,
        ErrorCode.REPORT_ASSISTANT_TURN_MODEL_INVALID,
    }
)


def _public_report_assistant_model_error(
    request: Request,
    exc: StarletteHTTPException,
) -> ErrorBody | None:
    """승인된 Assistant 모델·renderer 실패만 detail 없이 공개 재시도 계약으로 변환한다."""

    path_parts = request.url.path.split("/")
    if (
        exc.status_code != 502
        or len(path_parts) != 6
        or path_parts[:4] != ["", "reports", "assistant", "sessions"]
        or not path_parts[4]
        or not isinstance(exc.detail, dict)
    ):
        return None
    try:
        code = ErrorCode(exc.detail.get("code"))
    except (TypeError, ValueError):
        return None
    endpoint = path_parts[5]
    if code in _REPORT_ASSISTANT_MODEL_ERROR_CODES and endpoint in {"messages", "review"}:
        message = "보고서 AI 요청을 처리하지 못했습니다."
    elif (
        code is ErrorCode.REPORT_ASSISTANT_PAGE_RENDER_FAILED
        and endpoint in {"messages", "approval", "patch-approval"}
    ):
        message = "후보 보고서 페이지를 렌더링하지 못했습니다."
    else:
        return None

    policy = report_assistant_retry_policy(code.value)
    return ErrorBody(
        code=code,
        message=message,
        retryable=policy.retryable,
        required_action=policy.required_action.value,
    )


def _public_report_assistant_page_constraint_error(
    request: Request,
    exc: StarletteHTTPException,
) -> ErrorBody | None:
    """patch 승인 페이지 불일치에서 검증된 target·actual 정수만 공개한다."""

    path_parts = request.url.path.split("/")
    if (
        exc.status_code != 409
        or len(path_parts) != 6
        or path_parts[:4] != ["", "reports", "assistant", "sessions"]
        or not path_parts[4]
        or path_parts[5] != "patch-approval"
        or not isinstance(exc.detail, dict)
        or exc.detail.get("code")
        != ErrorCode.REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED.value
    ):
        return None
    exact_page_count = exc.detail.get("exact_page_count")
    verified_page_count = exc.detail.get("verified_page_count")
    if (
        isinstance(exact_page_count, bool)
        or not isinstance(exact_page_count, int)
        or not 1 <= exact_page_count <= 20
        or isinstance(verified_page_count, bool)
        or not isinstance(verified_page_count, int)
        or verified_page_count < 1
    ):
        return None
    return ErrorBody(
        code=ErrorCode.REPORT_ASSISTANT_PAGE_CONSTRAINT_UNSATISFIED,
        message="요청한 페이지 수와 실제 보고서 페이지 수가 일치하지 않습니다.",
        exact_page_count=exact_page_count,
        verified_page_count=verified_page_count,
    )


def _public_external_transfer_outcome_unknown(
    request: Request,
    exc: StarletteHTTPException,
) -> ErrorBody | None:
    """응답 유실 가능성이 있는 외부 POST를 자동 재전송하지 않는 공개 409로 변환한다."""

    path_parts = request.url.path.split("/")
    if (
        exc.status_code != 409
        or len(path_parts) != 6
        or path_parts[:4] != ["", "reports", "assistant", "sessions"]
        or not path_parts[4]
        or path_parts[5] not in {"messages", "review", "approval"}
        or not isinstance(exc.detail, dict)
        or exc.detail.get("code") != "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN"
        or str(exc.detail.get("assistant_request_id")) != path_parts[4]
    ):
        return None
    policy = report_assistant_retry_policy("EXTERNAL_TRANSFER_OUTCOME_UNKNOWN")
    return ErrorBody(
        code=ErrorCode.EXTERNAL_TRANSFER_OUTCOME_UNKNOWN,
        message=(
            "외부 모델이 요청을 처리했는지 확인할 수 없어 자동 재전송하지 않았습니다. "
            "새 Assistant 세션에서 전송 범위를 다시 확인해 주세요."
        ),
        retryable=policy.retryable,
        required_action=policy.required_action.value,
    )


def _public_report_assistant_external_transfer_error(
    request: Request,
    exc: StarletteHTTPException,
) -> ReportAssistantExternalTransferError | None:
    """428 detail 중 서버 검증 disclosure와 현재 session ID만 공개 error로 보존한다."""

    path_parts = request.url.path.split("/")
    if (
        exc.status_code != 428
        or len(path_parts) != 6
        or path_parts[:4] != ["", "reports", "assistant", "sessions"]
        or path_parts[5] not in {"messages", "review", "approval"}
        or not isinstance(exc.detail, dict)
        or exc.detail.get("code") != "EXTERNAL_TRANSFER_CONSENT_REQUIRED"
        or str(exc.detail.get("assistant_request_id")) != path_parts[4]
    ):
        return None
    try:
        disclosure = ReportAssistantExternalTransferDisclosureResponse.model_validate(
            exc.detail.get("disclosure")
        )
    except (TypeError, ValueError):
        return None
    if str(disclosure.assistant_request_id) != path_parts[4]:
        return None
    return ReportAssistantExternalTransferError(
        code="EXTERNAL_TRANSFER_CONSENT_REQUIRED",
        message="외부 AI 제공자에게 보고서 자료를 전송하려면 명시적 동의가 필요합니다.",
        assistant_request_id=disclosure.assistant_request_id,
        disclosure=disclosure,
        required_action="REVIEW_EXTERNAL_TRANSFER",
    )


def _allowed_origins() -> list[str]:
    origins = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOW_ORIGINS",
            "http://127.0.0.1:13000,http://localhost:13000,http://localhost:5173",
        ).split(",")
        if origin.strip()
    ]
    if "*" in origins:
        raise RuntimeError("CORS_ALLOW_ORIGINS must contain exact origins")
    return origins


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """앱 수명 동안 report scheduler를 구동하고 종료 시 자원을 역순으로 정리한다.

    scheduler 중지, model/data transport 종료, controller cache 해제, DB pool 폐기를 중첩된
    ``finally``로 보장해 앞선 cleanup 실패가 뒤 자원 누수로 번지지 않게 한다.
    """
    validate_model_runtime_compatibility()
    validate_report_assistant_page_render_runtime()
    controller = None
    try:
        recovery_enabled = bool(os.getenv("APP_RUNTIME_DATABASE_URL", "").strip())
        if recovery_enabled or report_scheduler_enabled():
            controller = _controller()
        if recovery_enabled:
            await conversation_recovery_worker.start(controller.data_platform)
        await report_scheduler.start(controller, execution_gate)
        yield
    finally:
        try:
            await report_scheduler.stop()
        finally:
            try:
                await conversation_recovery_worker.stop()
            finally:
                try:
                    if controller is not None:
                        await controller.aclose()
                finally:
                    _controller.cache_clear()
                    await dispose_database()


app = FastAPI(
    title="Answervice Control Plane",
    version=OPENAPI_DOCUMENT_VERSION,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Contract-Version",
        "X-Role",
        "X-Timezone",
        "X-Trace-Id",
        "X-User-Id",
        "MCP-Protocol-Version",
        "Mcp-Method",
        "Mcp-Name",
    ],
    expose_headers=["X-Request-Id", "X-Trace-Id", "Retry-After"],
)
app.include_router(router)
app.include_router(report_router)
app.include_router(mcp_router)
app.include_router(rag_router)
app.include_router(ml_router)
app.include_router(admin_router)


@app.middleware("http")
async def request_context_header(request: Request, call_next):
    """각 HTTP 요청에 server request ID와 검증된 trace ID를 부여해 응답 header까지 전파한다.

    잘못된 외부 trace는 state에 표시하고 새 trace로 격리해 공격자가 임의 문자열을 log·error
    correlation 식별자로 고정하지 못하게 한다.
    """
    request.state.request_id = uuid4()
    supplied_trace_id = request.headers.get("X-Trace-Id")
    request.state.trace_id_invalid = bool(
        supplied_trace_id and not valid_trace_id(supplied_trace_id)
    )
    request.state.trace_id = (
        supplied_trace_id
        if valid_trace_id(supplied_trace_id)
        else uuid4().hex
    )
    response = await call_next(request)
    response.headers["X-Request-Id"] = str(request.state.request_id)
    response.headers["X-Trace-Id"] = request.state.trace_id
    return response


@app.exception_handler(ContextValidationError)
async def context_error(request: Request, exc: ContextValidationError) -> JSONResponse:
    """권한·계약 Context의 typed 오류 code와 안전한 메시지를 공통 오류 envelope로 변환한다."""
    body = ErrorResponse(
        data=EmptyData(),
        meta=response_meta(request_context(request)),
        error=ErrorBody(code=exc.code, message=exc.message),
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """MCP header 오류 또는 일반 API의 누락 필드를 각 공개 계약으로 변환한다."""
    if request.url.path == "/mcp":
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "error": {
                    "code": HEADER_MISMATCH,
                    "message": "Required MCP request header is missing or malformed",
                },
            },
        )
    context = request_context(request)
    missing = tuple(
        sorted(
            {
                str(item["loc"][-1])
                for item in exc.errors()
                if item.get("type") == "missing" and item.get("loc")
            }
        )
    )
    body = ErrorResponse(
        data=EmptyData(),
        meta=response_meta(context),
        error=ErrorBody(
            code=ErrorCode.CONTEXT_INCOMPLETE,
            message="요청 형식이나 필수 정보가 올바르지 않습니다.",
            missing_requirements=missing,
        ),
    )
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """내부 HTTP detail을 노출하지 않고 상태별 공개 error code와 메시지로 정규화한다."""
    context = request_context(request)
    transfer_error = _public_report_assistant_external_transfer_error(request, exc)
    if transfer_error is not None:
        if not transfer_error.trace_id:
            object.__setattr__(transfer_error, "trace_id", context.trace_id)
        transfer_body = ReportAssistantExternalTransferErrorResponse(
            data=EmptyData(),
            meta=response_meta(context),
            error=transfer_error,
        )
        return JSONResponse(
            status_code=428,
            content=transfer_body.model_dump(mode="json"),
            headers=exc.headers,
        )
    error = _public_report_assistant_model_error(request, exc)
    if error is None:
        error = _public_report_assistant_page_constraint_error(request, exc)
    if error is None:
        error = _public_external_transfer_outcome_unknown(request, exc)
    if error is None:
        code, message = _HTTP_ERROR_MAP.get(
            exc.status_code,
            (ErrorCode.INTERNAL_ERROR, "요청을 처리하지 못했습니다."),
        )
        error = ErrorBody(code=code, message=message)
    body = ErrorResponse(
        data=EmptyData(),
        meta=response_meta(context),
        error=error,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(mode="json"),
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def internal_error(request: Request, _exc: Exception) -> JSONResponse:
    """예상하지 못한 예외의 내용은 숨기고 request 추적 정보가 있는 typed 500만 반환한다."""
    context = request_context(request)
    body = ErrorResponse(
        data=EmptyData(),
        meta=response_meta(context),
        error=ErrorBody(code=ErrorCode.INTERNAL_ERROR, message="내부 오류가 발생했습니다."),
    )
    return JSONResponse(status_code=500, content=body.model_dump(mode="json"))
