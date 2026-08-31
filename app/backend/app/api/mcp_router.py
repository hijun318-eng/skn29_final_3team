"""MCP JSON-RPC tool 목록·호출을 origin/protocol/role 검증과 owner-scoped analysis 조회에 연결한다."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from datetime import UTC
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Security
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mcp_tool_rate_limit_repository import (
    PostgresMcpToolRateLimitRepository,
)
from app.auth import AuthenticationError, Principal
from app.context import TokenAuthenticator, bearer_auth, token_authenticator
from app.database import DatabaseConfigurationError, get_sessionmaker, session_scope
from app.ports.mcp_tool import (
    MCPToolDispatchError,
    MCPToolInfrastructureError,
)
from app.services.mcp_tool_registry import (
    ANALYSIS_GET_RUN_ANNOTATIONS,
    ANALYSIS_GET_RUN_DESCRIPTION,
    ANALYSIS_GET_RUN_INPUT_SCHEMA,
    ANALYSIS_GET_RUN_NAME,
    ANALYSIS_GET_RUN_OUTPUT_SCHEMA,
    ANALYSIS_GET_RUN_SEMANTIC_VERSION,
    ANALYSIS_GET_RUN_TIMEOUT_SECONDS,
    ANALYSIS_GET_RUN_TOOL_ID,
    MCPToolDispatcher,
    MCPToolRegistry,
    _analysis_get_run_output,
    analysis_get_run_descriptor,
)
from app.services.mcp_tool_rate_limit import (
    McpToolRateLimitConfigurationError,
    McpToolRateLimitDecision,
    McpToolRateLimitService,
    McpToolRateLimitUnavailable,
)


# 날짜처럼 보이는 값은 질문 기준일이 아니라 MCP wire protocol의 공개 version이다.
# Tool UUID·name·schema와 migration registry가 함께 바뀌지 않으면 client 호환성이 깨진다.
MCP_PROTOCOL_VERSION = "2026-07-28"
MCP_SERVER_INFO = {"name": "answervice-mcp", "version": "1.0.0"}
HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022
TOOL_RATE_LIMITED = 42900
TOOL_ID = ANALYSIS_GET_RUN_TOOL_ID
TOOL_NAME = ANALYSIS_GET_RUN_NAME
TOOL_SEMANTIC_VERSION = ANALYSIS_GET_RUN_SEMANTIC_VERSION
TOOL_DESCRIPTION = ANALYSIS_GET_RUN_DESCRIPTION
TOOL_TRANSPORT = "MCP_STREAMABLE_HTTP"
TOOL_TIMEOUT_SECONDS = ANALYSIS_GET_RUN_TIMEOUT_SECONDS
TOOL_REQUIRED_ROLES = ("analyst",)
TOOL_INPUT_SCHEMA = ANALYSIS_GET_RUN_INPUT_SCHEMA
TOOL_OUTPUT_SCHEMA = ANALYSIS_GET_RUN_OUTPUT_SCHEMA
TOOL_ANNOTATIONS = ANALYSIS_GET_RUN_ANNOTATIONS

mcp_router = APIRouter()
MCPInfrastructureError = MCPToolInfrastructureError


def _database_url() -> str:
    value = os.getenv("APP_RUNTIME_DATABASE_URL", "")
    if not value:
        raise MCPInfrastructureError("MCP_STORAGE_UNAVAILABLE")
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
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    payload: dict[str, Any] = {"jsonrpc": "2.0", "error": error}
    if request_id is not None:
        payload["id"] = request_id
    return JSONResponse(
        payload,
        status_code=status,
        headers=dict(headers) if headers is not None else None,
    )


def _rpc_infrastructure_error(
    request_id: str | int,
    error: MCPInfrastructureError,
) -> JSONResponse:
    """내부 저장소 장애를 MCP client가 식별 가능한 JSON-RPC 오류로 닫는다."""

    return _rpc_error(
        request_id,
        -32603,
        "Internal error",
        503,
        {"code": error.code},
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

    return dict(_analysis_get_run_output(run))


def _tool_output_matches_schema(value: Mapping[str, Any]) -> bool:
    """공개 structuredContent가 추가 필드 없이 선언 schema와 일치하는지 확인한다."""

    try:
        return dict(_analysis_get_run_output(value)) == value
    except (TypeError, ValueError):
        return False


def _registry_contract_matches(row: Mapping[str, Any] | None) -> bool:
    """DB registry row가 코드 Tool 계약과 정확히 일치하는지 검증한다."""

    return analysis_get_run_descriptor(_database_url).registry_contract_matches(row)


def _registry_receipt_matches(
    row: Mapping[str, Any] | None,
    principal: Principal,
) -> bool:
    """정확한 registry 계약에 현재 Principal entitlement까지 대조한다."""

    descriptor = analysis_get_run_descriptor(_database_url)
    return bool(
        descriptor.registry_contract_matches(row)
        and MCPToolRegistry._authorized(descriptor, principal.role)
    )


async def _registry_rows() -> Sequence[Mapping[str, Any]]:
    """Runtime DB의 registry rows를 generic registry에 전달한다."""

    try:
        async with session_scope(_database_url()) as session:
            result = await session.execute(
                text(
                    """
                    SELECT tool_id, tool_code, semantic_version, description,
                           input_schema_json, output_schema_json, transport,
                           timeout_seconds, required_roles_json, is_enabled
                    FROM tooling.tool_registry
                    """
                )
            )
            return tuple(result.mappings().all())
    except MCPInfrastructureError:
        raise
    except (DatabaseConfigurationError, SQLAlchemyError) as error:
        raise MCPInfrastructureError("MCP_REGISTRY_UNAVAILABLE") from error


def _tool_registry() -> MCPToolRegistry:
    """현재 handler가 구현된 descriptor만 runtime registry에 조립한다."""

    return MCPToolRegistry(
        (analysis_get_run_descriptor(_database_url),),
        _registry_rows,
    )


async def _tool_access(principal: Principal) -> tuple[bool, bool]:
    """기존 내부 검증 helper를 generic registry access 위에 유지한다."""

    access = await _tool_registry().resolve(TOOL_NAME, principal.role)
    return access.known, access.authorized


async def _authorized_tool(principal: Principal) -> bool:
    """Registry의 전체 계약 receipt와 현재 Principal role을 한 번에 대조한다."""

    _, authorized = await _tool_access(principal)
    return authorized


async def _consume_tool_quota(
    principal: Principal,
    tool_id: UUID,
) -> McpToolRateLimitDecision:
    """독립 DB transaction의 strict 환경 quota를 known·authorized Tool에 소비한다."""

    try:
        repository = PostgresMcpToolRateLimitRepository(
            get_sessionmaker(_database_url())
        )
        return await McpToolRateLimitService.from_env(repository).consume(
            principal_subject=principal.subject,
            tool_id=tool_id,
        )
    except (
        MCPInfrastructureError,
        DatabaseConfigurationError,
        McpToolRateLimitConfigurationError,
        McpToolRateLimitUnavailable,
    ) as error:
        raise MCPInfrastructureError("MCP_RATE_LIMIT_UNAVAILABLE") from error


async def _record_run(
    principal: Principal,
    trace_id: str,
    arguments: Any,
    status: str,
    started: float,
    output_ref: dict[str, Any],
    error_code: str | None = None,
    *,
    tool_id: UUID = TOOL_ID,
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
                    "run_id": uuid4(), "tool_id": tool_id, "user_id": principal.subject,
                    "role": principal.role.value, "trace_id": trace_id,
                    "input_hash": hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest(),
                    "status": status, "latency_ms": max(0, round((time.perf_counter() - started) * 1000)),
                    "output_ref": json.dumps(output_ref, default=str), "error_code": error_code,
                },
            )
    except MCPInfrastructureError as error:
        raise MCPInfrastructureError("MCP_AUDIT_UNAVAILABLE") from error
    except (DatabaseConfigurationError, SQLAlchemyError) as error:
        raise MCPInfrastructureError("MCP_AUDIT_UNAVAILABLE") from error


async def _audit_or_error(
    request_id: str | int,
    principal: Principal,
    trace_id: str,
    arguments: Any,
    status: str,
    started: float,
    output_ref: dict[str, Any],
    error_code: str | None = None,
    *,
    tool_id: UUID = TOOL_ID,
) -> JSONResponse | None:
    """감사 저장에 실패하면 원래 Tool 결과 대신 JSON-RPC server error를 반환한다."""

    try:
        await _record_run(
            principal,
            trace_id,
            arguments,
            status,
            started,
            output_ref,
            error_code,
            tool_id=tool_id,
        )
    except MCPInfrastructureError as error:
        return _rpc_infrastructure_error(request_id, error)
    return None


async def _audited_tool_error(
    request_id: str | int,
    principal: Principal,
    trace_id: str,
    arguments: Any,
    started: float,
    error_code: str,
    message: str,
    *,
    status: str = "FAILED",
    protocol_error: bool = False,
    tool_id: UUID = TOOL_ID,
) -> JSONResponse:
    """실패 감사를 먼저 저장하고 공개 MCP 오류 형식으로 안전하게 변환한다."""

    audit_error = await _audit_or_error(
        request_id,
        principal,
        trace_id,
        arguments,
        status,
        started,
        {},
        error_code,
        tool_id=tool_id,
    )
    if audit_error is not None:
        return audit_error
    if protocol_error:
        return _rpc_error(request_id, -32602, message)
    return _rpc_result(
        request_id,
        {
            "content": [{"type": "text", "text": message}],
            "isError": True,
        },
    )


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
        invalid_request_id = (
            payload.get("id")
            if isinstance(payload, dict) and _valid_request_id(payload.get("id"))
            else None
        )
        return _rpc_error(
            invalid_request_id,
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
        try:
            descriptors = await _tool_registry().list_authorized(principal.role)
        except MCPInfrastructureError as error:
            return _rpc_infrastructure_error(request_id, error)
        tools = [descriptor.public_definition() for descriptor in descriptors]
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
    started = time.perf_counter()
    trace_id = request.state.trace_id
    try:
        access = await _tool_registry().resolve(str(params.get("name")), principal.role)
    except MCPInfrastructureError as error:
        return _rpc_infrastructure_error(request_id, error)
    if not access.known or access.descriptor is None:
        return _rpc_error(request_id, -32602, "Unknown or disabled tool")
    arguments = params.get("arguments", {})
    descriptor = access.descriptor
    if not access.authorized:
        return await _audited_tool_error(
            request_id,
            principal,
            trace_id,
            arguments,
            started,
            "ACCESS_DENIED",
            "Unknown or disabled tool",
            status="DENIED",
            protocol_error=True,
            tool_id=descriptor.tool_id,
        )
    try:
        quota = await _consume_tool_quota(principal, descriptor.tool_id)
    except MCPInfrastructureError as error:
        audit_error = await _audit_or_error(
            request_id,
            principal,
            trace_id,
            arguments,
            "FAILED",
            started,
            {},
            error.code,
            tool_id=descriptor.tool_id,
        )
        if audit_error is not None:
            return audit_error
        return _rpc_infrastructure_error(request_id, error)
    if not quota.allowed:
        audit_error = await _audit_or_error(
            request_id,
            principal,
            trace_id,
            arguments,
            "DENIED",
            started,
            {},
            "RATE_LIMITED",
            tool_id=descriptor.tool_id,
        )
        if audit_error is not None:
            return audit_error
        return _rpc_error(
            request_id,
            TOOL_RATE_LIMITED,
            "Rate limit exceeded",
            429,
            {
                "code": "RATE_LIMITED",
                "limit": quota.limit,
                "remaining": 0,
                "retryAfterSeconds": quota.retry_after_seconds,
                "resetAt": quota.window_end.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z"),
            },
            headers={
                "Retry-After": str(quota.retry_after_seconds),
                "Cache-Control": "no-store",
            },
        )
    try:
        result = await MCPToolDispatcher().dispatch(
            descriptor,
            subject_id=principal.subject,
            role=principal.role,
            trace_id=trace_id,
            arguments=arguments,
        )
    except MCPInfrastructureError as error:
        audit_error = await _audit_or_error(
            request_id,
            principal,
            trace_id,
            arguments,
            "FAILED",
            started,
            {},
            error.code,
            tool_id=descriptor.tool_id,
        )
        if audit_error is not None:
            return audit_error
        return _rpc_infrastructure_error(request_id, error)
    except MCPToolDispatchError as error:
        return await _audited_tool_error(
            request_id,
            principal,
            trace_id,
            arguments,
            started,
            error.code,
            str(error),
            protocol_error=error.protocol_error,
            tool_id=descriptor.tool_id,
        )
    audit_error = await _audit_or_error(
        request_id,
        principal,
        trace_id,
        arguments,
        "SUCCEEDED",
        started,
        dict(result.audit_output_ref),
        tool_id=descriptor.tool_id,
    )
    if audit_error is not None:
        return audit_error
    return _rpc_result(request_id, {
        "content": [{
            "type": "text",
            "text": json.dumps(result.structured_content, ensure_ascii=False),
        }],
        "structuredContent": dict(result.structured_content),
        "isError": False,
    })
