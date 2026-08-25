"""인증된 세션의 MCP 요청을 승인 Tool Registry와 감사 경계로 전달한다."""

from __future__ import annotations

import json
import os
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response

from app.context import session_context
from app.contracts import RequestContext
from app.services.mcp_tool_service import McpToolError, McpToolService


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


def _database_url() -> str:
    value = os.getenv("APP_RUNTIME_DATABASE_URL", "").strip()
    if not value:
        raise McpToolError(
            "REGISTRY_UNAVAILABLE", "MCP repository is unavailable.", -32000
        )
    return value


def _rpc_result(request_id: str | int, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def _rpc_error(
    request_id: str | int | None,
    code: int,
    message: str,
    status: int = 200,
) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=status,
    )


def _origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return True
    allowed = {
        item.strip()
        for item in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
        if item.strip()
    }
    return origin in allowed


def _client_info(params: dict[str, Any]) -> dict[str, Any] | None:
    direct = params.get("clientInfo")
    meta = params.get("_meta")
    nested = (
        meta.get("io.modelcontextprotocol/clientInfo")
        if isinstance(meta, dict)
        else None
    )
    client = direct if isinstance(direct, dict) else nested
    if not isinstance(client, dict):
        return None
    if not isinstance(client.get("name"), str) or not client["name"].strip():
        return None
    if not isinstance(client.get("version"), str) or not client["version"].strip():
        return None
    return client


def _has_client_info(params: dict[str, Any]) -> bool:
    """Keep the established public protocol helper while accepting direct clientInfo."""

    return _client_info(params) is not None


@mcp_router.get("/mcp", operation_id="mcpGet")
async def mcp_get(
    _context: Annotated[RequestContext, Depends(session_context)],
) -> Response:
    """인증은 확인하되 MCP 전송은 POST만 허용한다는 405 계약을 반환한다."""

    return Response(status_code=405, headers={"Allow": "POST"})


@mcp_router.post("/mcp", operation_id="mcpPost")
async def mcp_post(
    request: Request,
    context: Annotated[RequestContext, Depends(session_context)],
    protocol_version: Annotated[str, Header(alias="MCP-Protocol-Version")],
    mcp_method: Annotated[str, Header(alias="Mcp-Method")],
    mcp_name: Annotated[str | None, Header(alias="Mcp-Name")] = None,
) -> Response:
    """JSON-RPC 헤더와 clientInfo를 검증한 뒤 권한이 승인된 Tool만 실행한다."""
    if not _origin_allowed(request.headers.get("Origin")):
        return _rpc_error(None, -32000, "Origin is not allowed", 403)
    if protocol_version != MCP_PROTOCOL_VERSION:
        return _rpc_error(None, -32600, "Unsupported MCP protocol version", 400)
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _rpc_error(None, -32700, "Parse error", 400)
    if (
        not isinstance(payload, dict)
        or payload.get("jsonrpc") != "2.0"
        or "id" not in payload
    ):
        return _rpc_error(
            payload.get("id") if isinstance(payload, dict) else None,
            -32600,
            "Invalid Request",
        )
    request_id = payload["id"]
    method = payload.get("method")
    if method != mcp_method:
        return _rpc_error(
            request_id, -32600, "Mcp-Method header does not match the request"
        )
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return _rpc_error(request_id, -32602, "Invalid params")
    if not _has_client_info(params):
        return _rpc_error(request_id, -32602, "MCP clientInfo is required")

    if method == "initialize":
        if params.get("protocolVersion") != MCP_PROTOCOL_VERSION:
            return _rpc_error(
                request_id, -32602, "Unsupported requested protocol version"
            )
        return _rpc_result(
            request_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "answervice", "version": "3.4"},
            },
        )

    try:
        service = McpToolService(_database_url())
        if method == "tools/list":
            return _rpc_result(request_id, {"tools": await service.list_tools(context)})
        if method != "tools/call":
            return _rpc_error(request_id, -32601, "Method not found")
        if mcp_name != params.get("name"):
            return _rpc_error(
                request_id,
                -32600,
                "Mcp-Name header does not match the request",
            )
        output = await service.call(
            params.get("name"), params.get("arguments"), context
        )
    except McpToolError as error:
        if error.rpc_code is not None:
            return _rpc_error(request_id, error.rpc_code, str(error))
        return _rpc_result(
            request_id,
            {
                "content": [{"type": "text", "text": str(error)}],
                "isError": True,
                "_meta": {
                    "status": "error",
                    "error_code": error.code,
                    "trace_id": context.trace_id,
                },
            },
        )
    structured = json.loads(json.dumps(output, default=str))
    return _rpc_result(
        request_id,
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(structured, ensure_ascii=False),
                }
            ],
            "structuredContent": structured,
            "isError": False,
            "_meta": {
                "status": "ok",
                "error_code": None,
                "trace_id": context.trace_id,
            },
        },
    )
