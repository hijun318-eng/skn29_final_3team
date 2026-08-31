from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.contracts import Role
from app.ports.mcp_tool import MCPToolDispatchError
from app.services.governed_mcp_execution import GovernedMCPToolExecutor
from app.services.mcp_tool_rate_limit import McpToolRateLimitDecision
from app.services.mcp_tool_registry import (
    MCPToolAccess,
    MCPToolDispatchResult,
    analysis_get_run_descriptor,
)


def _run_async(function):
    @wraps(function)
    def wrapper():
        return asyncio.run(function())

    return wrapper


def _quota(*, allowed: bool) -> McpToolRateLimitDecision:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    return McpToolRateLimitDecision(
        allowed=allowed,
        limit=10,
        remaining=9 if allowed else 0,
        retry_after_seconds=60,
        window_start=start,
        window_end=start + timedelta(seconds=60),
    )


@_run_async
async def test_governed_executor_orders_registry_quota_dispatch_and_success_audit() -> None:
    descriptor = analysis_get_run_descriptor(lambda: "postgresql://runtime")
    executor = GovernedMCPToolExecutor(
        (descriptor,),
        lambda: "postgresql://runtime",
    )
    registry = SimpleNamespace(
        resolve=AsyncMock(return_value=MCPToolAccess(True, True, descriptor))
    )
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = MCPToolDispatchResult(
        descriptor=descriptor,
        structured_content={
            "request_id": str(uuid4()),
            "status": "SUCCEEDED",
            "trace_id": "trace-governed",
            "query_id": None,
            "artifact_id": None,
        },
        audit_output_ref={"status": "SUCCEEDED"},
    )
    run_id = uuid4()
    executor._registry = registry
    executor._dispatcher = dispatcher
    executor._consume_quota = AsyncMock(return_value=_quota(allowed=True))
    executor._record_run = AsyncMock(return_value=run_id)
    subject_id = uuid4()
    arguments = {"request_id": str(uuid4())}

    result = await executor.execute(
        descriptor.name,
        subject_id=subject_id,
        role=Role.ANALYST,
        trace_id="trace-governed",
        arguments=arguments,
    )

    registry.resolve.assert_awaited_once_with(descriptor.name, Role.ANALYST)
    executor._consume_quota.assert_awaited_once_with(subject_id, descriptor.tool_id)
    dispatcher.dispatch.assert_awaited_once()
    assert executor._record_run.await_args.kwargs["status"] == "SUCCEEDED"
    assert result.tool_run_id == run_id


@_run_async
async def test_governed_executor_audits_access_denial_before_raising() -> None:
    descriptor = analysis_get_run_descriptor(lambda: "postgresql://runtime")
    executor = GovernedMCPToolExecutor(
        (descriptor,),
        lambda: "postgresql://runtime",
    )
    executor._registry = SimpleNamespace(
        resolve=AsyncMock(return_value=MCPToolAccess(True, False, descriptor))
    )
    executor._record_run = AsyncMock(return_value=uuid4())

    with pytest.raises(MCPToolDispatchError) as raised:
        await executor.execute(
            descriptor.name,
            subject_id=uuid4(),
            role=Role.REPORT_ADMIN,
            trace_id="trace-denied",
            arguments={"request_id": str(uuid4())},
        )

    assert raised.value.code == "ACCESS_DENIED"
    assert executor._record_run.await_args.kwargs["status"] == "DENIED"
    assert executor._record_run.await_args.kwargs["error_code"] == "ACCESS_DENIED"
