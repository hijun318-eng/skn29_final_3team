"""MCP JSON-RPC 목록·호출을 versioned Analysis·RAG·ML Tool 경계에 연결한다."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Mapping, Sequence
from datetime import UTC
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mcp_tool_rate_limit_repository import (
    PostgresMcpToolRateLimitRepository,
)
from app.auth import AuthenticationError, Principal
from app.context import TokenAuthenticator, bearer_auth, token_authenticator
from app.contracts import RuntimeFeature
from app.database import DatabaseConfigurationError, get_sessionmaker, session_scope
from app.ports.mcp_tool import (
    MCPToolDescriptor,
    MCPToolDispatchError,
    MCPToolInfrastructureError,
)
from app.runtime_features import runtime_feature_enabled
from app.services.mcp_agent_tools import (
    ml_predict_descriptor,
    rag_answer_descriptor,
)
from app.services.mcp_tool_registry import (
    ANALYSIS_GET_RUN_ANNOTATIONS,
    ANALYSIS_GET_RUN_DESCRIPTION,
    ANALYSIS_GET_RUN_INPUT_SCHEMA,
    ANALYSIS_GET_RUN_NAME,
    ANALYSIS_GET_RUN_OUTPUT_SCHEMA,
    ANALYSIS_GET_RUN_SEMANTIC_VERSION,
    ANALYSIS_GET_RUN_TITLE,
    ANALYSIS_GET_RUN_TIMEOUT_SECONDS,
    ANALYSIS_GET_RUN_TOOL_ID,
    MCPToolAccess,
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
TOOL_TITLE = ANALYSIS_GET_RUN_TITLE
TOOL_DESCRIPTION = ANALYSIS_GET_RUN_DESCRIPTION
TOOL_TRANSPORT = "MCP_STREAMABLE_HTTP"
TOOL_TIMEOUT_SECONDS = ANALYSIS_GET_RUN_TIMEOUT_SECONDS
TOOL_REQUIRED_ROLES = ("analyst",)
TOOL_INPUT_SCHEMA = ANALYSIS_GET_RUN_INPUT_SCHEMA
TOOL_OUTPUT_SCHEMA = ANALYSIS_GET_RUN_OUTPUT_SCHEMA
TOOL_ANNOTATIONS = ANALYSIS_GET_RUN_ANNOTATIONS

mcp_router = APIRouter()
MCPInfrastructureError = MCPToolInfrastructureError
MCP_REJECTED_TOOL_ACTION = "MCP_TOOL_CALL_REJECTED"
_SAFE_AUDIT_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MCPRejectedCallReason = Literal[
    "UNKNOWN_TOOL",
    "DISABLED_TOOL",
    "REGISTRY_CONTRACT_DRIFT",
]
_REJECTED_CALL_REASONS = frozenset(
    {"UNKNOWN_TOOL", "DISABLED_TOOL", "REGISTRY_CONTRACT_DRIFT"}
)
_REJECTED_CALL_BUCKET_PREFIX = "answervice:mcp:rejected-call:"
_MCP_RESPONSE_MEDIA_TYPES = frozenset({"application/json", "text/event-stream"})
logger = logging.getLogger(__name__)

_MCP_REQUEST_ID_SCHEMA = {
    "oneOf": [{"type": "string"}, {"type": "integer"}],
}
_MCP_REQUEST_META_SCHEMA = {
    "type": "object",
    "properties": {
        "io.modelcontextprotocol/protocolVersion": {
            "type": "string",
            "const": MCP_PROTOCOL_VERSION,
        },
        "io.modelcontextprotocol/clientCapabilities": {"type": "object"},
        "io.modelcontextprotocol/clientInfo": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "version": {"type": "string", "minLength": 1},
            },
            "required": ["name", "version"],
            "additionalProperties": True,
        },
    },
    "required": [
        "io.modelcontextprotocol/protocolVersion",
        "io.modelcontextprotocol/clientCapabilities",
    ],
    "additionalProperties": True,
}


def _mcp_request_schema(method: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """OpenAPI에 실제로 수용하는 method별 JSON-RPC request shape를 만든다."""

    return {
        "type": "object",
        "properties": {
            "jsonrpc": {"type": "string", "const": "2.0"},
            "id": _MCP_REQUEST_ID_SCHEMA,
            "method": {"type": "string", "const": method},
            "params": dict(params),
        },
        "required": ["jsonrpc", "id", "method", "params"],
        "additionalProperties": True,
    }


_MCP_METADATA_ONLY_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {"_meta": _MCP_REQUEST_META_SCHEMA},
    "required": ["_meta"],
    "additionalProperties": False,
}
_MCP_JSON_RPC_REQUEST_SCHEMA = {
    "oneOf": [
        _mcp_request_schema("server/discover", _MCP_METADATA_ONLY_PARAMS_SCHEMA),
        _mcp_request_schema("tools/list", _MCP_METADATA_ONLY_PARAMS_SCHEMA),
        _mcp_request_schema(
            "tools/call",
            {
                "type": "object",
                "properties": {
                    "_meta": _MCP_REQUEST_META_SCHEMA,
                    "name": {"type": "string", "minLength": 1},
                    "arguments": {"type": "object"},
                },
                "required": ["_meta", "name"],
                "additionalProperties": False,
            },
        ),
    ]
}
_MCP_JSON_RPC_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "jsonrpc": {"type": "string", "const": "2.0"},
        "id": _MCP_REQUEST_ID_SCHEMA,
        "result": {
            "type": "object",
            "properties": {
                "resultType": {"type": "string", "const": "complete"},
                "_meta": {"type": "object"},
            },
            "required": ["resultType", "_meta"],
        },
    },
    "required": ["jsonrpc", "id", "result"],
    "additionalProperties": False,
}
_MCP_JSON_RPC_ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "jsonrpc": {"type": "string", "const": "2.0"},
        "id": _MCP_REQUEST_ID_SCHEMA,
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "integer"},
                "message": {"type": "string"},
                "data": {},
            },
            "required": ["code", "message"],
            "additionalProperties": False,
        },
    },
    "required": ["jsonrpc", "error"],
    "additionalProperties": False,
}
_MCP_JSON_RPC_RESPONSE_SCHEMA = {
    "oneOf": [_MCP_JSON_RPC_RESULT_SCHEMA, _MCP_JSON_RPC_ERROR_SCHEMA]
}
_MCP_POST_OPENAPI_EXTRA = {
    "parameters": [
        {
            "name": "Accept",
            "in": "header",
            "required": True,
            "schema": {
                "type": "string",
                "example": "application/json, text/event-stream",
            },
        },
        {
            "name": "MCP-Protocol-Version",
            "in": "header",
            "required": True,
            "schema": {"type": "string", "const": MCP_PROTOCOL_VERSION},
        },
        {
            "name": "Mcp-Method",
            "in": "header",
            "required": True,
            "schema": {"type": "string"},
        },
        {
            "name": "Mcp-Name",
            "in": "header",
            "required": False,
            "schema": {"type": "string"},
        },
        {
            "name": "Mcp-Session-Id",
            "in": "header",
            "required": False,
            "deprecated": True,
            "description": "2026-07-28 stateless transport ignores this legacy header.",
            "schema": {"type": "string"},
        },
    ],
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": _MCP_JSON_RPC_REQUEST_SCHEMA},
        },
    },
}
_COMMON_ERROR_RESPONSE_SCHEMA = {"$ref": "#/components/schemas/ErrorResponse"}


def _mcp_openapi_response(
    description: str,
    schema: Mapping[str, Any] = _MCP_JSON_RPC_RESPONSE_SCHEMA,
) -> dict[str, Any]:
    """한 HTTP 상태의 실제 JSON 응답 계약을 OpenAPI 항목으로 만든다."""

    return {
        "description": description,
        "content": {"application/json": {"schema": dict(schema)}},
    }


_MCP_POST_RESPONSES = {
    200: _mcp_openapi_response("JSON-RPC result or Tool-level error"),
    400: _mcp_openapi_response(
        "Malformed JSON-RPC request or mirrored-header mismatch"
    ),
    401: _mcp_openapi_response(
        "Bearer authentication required",
        _COMMON_ERROR_RESPONSE_SCHEMA,
    ),
    403: _mcp_openapi_response(
        "Origin or authorization denied",
        {
            "oneOf": [
                _MCP_JSON_RPC_ERROR_SCHEMA,
                _COMMON_ERROR_RESPONSE_SCHEMA,
            ]
        },
    ),
    404: _mcp_openapi_response("JSON-RPC method not found"),
    406: _mcp_openapi_response("Required response media types are not accepted"),
    415: _mcp_openapi_response("Request body is not application/json"),
    429: {
        **_mcp_openapi_response("Tool call rate limited"),
        "headers": {
            "Retry-After": {"schema": {"type": "integer", "minimum": 1}},
            "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
        },
    },
    500: _mcp_openapi_response(
        "Unhandled server failure",
        _COMMON_ERROR_RESPONSE_SCHEMA,
    ),
    503: _mcp_openapi_response(
        "Authentication, MCP registry, quota, Tool, or audit unavailable",
        {
            "oneOf": [
                _MCP_JSON_RPC_ERROR_SCHEMA,
                _COMMON_ERROR_RESPONSE_SCHEMA,
            ]
        },
    ),
}


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


def _rpc_rate_limited(
    request_id: str | int,
    quota: McpToolRateLimitDecision,
) -> JSONResponse:
    """Tool 종류를 노출하지 않는 공통 quota 거부 응답을 만든다."""

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


def _origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return True
    allowed = {item.strip() for item in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if item.strip()}
    return origin in allowed


def _is_json_content_type(value: str | None) -> bool:
    """Charset parameter를 허용하되 JSON 이외 request media type은 거부한다."""

    if value is None:
        return False
    return value.split(";", 1)[0].strip().lower() == "application/json"


def _accepts_mcp_response_types(value: str | None) -> bool:
    """한 POST가 JSON과 request-scoped SSE 응답을 모두 수용하는지 확인한다."""

    if value is None:
        return False
    accepted: set[str] = set()
    for item in value.split(","):
        segments = [segment.strip() for segment in item.split(";")]
        if not segments or not segments[0]:
            continue
        quality = 1.0
        for parameter in segments[1:]:
            key, separator, raw_quality = parameter.partition("=")
            if separator and key.strip().lower() == "q":
                try:
                    quality = float(raw_quality.strip())
                except ValueError:
                    quality = 0.0
        if 0 < quality <= 1:
            accepted.add(segments[0].lower())
    return _MCP_RESPONSE_MEDIA_TYPES.issubset(accepted)


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
                    SELECT tool_id, tool_code, semantic_version, title, description,
                           input_schema_json, output_schema_json, annotations_json, transport,
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
        _implemented_tool_descriptors(),
        _registry_rows,
    )


def _implemented_tool_descriptors() -> tuple[MCPToolDescriptor, ...]:
    """코드 handler와 feature flag가 함께 준비된 MCP Tool만 조립한다."""

    descriptors = [analysis_get_run_descriptor(_database_url)]
    if runtime_feature_enabled(RuntimeFeature.INTERNAL_GUIDELINE):
        descriptors.append(rag_answer_descriptor(_database_url))
    if runtime_feature_enabled(RuntimeFeature.ML_PREDICTION):
        descriptors.append(ml_predict_descriptor(_database_url))
    return tuple(descriptors)


async def _tool_call_access(
    tool_name: str,
    principal: Principal,
) -> tuple[MCPToolAccess, MCPRejectedCallReason | None, str | None]:
    """한 registry snapshot으로 호출 허용 여부와 내부 거부 원인을 판정한다."""

    descriptors = _implemented_tool_descriptors()
    descriptor = next(
        (item for item in descriptors if item.name == tool_name),
        None,
    )
    if descriptor is None:
        return MCPToolAccess(False, False, None), "UNKNOWN_TOOL", None

    rows = tuple(await _registry_rows())

    async def cached_rows() -> Sequence[Mapping[str, Any]]:
        return rows

    access = await MCPToolRegistry(descriptors, cached_rows).resolve(
        tool_name,
        principal.role,
    )
    if access.known:
        return access, None, None
    row = next(
        (item for item in rows if item.get("tool_code") == descriptor.name),
        None,
    )
    if row is not None and row.get("is_enabled") is False:
        return access, "DISABLED_TOOL", descriptor.name
    return access, "REGISTRY_CONTRACT_DRIFT", None


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


def _rejected_call_quota_subject(principal_subject: UUID) -> UUID:
    """실제 subject와 분리된 결정론적 pseudonymous 거부 호출 key를 만든다."""

    return uuid5(
        NAMESPACE_URL,
        f"{_REJECTED_CALL_BUCKET_PREFIX}{principal_subject}",
    )


async def _consume_rejected_call_quota(
    principal: Principal,
) -> McpToolRateLimitDecision:
    """동일 limit/window 정책의 별도 pseudonymous counter로 감사 증폭만 제한한다."""

    try:
        repository = PostgresMcpToolRateLimitRepository(
            get_sessionmaker(_database_url())
        )
        return await McpToolRateLimitService.from_env(repository).consume(
            principal_subject=_rejected_call_quota_subject(principal.subject),
            # Table FK는 등록 Tool을 요구한다. principal keyspace를 분리했으므로
            # 정상 analysis.get_run quota row는 절대로 함께 소비되지 않는다.
            tool_id=TOOL_ID,
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
    tool_semantic_version: str = TOOL_SEMANTIC_VERSION,
) -> None:
    try:
        async with session_scope(_database_url()) as session:
            await session.execute(
                text(
                    """
                    INSERT INTO tooling.tool_runs
                        (tool_run_id, tool_id, tool_semantic_version,
                         caller_user_id, caller_role, trace_id, input_hash,
                         status, latency_ms, output_ref_json, error_code)
                    VALUES (:run_id, :tool_id, :tool_semantic_version,
                            :user_id, :role, :trace_id,
                            :input_hash, :status, :latency_ms, CAST(:output_ref AS jsonb), :error_code)
                    """
                ),
                {
                    "run_id": uuid4(), "tool_id": tool_id,
                    "tool_semantic_version": tool_semantic_version,
                    "user_id": principal.subject,
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


def _canonical_input_hash(arguments: Any) -> str:
    """원문을 보존하지 않고 결정론적 JSON 입력 영수증만 만든다."""

    canonical = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


async def _record_protocol_security_event(
    principal: Principal,
    trace_id: str,
    tool_name: str,
    arguments: Any,
    rejection_reason: MCPRejectedCallReason,
    canonical_disabled_name: str | None = None,
) -> None:
    """FK가 없는 governance 감사에 unknown·disabled 호출 시도만 기록한다."""

    try:
        if rejection_reason not in _REJECTED_CALL_REASONS:
            raise ValueError("MCP rejection reason is invalid")
        if rejection_reason == "DISABLED_TOOL":
            if canonical_disabled_name is None or not _SAFE_AUDIT_TOOL_NAME.fullmatch(
                canonical_disabled_name
            ):
                raise ValueError("disabled MCP canonical name is invalid")
            safe_name = canonical_disabled_name
        else:
            if canonical_disabled_name is not None:
                raise ValueError("MCP canonical name is not allowed for this rejection")
            safe_name = None
        name_hash = hashlib.sha256(tool_name.encode("utf-8")).hexdigest()
        details = json.dumps(
            {
                "tool_name": safe_name,
                "tool_name_sha256": name_hash,
                "tool_name_length": len(tool_name),
                "canonical_input_sha256": _canonical_input_hash(arguments),
                "rejection_reason": rejection_reason,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        async with session_scope(_database_url()) as session:
            await session.execute(
                text(
                    """
                    INSERT INTO governance.audit_events
                        (audit_event_id, actor_user_id, actor_role, action_code,
                         object_type, object_id, details_json_redacted, trace_id)
                    VALUES (:event_id, :actor_user_id, :actor_role, :action_code,
                            :object_type, :object_id,
                            CAST(:details_json_redacted AS jsonb), :trace_id)
                    """
                ),
                {
                    "event_id": uuid4(),
                    "actor_user_id": principal.subject,
                    "actor_role": principal.role.value,
                    "action_code": MCP_REJECTED_TOOL_ACTION,
                    "object_type": "MCP_TOOL",
                    "object_id": f"sha256:{name_hash}",
                    "details_json_redacted": details,
                    "trace_id": trace_id,
                },
            )
    except MCPInfrastructureError as error:
        raise MCPInfrastructureError("MCP_AUDIT_UNAVAILABLE") from error
    except (
        DatabaseConfigurationError,
        SQLAlchemyError,
        TypeError,
        ValueError,
        UnicodeError,
    ) as error:
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
    tool_semantic_version: str = TOOL_SEMANTIC_VERSION,
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
            tool_semantic_version=tool_semantic_version,
        )
    except MCPInfrastructureError as error:
        return _rpc_infrastructure_error(request_id, error)
    return None


async def _record_cancelled_run(
    principal: Principal,
    trace_id: str,
    arguments: Any,
    started: float,
    *,
    tool_id: UUID,
    tool_semantic_version: str,
) -> None:
    """요청 task 취소와 분리해 terminal cancellation receipt 저장을 끝낸다."""

    audit_task = asyncio.create_task(
        _record_run(
            principal,
            trace_id,
            arguments,
            "CANCELLED",
            started,
            {},
            "REQUEST_CANCELLED",
            tool_id=tool_id,
            tool_semantic_version=tool_semantic_version,
        )
    )
    try:
        await asyncio.shield(audit_task)
    except asyncio.CancelledError:
        # 동시에 들어온 추가 cancel도 audit child task에는 전파하지 않는다.
        try:
            await audit_task
        except Exception:
            logger.exception("MCP cancellation audit failed", extra={"trace_id": trace_id})
    except Exception:
        # 끊어진 client에 응답할 수 없으므로 감사 저장 실패를 운영 log로 남긴다.
        logger.exception("MCP cancellation audit failed", extra={"trace_id": trace_id})


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
    tool_semantic_version: str = TOOL_SEMANTIC_VERSION,
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
        tool_semantic_version=tool_semantic_version,
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


@mcp_router.get(
    "/mcp",
    operation_id="mcpGet",
    status_code=405,
    response_class=Response,
    responses={405: {"description": "GET is not supported by stateless MCP"}},
)
async def mcp_get(
    _authenticated: Annotated[Principal, Security(_principal)],
) -> Response:
    """2026-07-28에서 제거된 standalone GET stream을 405로 닫는다."""
    return Response(status_code=405, headers={"Allow": "POST"})


@mcp_router.delete(
    "/mcp",
    operation_id="mcpDelete",
    status_code=405,
    response_class=Response,
    responses={405: {"description": "DELETE is not supported by stateless MCP"}},
)
async def mcp_delete(
    _authenticated: Annotated[Principal, Security(_principal)],
) -> Response:
    """2026-07-28에서 제거된 protocol session 종료 요청을 405로 닫는다."""

    return Response(status_code=405, headers={"Allow": "POST"})


@mcp_router.post(
    "/mcp",
    operation_id="mcpPost",
    openapi_extra=_MCP_POST_OPENAPI_EXTRA,
    responses=_MCP_POST_RESPONSES,
)
async def mcp_post(
    request: Request,
    principal: Annotated[Principal, Security(_principal)],
) -> Response:
    """MCP JSON-RPC 요청의 origin·버전·header·도구 권한을 검증해 한 건을 실행한다.

    현재 주체에게 승인된 exact registry Tool만 실행하며 성공·거부·실패를 모두
    tool audit에 남긴다. 프로토콜 위반은 JSON-RPC 오류로, 저장소·runtime 장애는
    도구 실행 오류로 닫힌다.
    """
    if not _origin_allowed(request.headers.get("Origin")):
        return _rpc_error(None, -32600, "Origin is not allowed", 403)
    if not _is_json_content_type(request.headers.get("Content-Type")):
        return _rpc_error(None, -32600, "Content-Type must be application/json", 415)
    if not _accepts_mcp_response_types(request.headers.get("Accept")):
        return _rpc_error(
            None,
            -32600,
            "Accept must list application/json and text/event-stream",
            406,
        )
    protocol_version = request.headers.get("MCP-Protocol-Version")
    mcp_method = request.headers.get("Mcp-Method")
    mcp_name = request.headers.get("Mcp-Name")
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
    arguments = params.get("arguments", {})
    try:
        access, rejection_reason, canonical_disabled_name = await _tool_call_access(
            str(params.get("name")),
            principal,
        )
    except MCPInfrastructureError as error:
        return _rpc_infrastructure_error(request_id, error)
    if not access.known or access.descriptor is None:
        if rejection_reason is None:
            return _rpc_infrastructure_error(
                request_id,
                MCPInfrastructureError("MCP_REGISTRY_INVALID"),
            )
        try:
            rejected_quota = await _consume_rejected_call_quota(principal)
        except MCPInfrastructureError as error:
            return _rpc_infrastructure_error(request_id, error)
        if not rejected_quota.allowed:
            return _rpc_rate_limited(request_id, rejected_quota)
        try:
            await _record_protocol_security_event(
                principal,
                trace_id,
                str(params.get("name")),
                arguments,
                rejection_reason,
                canonical_disabled_name,
            )
        except MCPInfrastructureError as error:
            return _rpc_infrastructure_error(request_id, error)
        return _rpc_error(request_id, -32602, "Unknown or disabled tool")
    descriptor = access.descriptor
    if not access.authorized:
        try:
            rejected_quota = await _consume_rejected_call_quota(principal)
        except MCPInfrastructureError as error:
            return _rpc_infrastructure_error(request_id, error)
        if not rejected_quota.allowed:
            return _rpc_rate_limited(request_id, rejected_quota)
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
            tool_semantic_version=descriptor.semantic_version,
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
            tool_semantic_version=descriptor.semantic_version,
        )
        if audit_error is not None:
            return audit_error
        return _rpc_infrastructure_error(request_id, error)
    if not quota.allowed:
        try:
            rejected_quota = await _consume_rejected_call_quota(principal)
        except MCPInfrastructureError as error:
            return _rpc_infrastructure_error(request_id, error)
        if rejected_quota.allowed:
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
                tool_semantic_version=descriptor.semantic_version,
            )
            if audit_error is not None:
                return audit_error
        return _rpc_rate_limited(request_id, quota)
    try:
        result = await MCPToolDispatcher().dispatch(
            descriptor,
            subject_id=principal.subject,
            role=principal.role,
            trace_id=trace_id,
            arguments=arguments,
        )
    except asyncio.CancelledError:
        await _record_cancelled_run(
            principal,
            trace_id,
            arguments,
            started,
            tool_id=descriptor.tool_id,
            tool_semantic_version=descriptor.semantic_version,
        )
        raise
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
            tool_semantic_version=descriptor.semantic_version,
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
            tool_semantic_version=descriptor.semantic_version,
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
        tool_semantic_version=descriptor.semantic_version,
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
