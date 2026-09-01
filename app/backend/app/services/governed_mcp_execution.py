"""내부·HTTP 호출이 공유하는 MCP Tool 권한·quota·감사 실행 경계다."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mcp_tool_rate_limit_repository import (
    PostgresMcpToolRateLimitRepository,
)
from app.contracts import Role
from app.database import DatabaseConfigurationError, get_sessionmaker, session_scope
from app.ports.mcp_tool import (
    MCPToolDescriptor,
    MCPToolDispatchError,
    MCPToolInfrastructureError,
)
from app.services.mcp_tool_rate_limit import (
    McpToolRateLimitConfigurationError,
    McpToolRateLimitDecision,
    McpToolRateLimitService,
    McpToolRateLimitUnavailable,
)
from app.services.mcp_tool_registry import MCPToolDispatcher, MCPToolRegistry


DatabaseUrlFactory = Callable[[], str]


class MCPToolUnavailableError(RuntimeError):
    """코드 descriptor와 DB registry가 일치하는 Tool을 찾지 못했음을 나타낸다."""


class MCPToolRateLimitedError(RuntimeError):
    """영속 quota가 호출을 거부했으며 retry receipt를 보존한다."""

    def __init__(self, decision: McpToolRateLimitDecision) -> None:
        self.decision = decision
        super().__init__("MCP_TOOL_RATE_LIMITED")


@dataclass(frozen=True)
class GovernedMCPToolResult:
    """검증된 Tool 결과와 별도 commit된 실행 영수증이다."""

    descriptor: MCPToolDescriptor
    structured_content: Mapping[str, Any]
    audit_output_ref: Mapping[str, Any]
    tool_run_id: UUID


class GovernedMCPToolExecutor:
    """Registry→권한→quota→schema/deadline→audit 순서를 한 곳에서 강제한다."""

    def __init__(
        self,
        descriptors: Sequence[MCPToolDescriptor],
        database_url_factory: DatabaseUrlFactory,
        *,
        dispatcher: MCPToolDispatcher | None = None,
    ) -> None:
        if not callable(database_url_factory):
            raise ValueError("MCP database URL factory is invalid")
        self._descriptors = tuple(descriptors)
        self._database_url_factory = database_url_factory
        self._dispatcher = dispatcher or MCPToolDispatcher()
        self._registry = MCPToolRegistry(self._descriptors, self._registry_rows)

    async def resolve_descriptor(
        self,
        tool_name: str,
        role: Role,
    ) -> MCPToolDescriptor:
        """실행 전 capability probe가 exact registry·권한을 소비 없이 확인한다."""

        access = await self._registry.resolve(tool_name, role)
        if not access.known or access.descriptor is None or not access.authorized:
            raise MCPToolUnavailableError("MCP_TOOL_UNAVAILABLE")
        return access.descriptor

    async def _registry_rows(self) -> Sequence[Mapping[str, Any]]:
        try:
            async with session_scope(self._database_url_factory()) as session:
                result = await session.execute(
                    text(
                        """
                        SELECT tool_id, tool_code, semantic_version, title, description,
                               input_schema_json, output_schema_json, annotations_json,
                               transport, timeout_seconds, required_roles_json, is_enabled
                        FROM tooling.tool_registry
                        """
                    )
                )
                return tuple(result.mappings().all())
        except (DatabaseConfigurationError, SQLAlchemyError) as error:
            raise MCPToolInfrastructureError("MCP_REGISTRY_UNAVAILABLE") from error

    async def _consume_quota(
        self,
        subject_id: UUID,
        tool_id: UUID,
    ) -> McpToolRateLimitDecision:
        try:
            repository = PostgresMcpToolRateLimitRepository(
                get_sessionmaker(self._database_url_factory())
            )
            return await McpToolRateLimitService.from_env(repository).consume(
                principal_subject=subject_id,
                tool_id=tool_id,
            )
        except (
            DatabaseConfigurationError,
            McpToolRateLimitConfigurationError,
            McpToolRateLimitUnavailable,
        ) as error:
            raise MCPToolInfrastructureError("MCP_RATE_LIMIT_UNAVAILABLE") from error

    async def _record_run(
        self,
        *,
        descriptor: MCPToolDescriptor,
        subject_id: UUID,
        role: Role,
        trace_id: str,
        arguments: Any,
        status: str,
        started: float,
        output_ref: Mapping[str, Any],
        error_code: str | None = None,
    ) -> UUID:
        run_id = uuid4()
        try:
            canonical = json.dumps(
                arguments,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            serialized_output = json.dumps(
                dict(output_ref),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            async with session_scope(self._database_url_factory()) as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO tooling.tool_runs
                            (tool_run_id, tool_id, tool_semantic_version,
                             caller_user_id, caller_role, trace_id, input_hash,
                             status, latency_ms,
                             output_ref_json, error_code)
                        VALUES
                            (:run_id, :tool_id, :tool_semantic_version,
                             :subject_id, :role, :trace_id, :input_hash,
                             :status, :latency_ms,
                             CAST(:output_ref AS jsonb), :error_code)
                        """
                    ),
                    {
                        "run_id": run_id,
                        "tool_id": descriptor.tool_id,
                        "tool_semantic_version": descriptor.semantic_version,
                        "subject_id": subject_id,
                        "role": role.value,
                        "trace_id": trace_id,
                        "input_hash": hashlib.sha256(canonical).hexdigest(),
                        "status": status,
                        "latency_ms": max(
                            0,
                            round((time.perf_counter() - started) * 1000),
                        ),
                        "output_ref": serialized_output,
                        "error_code": error_code,
                    },
                )
        except (DatabaseConfigurationError, SQLAlchemyError, TypeError, ValueError) as error:
            raise MCPToolInfrastructureError("MCP_AUDIT_UNAVAILABLE") from error
        return run_id

    async def _record_cancelled(
        self,
        *,
        descriptor: MCPToolDescriptor,
        subject_id: UUID,
        role: Role,
        trace_id: str,
        arguments: Any,
        started: float,
    ) -> None:
        task = asyncio.create_task(
            self._record_run(
                descriptor=descriptor,
                subject_id=subject_id,
                role=role,
                trace_id=trace_id,
                arguments=arguments,
                status="CANCELLED",
                started=started,
                output_ref={},
                error_code="REQUEST_CANCELLED",
            )
        )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task

    async def execute(
        self,
        tool_name: str,
        *,
        subject_id: UUID,
        role: Role,
        trace_id: str,
        arguments: Any,
    ) -> GovernedMCPToolResult:
        """한 Tool을 exact registry와 현재 주체 권한으로 다시 검증해 실행한다."""

        access = await self._registry.resolve(tool_name, role)
        if not access.known or access.descriptor is None:
            raise MCPToolUnavailableError("MCP_TOOL_UNAVAILABLE")
        descriptor = access.descriptor
        started = time.perf_counter()
        if not access.authorized:
            await self._record_run(
                descriptor=descriptor,
                subject_id=subject_id,
                role=role,
                trace_id=trace_id,
                arguments=arguments,
                status="DENIED",
                started=started,
                output_ref={},
                error_code="ACCESS_DENIED",
            )
            raise MCPToolDispatchError(
                "ACCESS_DENIED",
                "Unknown or disabled tool",
                protocol_error=True,
            )
        try:
            quota = await self._consume_quota(subject_id, descriptor.tool_id)
        except MCPToolInfrastructureError as error:
            await self._record_run(
                descriptor=descriptor,
                subject_id=subject_id,
                role=role,
                trace_id=trace_id,
                arguments=arguments,
                status="FAILED",
                started=started,
                output_ref={},
                error_code=error.code,
            )
            raise
        if not quota.allowed:
            await self._record_run(
                descriptor=descriptor,
                subject_id=subject_id,
                role=role,
                trace_id=trace_id,
                arguments=arguments,
                status="DENIED",
                started=started,
                output_ref={},
                error_code="RATE_LIMITED",
            )
            raise MCPToolRateLimitedError(quota)
        try:
            dispatched = await self._dispatcher.dispatch(
                descriptor,
                subject_id=subject_id,
                role=role,
                trace_id=trace_id,
                arguments=arguments,
            )
        except asyncio.CancelledError:
            await self._record_cancelled(
                descriptor=descriptor,
                subject_id=subject_id,
                role=role,
                trace_id=trace_id,
                arguments=arguments,
                started=started,
            )
            raise
        except (MCPToolDispatchError, MCPToolInfrastructureError) as error:
            await self._record_run(
                descriptor=descriptor,
                subject_id=subject_id,
                role=role,
                trace_id=trace_id,
                arguments=arguments,
                status="FAILED",
                started=started,
                output_ref={},
                error_code=error.code,
            )
            raise
        run_id = await self._record_run(
            descriptor=descriptor,
            subject_id=subject_id,
            role=role,
            trace_id=trace_id,
            arguments=arguments,
            status="SUCCEEDED",
            started=started,
            output_ref=dispatched.audit_output_ref,
        )
        return GovernedMCPToolResult(
            descriptor=descriptor,
            structured_content=dispatched.structured_content,
            audit_output_ref=dispatched.audit_output_ref,
            tool_run_id=run_id,
        )
