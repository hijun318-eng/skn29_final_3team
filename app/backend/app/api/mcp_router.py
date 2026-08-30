"""MCP JSON-RPC tool 목록·호출을 origin/protocol/role 검증과 owner-scoped analysis 조회에 연결한다."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
from collections.abc import Mapping
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Security
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.analysis_repository import AnalysisRepositoryUnavailable, PostgresAnalysisRepository
from app.auth import AuthenticationError, Principal
from app.authorization import has_capability, role_is_entitled
from app.context import TokenAuthenticator, bearer_auth, token_authenticator
from app.contracts import Capability, Role
from app.database import session_scope


# 날짜처럼 보이는 값은 질문 기준일이 아니라 MCP wire protocol의 공개 version이다.
# Tool UUID·name·schema와 migration registry가 함께 바뀌지 않으면 client 호환성이 깨진다.
MCP_PROTOCOL_VERSION = "2026-07-28"
MCP_SERVER_INFO = {"name": "answervice-mcp", "version": "1.0.0"}
HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022
TOOL_ID = UUID("c4454392-2f92-54a4-ad13-b8cdaba45732")
TOOL_NAME = "analysis.get_run"
TOOL_SEMANTIC_VERSION = "1.0.0"
TOOL_DESCRIPTION = "Get one persisted Analysis Run owned by the authenticated user."
TOOL_TRANSPORT = "MCP_STREAMABLE_HTTP"
TOOL_TIMEOUT_SECONDS = 5
TOOL_REQUIRED_ROLES = (Role.ANALYST.value,)
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
    "additionalProperties": False,
}
TOOL_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

mcp_router = APIRouter()


def _database_url() -> str:
    value = os.getenv("APP_RUNTIME_DATABASE_URL", "")
    if not value:
        raise HTTPException(status_code=503, detail="MCP 저장소를 사용할 수 없습니다.")
    return value


async def _principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_auth)],
    authenticator: Annotated[TokenAuthenticator, Depends(token_authenticator)],
) -> Principal:
    try:
        return await authenticator(credentials.credentials if credentials else None)
    except AuthenticationError as error:
        headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None
        raise HTTPException(status_code=error.status_code, detail=error.message, headers=headers) from error


def _rpc_result(request_id: str | int, result: dict[str, Any]) -> JSONResponse:
    stamped = {
        **result,
        "resultType": result.get("resultType", "complete"),
        "_meta": {
            **(
                result.get("_meta")
                if isinstance(result.get("_meta"), dict)
                else {}
            ),
            "io.modelcontextprotocol/serverInfo": MCP_SERVER_INFO,
        },
    }
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": stamped})


def _rpc_error(
    request_id: str | int | None,
    code: int,
    message: str,
    status: int = 200,
    data: Any | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": error},
        status_code=status,
    )


def _origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return True
    allowed = {item.strip() for item in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if item.strip()}
    return origin in allowed


def _valid_request_id(value: Any) -> bool:
    """JSON-RPC request ID는 null·boolean이 아닌 문자열 또는 정수여야 한다."""

    return isinstance(value, (str, int)) and not isinstance(value, bool)


def _decode_mcp_header(value: str | None) -> str | None:
    """Mcp-Name의 plain ASCII 또는 표준 Base64 sentinel 값을 해석한다."""

    if value is None:
        return None
    if value.startswith("=?base64?") and value.endswith("?="):
        encoded = value[len("=?base64?") : -len("?=")]
        try:
            return base64.b64decode(encoded, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    if (
        value != value.strip()
        or any(ord(character) < 0x20 or ord(character) > 0x7E for character in value)
        or (value.startswith("=?base64?") or value.endswith("?="))
    ):
        return None
    return value


def _has_request_metadata(params: dict[str, Any], protocol_version: str) -> bool:
    """2026-07-28 stateless 요청의 version·capability metadata를 검증한다.

    최종 규격에서 clientInfo는 SHOULD이므로 누락은 허용하지만, 들어온 값은 빈 identity가
    아니어야 한다. protocolVersion과 clientCapabilities는 이전 요청 상태에서 추론하지 않는다.
    """

    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return False
    if meta.get("io.modelcontextprotocol/protocolVersion") != protocol_version:
        return False
    if not isinstance(
        meta.get("io.modelcontextprotocol/clientCapabilities"),
        dict,
    ):
        return False
    client = meta.get("io.modelcontextprotocol/clientInfo")
    if client is None:
        return True
    return bool(
        isinstance(client, dict)
        and isinstance(client.get("name"), str)
        and client["name"].strip()
        and isinstance(client.get("version"), str)
        and client["version"].strip()
    )


def _discovery_result() -> dict[str, Any]:
    """세션 없이 조회 가능한 서버 capability와 private cache 경계를 반환한다."""

    return {
        "supportedVersions": [MCP_PROTOCOL_VERSION],
        "capabilities": {"tools": {"listChanged": False}},
        "instructions": (
            "인증된 사용자가 소유한 검증 완료 분석 실행만 읽기 전용 Tool로 조회합니다."
        ),
        "ttlMs": 0,
        "cacheScope": "private",
    }


def _structured_run_output(run: dict[str, Any]) -> dict[str, Any]:
    """저장된 run을 공개 outputSchema의 최소 필드로 투영하고 타입을 검증한다."""

    stored_run = json.loads(json.dumps(run, default=str))
    structured = {
        key: stored_run.get(key)
        for key in ("request_id", "status", "trace_id", "query_id", "artifact_id")
    }
    if not _tool_output_matches_schema(structured):
        raise ValueError("analysis.get_run output contract is invalid")
    return structured


def _tool_output_matches_schema(value: Mapping[str, Any]) -> bool:
    """공개 structuredContent가 추가 필드 없이 선언 schema와 일치하는지 확인한다."""

    if set(value) != set(TOOL_OUTPUT_SCHEMA["properties"]):
        return False
    return not (
        any(
            not isinstance(value[key], str) or not value[key].strip()
            for key in ("request_id", "status", "trace_id")
        )
        or any(
            value[key] is not None
            and (
                not isinstance(value[key], str)
                or not value[key].strip()
            )
            for key in ("query_id", "artifact_id")
        )
    )


def _registry_receipt_matches(
    row: Mapping[str, Any] | None,
    principal: Principal,
) -> bool:
    """DB registry row가 코드 Tool 계약과 현재 Principal에 정확히 일치하는지 검증한다."""

    if row is None or not isinstance(principal.role, Role):
        return False
    try:
        required_roles = row["required_roles_json"]
        return bool(
            UUID(str(row["tool_id"])) == TOOL_ID
            and row["tool_code"] == TOOL_NAME
            and row["semantic_version"] == TOOL_SEMANTIC_VERSION
            and row["description"] == TOOL_DESCRIPTION
            and row["input_schema_json"] == TOOL_INPUT_SCHEMA
            and row["output_schema_json"] == TOOL_OUTPUT_SCHEMA
            and row["transport"] == TOOL_TRANSPORT
            and type(row["timeout_seconds"]) is int
            and row["timeout_seconds"] == TOOL_TIMEOUT_SECONDS
            and type(required_roles) is list
            and tuple(required_roles) == TOOL_REQUIRED_ROLES
            and role_is_entitled(principal.role, required_roles)
            and row["is_enabled"] is True
        )
    except (KeyError, TypeError, ValueError):
        return False


async def _authorized_tool(principal: Principal) -> bool:
    """Registry의 전체 계약 receipt와 현재 Principal role을 한 번에 대조한다."""

    try:
        async with session_scope(_database_url()) as session:
            result = await session.execute(
                text(
                    """
                    SELECT tool_id, tool_code, semantic_version, description,
                           input_schema_json, output_schema_json, transport,
                           timeout_seconds, required_roles_json, is_enabled
                    FROM tooling.tool_registry
                    WHERE tool_id = :tool_id AND tool_code = :tool_code
                    """
                ),
                {"tool_id": TOOL_ID, "tool_code": TOOL_NAME},
            )
            row = result.mappings().one_or_none()
            return _registry_receipt_matches(row, principal)
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="MCP Tool Registry를 사용할 수 없습니다.") from error


async def _record_run(
    principal: Principal,
    trace_id: str,
    arguments: dict[str, Any],
    status: str,
    started: float,
    output_ref: dict[str, Any],
    error_code: str | None = None,
) -> None:
    try:
        async with session_scope(_database_url()) as session:
            await session.execute(
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
async def mcp_get(_principal: Annotated[Principal, Security(_principal)]) -> Response:
    """인증은 확인하되 MCP transport를 POST로만 제한하는 405 응답을 반환한다."""
    return Response(status_code=405, headers={"Allow": "POST"})


@mcp_router.post("/mcp", operation_id="mcpPost")
async def mcp_post(
    request: Request,
    principal: Annotated[Principal, Security(_principal)],
    protocol_version: Annotated[str, Header(alias="MCP-Protocol-Version")],
    mcp_method: Annotated[str, Header(alias="Mcp-Method")],
    mcp_name: Annotated[str | None, Header(alias="Mcp-Name")] = None,
) -> Response:
    """MCP JSON-RPC 요청의 origin·버전·header·도구 권한을 검증해 한 건을 실행한다.

    현재 주체가 소유한 분석 run만 조회하며 성공·거부·실패를 모두 tool audit에 남긴다.
    프로토콜 위반은 JSON-RPC 오류로, 저장소 장애는 도구 실행 오류로 닫힌다.
    """
    if not _origin_allowed(request.headers.get("Origin")):
        return _rpc_error(None, -32600, "Origin is not allowed", 403)
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _rpc_error(None, -32700, "Parse error", 400)
    if (
        not isinstance(payload, dict)
        or payload.get("jsonrpc") != "2.0"
        or not _valid_request_id(payload.get("id"))
        or not isinstance(payload.get("method"), str)
        or not payload["method"]
    ):
        return _rpc_error(
            payload.get("id") if isinstance(payload, dict) else None,
            -32600,
            "Invalid Request",
            400,
        )
    request_id = payload["id"]
    method = payload.get("method")
    params = payload.get("params", {})
    if not isinstance(params, dict):
        return _rpc_error(request_id, -32602, "Invalid params", 400)
    meta = params.get("_meta")
    body_protocol_version = (
        meta.get("io.modelcontextprotocol/protocolVersion")
        if isinstance(meta, dict)
        else None
    )
    if not isinstance(body_protocol_version, str) or not _has_request_metadata(
        params,
        body_protocol_version,
    ):
        return _rpc_error(
            request_id,
            -32602,
            "MCP request metadata is invalid",
            400,
        )
    if protocol_version is None or protocol_version != body_protocol_version:
        return _rpc_error(
            request_id,
            HEADER_MISMATCH,
            "MCP-Protocol-Version header does not match the request",
            400,
        )
    if protocol_version != MCP_PROTOCOL_VERSION:
        return _rpc_error(
            request_id,
            UNSUPPORTED_PROTOCOL_VERSION,
            "Unsupported protocol version",
            400,
            {
                "supported": [MCP_PROTOCOL_VERSION],
                "requested": protocol_version,
            },
        )
    if mcp_method is None or method != mcp_method:
        return _rpc_error(
            request_id,
            HEADER_MISMATCH,
            "Mcp-Method header does not match the request",
            400,
        )
    decoded_name = _decode_mcp_header(mcp_name)
    if mcp_name is not None and decoded_name is None:
        return _rpc_error(
            request_id,
            HEADER_MISMATCH,
            "Mcp-Name header is malformed",
            400,
        )
    if method == "server/discover":
        if mcp_name is not None:
            return _rpc_error(
                request_id,
                HEADER_MISMATCH,
                "Mcp-Name must be omitted for server/discover",
                400,
            )
        if set(params) != {"_meta"}:
            return _rpc_error(
                request_id,
                -32602,
                "server/discover accepts only request metadata",
                400,
            )
        return _rpc_result(request_id, _discovery_result())
    if method == "tools/list":
        if mcp_name is not None:
            return _rpc_error(
                request_id,
                HEADER_MISMATCH,
                "Mcp-Name must be omitted for tools/list",
                400,
            )
        if set(params) - {"_meta", "cursor"} or "cursor" in params:
            return _rpc_error(request_id, -32602, "Invalid cursor", 400)
        tools = []
        if has_capability(principal.role, Capability.READ_ANALYSIS) and await _authorized_tool(principal):
            tools.append({
                "name": TOOL_NAME,
                "title": "Get Analysis Run",
                "description": TOOL_DESCRIPTION,
                "inputSchema": TOOL_INPUT_SCHEMA,
                "outputSchema": TOOL_OUTPUT_SCHEMA,
                "annotations": TOOL_ANNOTATIONS,
            })
        return _rpc_result(
            request_id,
            {"tools": tools, "ttlMs": 0, "cacheScope": "private"},
        )

    if method != "tools/call":
        return _rpc_error(request_id, -32601, "Method not found", 404)
    if decoded_name is None or decoded_name != params.get("name"):
        return _rpc_error(
            request_id,
            HEADER_MISMATCH,
            "Mcp-Name header does not match the request",
            400,
        )
    if set(params) - {"_meta", "name", "arguments"}:
        return _rpc_error(request_id, -32602, "Invalid tools/call params", 400)
    if params.get("name") != TOOL_NAME or not await _authorized_tool(principal):
        return _rpc_error(request_id, -32602, "Unknown or disabled tool")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict) or set(arguments) != {"request_id"}:
        return _rpc_error(request_id, -32602, "request_id is required and no additional arguments are allowed")
    try:
        UUID(arguments["request_id"])
    except (AttributeError, TypeError, ValueError):
        return _rpc_result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": "request_id는 UUID 형식이어야 합니다.",
                    }
                ],
                "isError": True,
            },
        )
    started = time.perf_counter()
    trace_id = request.state.trace_id
    if not has_capability(principal.role, Capability.READ_ANALYSIS):
        await _record_run(principal, trace_id, arguments, "DENIED", started, {}, "ACCESS_DENIED")
        return _rpc_result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": "이 Analysis 실행을 조회할 권한이 없습니다.",
                    }
                ],
                "isError": True,
            },
        )
    try:
        run = await asyncio.wait_for(
            PostgresAnalysisRepository(
                _database_url(), principal.subject
            ).get_run(arguments["request_id"]),
            timeout=TOOL_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        await _record_run(
            principal,
            trace_id,
            arguments,
            "FAILED",
            started,
            {},
            "TOOL_TIMEOUT",
        )
        return _rpc_result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": "Analysis 실행 조회 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.",
                    }
                ],
                "isError": True,
            },
        )
    except (ValueError, KeyError) as error:
        await _record_run(principal, trace_id, arguments, "FAILED", started, {}, "RUN_NOT_FOUND")
        return _rpc_result(request_id, {"content": [{"type": "text", "text": str(error)}], "isError": True})
    except AnalysisRepositoryUnavailable:
        await _record_run(principal, trace_id, arguments, "FAILED", started, {}, "REPOSITORY_UNAVAILABLE")
        return _rpc_result(request_id, {"content": [{"type": "text", "text": "Analysis 저장소를 사용할 수 없습니다."}], "isError": True})
    try:
        structured = _structured_run_output(run)
    except ValueError:
        await _record_run(
            principal,
            trace_id,
            arguments,
            "FAILED",
            started,
            {},
            "RUN_CONTRACT_INVALID",
        )
        return _rpc_result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": "Analysis 실행 결과 계약이 올바르지 않습니다.",
                    }
                ],
                "isError": True,
            },
        )
    await _record_run(
        principal, trace_id, arguments, "SUCCEEDED", started,
        {key: structured.get(key) for key in ("request_id", "query_id", "artifact_id")},
    )
    return _rpc_result(request_id, {
        "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
        "structuredContent": structured,
        "isError": False,
    })
