from __future__ import annotations

import hashlib
import json
import os
import time
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request, Security
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.analysis_repository import AnalysisRepositoryUnavailable, PostgresAnalysisRepository
from app.auth import AuthenticationError, Principal, authenticate_token
from app.context import bearer_auth


MCP_PROTOCOL_VERSION = "2026-07-28"
TOOL_ID = UUID("c4454392-2f92-54a4-ad13-b8cdaba45732")
TOOL_NAME = "analysis.get_run"
TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"request_id": {"type": "string", "format": "uuid"}},
    "required": ["request_id"],
    "additionalProperties": False,
}
TOOL_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "request_id": {"type": "string"},
        "status": {"type": "string"},
        "trace_id": {"type": "string"},
        "query_id": {"type": ["string", "null"]},
        "artifact_id": {"type": ["string", "null"]},
    },
    "required": ["request_id", "status", "trace_id", "query_id", "artifact_id"],
}

mcp_router = APIRouter()


@lru_cache(maxsize=None)
def _engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def _database_url() -> str:
    value = os.getenv("APP_RUNTIME_DATABASE_URL", "")
    if not value:
        raise HTTPException(status_code=503, detail="MCP 저장소를 사용할 수 없습니다.")
    return value


def _principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_auth)],
) -> Principal:
    try:
        return authenticate_token(credentials.credentials if credentials else None)
    except AuthenticationError as error:
        headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None
        raise HTTPException(status_code=error.status_code, detail=error.message, headers=headers) from error


def _rpc_result(request_id: str | int, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def _rpc_error(request_id: str | int | None, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=status,
    )


def _origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return True
    allowed = {item.strip() for item in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if item.strip()}
    return origin in allowed


def _has_client_info(params: dict[str, Any]) -> bool:
    meta = params.get("_meta")
    client = meta.get("io.modelcontextprotocol/clientInfo") if isinstance(meta, dict) else None
    return (
        isinstance(client, dict)
        and isinstance(client.get("name"), str)
        and bool(client["name"].strip())
        and isinstance(client.get("version"), str)
        and bool(client["version"].strip())
    )


def _enabled_tool(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            return bool(connection.execute(
                text("SELECT is_enabled FROM tooling.tool_registry WHERE tool_id = :tool_id AND tool_code = :tool_code"),
                {"tool_id": TOOL_ID, "tool_code": TOOL_NAME},
            ).scalar_one_or_none())
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="MCP Tool Registry를 사용할 수 없습니다.") from error


def _record_run(
    engine: Engine,
    principal: Principal,
    trace_id: str,
    arguments: dict[str, Any],
    status: str,
    started: float,
    output_ref: dict[str, Any],
    error_code: str | None = None,
) -> None:
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO tooling.tool_runs
                        (tool_run_id, tool_id, caller_user_id, caller_role, trace_id,
                         input_hash, status, latency_ms, output_ref_json, error_code)
                    VALUES (:run_id, :tool_id, :user_id, :role, :trace_id,
                            :input_hash, :status, :latency_ms, CAST(:output_ref AS jsonb), :error_code)
                    """
                ),
                {
                    "run_id": uuid4(), "tool_id": TOOL_ID, "user_id": principal.subject,
                    "role": principal.role.value, "trace_id": trace_id,
                    "input_hash": hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest(),
                    "status": status, "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
                    "output_ref": json.dumps(output_ref, default=str), "error_code": error_code,
                },
            )
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="MCP 실행 근거를 저장하지 못했습니다.") from error


@mcp_router.get("/mcp", operation_id="mcpGet")
def mcp_get(_principal: Annotated[Principal, Security(_principal)]) -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})


@mcp_router.post("/mcp", operation_id="mcpPost")
async def mcp_post(
    request: Request,
    principal: Annotated[Principal, Security(_principal)],
    protocol_version: Annotated[str, Header(alias="MCP-Protocol-Version")],
    mcp_method: Annotated[str, Header(alias="Mcp-Method")],
    mcp_name: Annotated[str | None, Header(alias="Mcp-Name")] = None,
) -> Response:
    if not _origin_allowed(request.headers.get("Origin")):
        return _rpc_error(None, -32000, "Origin is not allowed", 403)
    if protocol_version != MCP_PROTOCOL_VERSION:
        return _rpc_error(None, -32600, "Unsupported MCP protocol version", 400)
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _rpc_error(None, -32700, "Parse error", 400)
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or "id" not in payload:
        return _rpc_error(payload.get("id") if isinstance(payload, dict) else None, -32600, "Invalid Request")
    request_id = payload["id"]
    method = payload.get("method")
    if method != mcp_method:
        return _rpc_error(request_id, -32600, "Mcp-Method header does not match the request")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return _rpc_error(request_id, -32602, "Invalid params")
    if not _has_client_info(params):
        return _rpc_error(request_id, -32602, "MCP clientInfo is required")
    engine = _engine(_database_url())

    if method == "tools/list":
        tools = []
        if principal.role.value == "hotel_analyst" and _enabled_tool(engine):
            tools.append({
                "name": TOOL_NAME,
                "title": "Get Analysis Run",
                "description": "Get one persisted Analysis Run owned by the authenticated user.",
                "inputSchema": TOOL_INPUT_SCHEMA,
                "outputSchema": TOOL_OUTPUT_SCHEMA,
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            })
        return _rpc_result(request_id, {"tools": tools})

    if method != "tools/call":
        return _rpc_error(request_id, -32601, "Method not found")
    if mcp_name != params.get("name"):
        return _rpc_error(request_id, -32600, "Mcp-Name header does not match the request")
    if params.get("name") != TOOL_NAME or not _enabled_tool(engine):
        return _rpc_error(request_id, -32602, "Unknown or disabled tool")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict) or set(arguments) != {"request_id"}:
        return _rpc_error(request_id, -32602, "request_id is required and no additional arguments are allowed")
    started = time.perf_counter()
    trace_id = request.state.trace_id
    if principal.role.value != "hotel_analyst":
        _record_run(engine, principal, trace_id, arguments, "DENIED", started, {}, "ACCESS_DENIED")
        return _rpc_error(request_id, -32001, "Tool access denied")
    try:
        run = PostgresAnalysisRepository(_database_url(), principal.subject).get_run(arguments["request_id"])
    except (ValueError, KeyError) as error:
        _record_run(engine, principal, trace_id, arguments, "FAILED", started, {}, "RUN_NOT_FOUND")
        return _rpc_result(request_id, {"content": [{"type": "text", "text": str(error)}], "isError": True})
    except AnalysisRepositoryUnavailable:
        _record_run(engine, principal, trace_id, arguments, "FAILED", started, {}, "REPOSITORY_UNAVAILABLE")
        return _rpc_result(request_id, {"content": [{"type": "text", "text": "Analysis 저장소를 사용할 수 없습니다."}], "isError": True})
    structured = json.loads(json.dumps(run, default=str))
    _record_run(
        engine, principal, trace_id, arguments, "SUCCEEDED", started,
        {key: structured.get(key) for key in ("request_id", "query_id", "artifact_id")},
    )
    return _rpc_result(request_id, {
        "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
        "structuredContent": structured,
        "isError": False,
    })
