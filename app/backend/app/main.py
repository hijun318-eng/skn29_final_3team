from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.router import router
from app.context import request_context
from app.contracts import ApiResponse, ErrorBody, ErrorCode, response_meta


app = FastAPI(title="Answervice Control Plane", version="1.0.0-draft")
app.include_router(router)


@app.middleware("http")
async def request_context_header(request: Request, call_next):
    request.state.request_id = uuid4()
    request.state.trace_id = uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-Id"] = str(request.state.request_id)
    response.headers["X-Trace-Id"] = request.state.trace_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, _exc: RequestValidationError) -> JSONResponse:
    context = request_context(request)
    body = ApiResponse(
        meta=response_meta(context),
        error=ErrorBody(code=ErrorCode.CONTEXT_INCOMPLETE, message="요청 형식이 올바르지 않습니다."),
    )
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


@app.exception_handler(Exception)
async def internal_error(request: Request, _exc: Exception) -> JSONResponse:
    context = request_context(request)
    body = ApiResponse(
        meta=response_meta(context),
        error=ErrorBody(code=ErrorCode.INTERNAL_ERROR, message="내부 오류가 발생했습니다."),
    )
    return JSONResponse(status_code=500, content=body.model_dump(mode="json"))

