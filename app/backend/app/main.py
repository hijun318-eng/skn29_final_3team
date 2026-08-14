from __future__ import annotations

import os
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import _controller, execution_gate, router
from app.api.report_router import report_router
from app.api.mcp_router import mcp_router
from app.context import ContextValidationError, request_context, valid_trace_id
from app.contracts import (
    EmptyData,
    ErrorBody,
    ErrorCode,
    ErrorResponse,
    OPENAPI_DOCUMENT_VERSION,
    response_meta,
)
from app.services.report_scheduler import report_scheduler


_HTTP_ERROR_MAP = {
    400: (ErrorCode.CONTEXT_INCOMPLETE, "요청을 처리할 수 없습니다."),
    401: (ErrorCode.AUTHENTICATION_REQUIRED, "인증이 필요합니다."),
    403: (ErrorCode.ACCESS_DENIED, "요청한 작업을 수행할 권한이 없습니다."),
    404: (ErrorCode.RESOURCE_NOT_FOUND, "요청한 리소스를 찾을 수 없습니다."),
    409: (ErrorCode.RESOURCE_CONFLICT, "현재 리소스 상태와 요청이 충돌합니다."),
    405: (ErrorCode.RESOURCE_CONFLICT, "지원하지 않는 HTTP 메서드입니다."),
    422: (ErrorCode.CONTEXT_INCOMPLETE, "요청 형식이나 필수 정보가 올바르지 않습니다."),
    429: (ErrorCode.RATE_LIMITED, "요청이 많습니다. 잠시 후 다시 시도해 주세요."),
    503: (ErrorCode.DEPENDENCY_UNAVAILABLE, "필수 서비스가 준비되지 않았습니다."),
}


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
    await report_scheduler.start(_controller(), execution_gate)
    try:
        yield
    finally:
        await report_scheduler.stop()


app = FastAPI(
    title="Answervice Control Plane",
    version=OPENAPI_DOCUMENT_VERSION,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-As-Of",
        "X-Contract-Version",
        "X-Role",
        "X-Timezone",
        "X-Trace-Id",
        "X-User-Id",
        "MCP-Protocol-Version",
        "Mcp-Method",
        "Mcp-Name",
    ],
    expose_headers=["X-Request-Id", "X-Trace-Id"],
)
app.include_router(router)
app.include_router(report_router)
app.include_router(mcp_router)


@app.middleware("http")
async def request_context_header(request: Request, call_next):
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
    body = ErrorResponse(
        data=EmptyData(),
        meta=response_meta(request_context(request)),
        error=ErrorBody(code=exc.code, message=exc.message),
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
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
    context = request_context(request)
    code, message = _HTTP_ERROR_MAP.get(
        exc.status_code,
        (ErrorCode.INTERNAL_ERROR, "요청을 처리하지 못했습니다."),
    )
    body = ErrorResponse(
        data=EmptyData(),
        meta=response_meta(context),
        error=ErrorBody(code=code, message=message),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(mode="json"),
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def internal_error(request: Request, _exc: Exception) -> JSONResponse:
    context = request_context(request)
    body = ErrorResponse(
        data=EmptyData(),
        meta=response_meta(context),
        error=ErrorBody(code=ErrorCode.INTERNAL_ERROR, message="내부 오류가 발생했습니다."),
    )
    return JSONResponse(status_code=500, content=body.model_dump(mode="json"))
