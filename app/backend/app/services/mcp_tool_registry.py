"""Versioned MCP Tool descriptor를 registry receipt와 대조하고 결정론적으로 실행한다."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import logging
from typing import Any
from uuid import UUID

from app.adapters.analysis_repository import (
    AnalysisRepositoryUnavailable,
    PostgresAnalysisRepository,
)
from app.authorization import has_capability, role_is_entitled
from app.contracts import Capability, Role
from app.database import DatabaseConfigurationError
from app.ports.mcp_tool import (
    MCPToolDescriptor,
    MCPToolDispatchError,
    MCPToolErrorPolicy,
    MCPToolInfrastructureError,
    MCPToolInvocation,
)


ANALYSIS_GET_RUN_TOOL_ID = UUID("c4454392-2f92-54a4-ad13-b8cdaba45732")
ANALYSIS_GET_RUN_NAME = "analysis.get_run"
ANALYSIS_GET_RUN_SEMANTIC_VERSION = "1.0.0"
ANALYSIS_GET_RUN_DESCRIPTION = (
    "Get one persisted Analysis Run owned by the authenticated user."
)
ANALYSIS_GET_RUN_TIMEOUT_SECONDS = 5
ANALYSIS_GET_RUN_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"request_id": {"type": "string", "format": "uuid"}},
    "required": ["request_id"],
    "additionalProperties": False,
}
ANALYSIS_GET_RUN_OUTPUT_SCHEMA = {
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
ANALYSIS_GET_RUN_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


logger = logging.getLogger(__name__)
RegistryRowLoader = Callable[[], Awaitable[Sequence[Mapping[str, Any]]]]
DatabaseUrlFactory = Callable[[], str]


@dataclass(frozen=True)
class MCPToolAccess:
    """Tool 존재와 현재 role의 실행 권한을 구분한다."""

    known: bool
    authorized: bool
    descriptor: MCPToolDescriptor | None


@dataclass(frozen=True)
class MCPToolDispatchResult:
    """Schema 검증을 끝낸 structured content와 감사 참조다."""

    descriptor: MCPToolDescriptor
    structured_content: Mapping[str, Any]
    audit_output_ref: Mapping[str, Any]


class MCPToolRegistry:
    """Code descriptor와 DB receipt가 정확히 같은 Tool만 노출한다."""

    def __init__(
        self,
        descriptors: Sequence[MCPToolDescriptor],
        row_loader: RegistryRowLoader,
    ) -> None:
        ordered = tuple(sorted(descriptors, key=lambda item: item.name))
        if (
            not ordered
            or len({item.name for item in ordered}) != len(ordered)
            or len({item.tool_id for item in ordered}) != len(ordered)
            or not callable(row_loader)
        ):
            raise ValueError("MCP Tool registry assembly is invalid")
        self._descriptors = ordered
        self._by_name = {item.name: item for item in ordered}
        self._row_loader = row_loader

    async def _rows_by_name(self) -> dict[str, Mapping[str, Any]]:
        try:
            rows = tuple(await self._row_loader())
        except asyncio.CancelledError:
            raise
        except MCPToolInfrastructureError:
            raise
        except Exception as error:
            raise MCPToolInfrastructureError("MCP_REGISTRY_UNAVAILABLE") from error
        names = [row.get("tool_code") for row in rows]
        if any(not isinstance(name, str) or not name for name in names) or len(
            names
        ) != len(set(names)):
            raise MCPToolInfrastructureError("MCP_REGISTRY_INVALID")
        return {str(row["tool_code"]): row for row in rows}

    @staticmethod
    def _authorized(descriptor: MCPToolDescriptor, role: Role) -> bool:
        return bool(
            has_capability(role, descriptor.capability)
            and role_is_entitled(role, descriptor.roles)
        )

    async def list_authorized(self, role: Role) -> tuple[MCPToolDescriptor, ...]:
        """현재 role과 exact registry receipt를 모두 만족하는 Tool을 정렬한다."""

        rows = await self._rows_by_name()
        return tuple(
            descriptor
            for descriptor in self._descriptors
            if descriptor.registry_contract_matches(rows.get(descriptor.name))
            and self._authorized(descriptor, role)
        )

    async def resolve(self, name: str, role: Role) -> MCPToolAccess:
        """Disabled·schema drift·unknown Tool을 동일한 hidden 상태로 판정한다."""

        descriptor = self._by_name.get(name)
        if descriptor is None:
            return MCPToolAccess(False, False, None)
        rows = await self._rows_by_name()
        if not descriptor.registry_contract_matches(rows.get(name)):
            return MCPToolAccess(False, False, None)
        return MCPToolAccess(
            True,
            self._authorized(descriptor, role),
            descriptor,
        )


class MCPToolDispatcher:
    """Typed adapter·deadline·handler·output adapter를 하나의 실행 경계로 고정한다."""

    async def dispatch(
        self,
        descriptor: MCPToolDescriptor,
        *,
        subject_id: UUID,
        role: Role,
        trace_id: str,
        arguments: Any,
    ) -> MCPToolDispatchResult:
        """공통 schema·deadline·handler·결과 검증을 거쳐 Tool을 실행한다."""

        try:
            normalized_arguments = descriptor.input_adapter(arguments)
            descriptor.validate_input(normalized_arguments)
            invocation = MCPToolInvocation(
                subject_id=subject_id,
                role=role,
                trace_id=trace_id,
                arguments=normalized_arguments,
            )
        except asyncio.CancelledError:
            raise
        except MCPToolDispatchError:
            raise
        except Exception as error:
            raise MCPToolDispatchError(
                "INVALID_ARGUMENT",
                "Tool arguments do not match the declared input schema.",
                protocol_error=True,
            ) from error

        try:
            raw_output = await asyncio.wait_for(
                descriptor.handler(invocation),
                timeout=descriptor.timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError as error:
            raise MCPToolDispatchError(
                descriptor.error_policy.timeout_code,
                descriptor.error_policy.timeout_message,
            ) from error
        except MCPToolInfrastructureError:
            raise
        except MCPToolDispatchError:
            raise
        except Exception as error:
            logger.error(
                "MCP tool execution failed",
                extra={
                    "trace_id": trace_id,
                    "tool_name": descriptor.name,
                    "error_type": type(error).__name__,
                },
            )
            raise MCPToolDispatchError(
                descriptor.error_policy.unexpected_code,
                descriptor.error_policy.unexpected_message,
            ) from error

        try:
            structured = json.loads(
                json.dumps(
                    descriptor.output_adapter(raw_output),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
            if not isinstance(structured, dict):
                raise ValueError("MCP Tool structured output must be an object")
            descriptor.validate_output(structured)
            audit_ref = json.loads(
                json.dumps(
                    descriptor.audit_adapter(structured),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
            if not isinstance(audit_ref, dict):
                raise ValueError("MCP Tool audit output must be an object")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise MCPToolDispatchError(
                descriptor.error_policy.output_code,
                descriptor.error_policy.output_message,
            ) from error
        return MCPToolDispatchResult(
            descriptor=descriptor,
            structured_content=structured,
            audit_output_ref=audit_ref,
        )


def _analysis_get_run_input(arguments: Any) -> Mapping[str, Any]:
    if not isinstance(arguments, dict) or set(arguments) != {"request_id"}:
        raise MCPToolDispatchError(
            "INVALID_ARGUMENT",
            "request_id is required and no additional arguments are allowed",
            protocol_error=True,
        )
    try:
        UUID(arguments["request_id"])
    except (AttributeError, TypeError, ValueError) as error:
        raise MCPToolDispatchError(
            "INVALID_ARGUMENT",
            "request_id는 UUID 형식이어야 합니다.",
            protocol_error=True,
        ) from error
    return dict(arguments)


def _analysis_get_run_output(run: Mapping[str, Any]) -> Mapping[str, Any]:
    stored = json.loads(json.dumps(run, default=str))
    structured = {
        key: stored.get(key)
        for key in ("request_id", "status", "trace_id", "query_id", "artifact_id")
    }
    if set(structured) != set(ANALYSIS_GET_RUN_OUTPUT_SCHEMA["properties"]):
        raise ValueError("analysis.get_run output fields are invalid")
    if any(
        not isinstance(structured[key], str) or not structured[key].strip()
        for key in ("request_id", "status", "trace_id")
    ) or any(
        structured[key] is not None
        and (
            not isinstance(structured[key], str)
            or not structured[key].strip()
        )
        for key in ("query_id", "artifact_id")
    ):
        raise ValueError("analysis.get_run output contract is invalid")
    return structured


def _analysis_get_run_audit(output: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        key: output.get(key)
        for key in ("request_id", "query_id", "artifact_id")
    }


def analysis_get_run_descriptor(
    database_url_factory: DatabaseUrlFactory,
) -> MCPToolDescriptor:
    """Owner-scoped analysis.get_run handler를 기존 wire 계약과 조립한다."""

    async def _handler(invocation: MCPToolInvocation) -> Mapping[str, Any]:
        try:
            repository = PostgresAnalysisRepository(
                database_url_factory(),
                invocation.subject_id,
            )
            return await repository.get_run(invocation.arguments["request_id"])
        except asyncio.CancelledError:
            raise
        except MCPToolInfrastructureError:
            raise
        except DatabaseConfigurationError as error:
            raise MCPToolInfrastructureError("MCP_STORAGE_UNAVAILABLE") from error
        except (ValueError, KeyError) as error:
            raise MCPToolDispatchError("RUN_NOT_FOUND", str(error)) from error
        except AnalysisRepositoryUnavailable as error:
            raise MCPToolDispatchError(
                "REPOSITORY_UNAVAILABLE",
                "Analysis 저장소를 사용할 수 없습니다.",
            ) from error

    return MCPToolDescriptor(
        tool_id=ANALYSIS_GET_RUN_TOOL_ID,
        name=ANALYSIS_GET_RUN_NAME,
        semantic_version=ANALYSIS_GET_RUN_SEMANTIC_VERSION,
        title="Get Analysis Run",
        description=ANALYSIS_GET_RUN_DESCRIPTION,
        input_schema=ANALYSIS_GET_RUN_INPUT_SCHEMA,
        output_schema=ANALYSIS_GET_RUN_OUTPUT_SCHEMA,
        handler=_handler,
        input_adapter=_analysis_get_run_input,
        output_adapter=_analysis_get_run_output,
        audit_adapter=_analysis_get_run_audit,
        timeout_seconds=ANALYSIS_GET_RUN_TIMEOUT_SECONDS,
        capability=Capability.READ_ANALYSIS,
        roles=(Role.ANALYST,),
        annotations=ANALYSIS_GET_RUN_ANNOTATIONS,
        error_policy=MCPToolErrorPolicy(
            timeout_code="TOOL_TIMEOUT",
            timeout_message=(
                "Analysis 실행 조회 시간이 초과되었습니다. "
                "잠시 후 다시 시도해 주세요."
            ),
            output_code="RUN_CONTRACT_INVALID",
            output_message="Analysis 실행 결과 계약이 올바르지 않습니다.",
            unexpected_code="TOOL_EXECUTION_FAILED",
            unexpected_message="Analysis 실행을 조회하는 중 오류가 발생했습니다.",
        ),
    )
