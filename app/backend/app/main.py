from __future__ import annotations

import os
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import router
from app.api.audit_router import audit_router
from app.api.catalog_router import catalog_router
from app.api.report_router import report_router
from app.context import ContextValidationError, request_context
from app.contracts import (
    CONTRACT_VERSION,
    EmptyData,
    ErrorBody,
    ErrorCode,
    ErrorResponse,
    OPENAPI_DOCUMENT_VERSION,
    response_meta,
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


app = FastAPI(title="Answervice Control Plane", version=OPENAPI_DOCUMENT_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Access-Profile",
        "X-As-Of",
        "X-Contract-Version",
        "X-Role",
        "X-Timezone",
        "X-Trace-Id",
        "X-User-Id",
    ],
    expose_headers=["X-Request-Id", "X-Trace-Id"],
)
app.include_router(router)
app.include_router(report_router)
app.include_router(audit_router)
app.include_router(catalog_router)


@app.middleware("http")
async def request_context_header(request: Request, call_next):
    request.state.request_id = uuid4()
    request.state.trace_id = request.headers.get("X-Trace-Id") or uuid4().hex
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
async def validation_error(request: Request, _exc: RequestValidationError) -> JSONResponse:
    context = request_context(request)
    body = ErrorResponse(
        data=EmptyData(),
        meta=response_meta(context),
        error=ErrorBody(code=ErrorCode.CONTEXT_INCOMPLETE, message="요청 형식이 올바르지 않습니다."),
    )
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


@app.exception_handler(Exception)
async def internal_error(request: Request, _exc: Exception) -> JSONResponse:
    context = request_context(request)
    body = ErrorResponse(
        data=EmptyData(),
        meta=response_meta(context),
        error=ErrorBody(code=ErrorCode.INTERNAL_ERROR, message="내부 오류가 발생했습니다."),
    )
    return JSONResponse(status_code=500, content=body.model_dump(mode="json"))
