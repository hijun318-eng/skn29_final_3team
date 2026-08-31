from __future__ import annotations

import asyncio
import os
import unittest
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mcp_tool_rate_limit_repository import (
    PostgresMcpToolRateLimitRepository,
)
from app.services.mcp_tool_rate_limit import (
    MCP_TOOL_RATE_LIMIT_QUOTA_ENV,
    MCP_TOOL_RATE_LIMIT_WINDOW_SECONDS_ENV,
    McpToolRateLimitConfigurationError,
    McpToolRateLimitReceipt,
    McpToolRateLimitService,
    McpToolRateLimitSettings,
    McpToolRateLimitUnavailable,
)


WINDOW_START = datetime(2026, 8, 31, 3, 0, tzinfo=UTC)


class _StaticRepository:
    def __init__(self, receipt: McpToolRateLimitReceipt | Exception) -> None:
        self.receipt = receipt
        self.calls: list[dict[str, object]] = []

    async def consume(self, **parameters: object) -> McpToolRateLimitReceipt:
        self.calls.append(parameters)
        if isinstance(self.receipt, Exception):
            raise self.receipt
        return self.receipt


class _AtomicRepository:
    """동시 service 호출의 허용/거부 해석을 결정론적으로 검증하는 DB 계약 대역이다."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._counts: dict[tuple[UUID, UUID], int] = {}

    async def consume(
        self,
        *,
        principal_subject: UUID,
        tool_id: UUID,
        quota: int,
        window_seconds: int,
    ) -> McpToolRateLimitReceipt:
        async with self._lock:
            await asyncio.sleep(0)
            key = (principal_subject, tool_id)
            current = self._counts.get(key, 0)
            consumed = None
            if current < quota:
                current += 1
                self._counts[key] = current
                consumed = current
        return McpToolRateLimitReceipt(
            request_count=consumed,
            retry_after_seconds=window_seconds,
            window_start=WINDOW_START,
            reset_at=WINDOW_START + timedelta(seconds=window_seconds),
        )


class McpToolRateLimitServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_settings_require_explicit_positive_integer_environment(self) -> None:
        valid = {
            MCP_TOOL_RATE_LIMIT_QUOTA_ENV: " 25 ",
            MCP_TOOL_RATE_LIMIT_WINDOW_SECONDS_ENV: "60",
        }
        with patch.dict(os.environ, valid, clear=True):
            self.assertEqual(
                McpToolRateLimitSettings(quota=25, window_seconds=60),
                McpToolRateLimitSettings.from_env(),
            )

        for environment in (
            {},
            {MCP_TOOL_RATE_LIMIT_QUOTA_ENV: "0", MCP_TOOL_RATE_LIMIT_WINDOW_SECONDS_ENV: "60"},
            {MCP_TOOL_RATE_LIMIT_QUOTA_ENV: "5", MCP_TOOL_RATE_LIMIT_WINDOW_SECONDS_ENV: "-1"},
            {MCP_TOOL_RATE_LIMIT_QUOTA_ENV: "five", MCP_TOOL_RATE_LIMIT_WINDOW_SECONDS_ENV: "60"},
            {
                MCP_TOOL_RATE_LIMIT_QUOTA_ENV: str(2**63),
                MCP_TOOL_RATE_LIMIT_WINDOW_SECONDS_ENV: "60",
            },
            {
                MCP_TOOL_RATE_LIMIT_QUOTA_ENV: "5",
                MCP_TOOL_RATE_LIMIT_WINDOW_SECONDS_ENV: str(2**31),
            },
        ):
            with self.subTest(environment=environment), patch.dict(
                os.environ, environment, clear=True
            ):
                with self.assertRaises(McpToolRateLimitConfigurationError):
                    McpToolRateLimitSettings.from_env()

    async def test_decision_uses_database_reset_receipt_without_application_clock(self) -> None:
        receipt = McpToolRateLimitReceipt(
            request_count=2,
            retry_after_seconds=17,
            window_start=WINDOW_START,
            reset_at=WINDOW_START + timedelta(seconds=30),
        )
        repository = _StaticRepository(receipt)
        service = McpToolRateLimitService(
            repository,
            McpToolRateLimitSettings(quota=5, window_seconds=30),
        )
        principal, tool = uuid4(), uuid4()

        decision = await service.consume(
            principal_subject=principal,
            tool_id=tool,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(3, decision.remaining)
        self.assertEqual(17, decision.retry_after_seconds)
        self.assertEqual(WINDOW_START, decision.window_start)
        self.assertEqual(WINDOW_START + timedelta(seconds=30), decision.window_end)
        self.assertEqual(
            [{
                "principal_subject": principal,
                "tool_id": tool,
                "quota": 5,
                "window_seconds": 30,
            }],
            repository.calls,
        )

    async def test_none_count_is_denied_and_preserves_retry_after(self) -> None:
        repository = _StaticRepository(
            McpToolRateLimitReceipt(
                request_count=None,
                retry_after_seconds=9,
                window_start=WINDOW_START,
                reset_at=WINDOW_START + timedelta(seconds=30),
            )
        )
        decision = await McpToolRateLimitService(
            repository,
            McpToolRateLimitSettings(quota=1, window_seconds=30),
        ).consume(principal_subject=uuid4(), tool_id=uuid4())

        self.assertFalse(decision.allowed)
        self.assertEqual(0, decision.remaining)
        self.assertEqual(9, decision.retry_after_seconds)

    async def test_repository_error_and_invalid_receipt_fail_closed(self) -> None:
        settings = McpToolRateLimitSettings(quota=2, window_seconds=30)
        invalid_receipts = (
            McpToolRateLimitReceipt(3, 1, WINDOW_START, WINDOW_START + timedelta(seconds=30)),
            McpToolRateLimitReceipt(1, 0, WINDOW_START, WINDOW_START + timedelta(seconds=30)),
            McpToolRateLimitReceipt(1, 31, WINDOW_START, WINDOW_START + timedelta(seconds=30)),
            McpToolRateLimitReceipt(1, 1, WINDOW_START, WINDOW_START),
            McpToolRateLimitReceipt(1, 1, WINDOW_START, WINDOW_START + timedelta(seconds=31)),
        )
        for receipt in invalid_receipts:
            with self.subTest(receipt=receipt):
                with self.assertRaises(McpToolRateLimitUnavailable):
                    await McpToolRateLimitService(
                        _StaticRepository(receipt), settings
                    ).consume(principal_subject=uuid4(), tool_id=uuid4())

        with self.assertRaises(McpToolRateLimitUnavailable):
            await McpToolRateLimitService(
                _StaticRepository(RuntimeError("database unavailable")), settings
            ).consume(principal_subject=uuid4(), tool_id=uuid4())

    async def test_concurrent_calls_never_allow_more_than_quota_per_principal_tool(self) -> None:
        repository = _AtomicRepository()
        service = McpToolRateLimitService(
            repository,
            McpToolRateLimitSettings(quota=7, window_seconds=60),
        )
        principal, tool = uuid4(), uuid4()

        decisions = await asyncio.gather(*(
            service.consume(principal_subject=principal, tool_id=tool)
            for _ in range(40)
        ))

        self.assertEqual(7, sum(decision.allowed for decision in decisions))
        self.assertEqual(33, sum(not decision.allowed for decision in decisions))
        self.assertEqual(set(range(7)), {d.remaining for d in decisions if d.allowed})

        other_tool_id = uuid4()
        other_tool = await asyncio.gather(*(
            service.consume(principal_subject=principal, tool_id=other_tool_id)
            for _ in range(9)
        ))
        self.assertEqual(7, sum(decision.allowed for decision in other_tool))


class _Mappings:
    def __init__(self, row: Mapping[str, object]) -> None:
        self._row = row

    def one(self) -> Mapping[str, object]:
        return self._row


class _Scalars:
    def __init__(self, values: list[int]) -> None:
        self._values = values

    def all(self) -> list[int]:
        return self._values


class _Result:
    def __init__(
        self,
        *,
        row: Mapping[str, object] | None = None,
        values: list[int] | None = None,
    ) -> None:
        self._row = row or {}
        self._values = values or []

    def mappings(self) -> _Mappings:
        return _Mappings(self._row)

    def scalars(self) -> _Scalars:
        return _Scalars(self._values)


class _RecordingSession:
    def __init__(self, results: list[_Result | Exception]) -> None:
        self._results = results
        self.executions: list[tuple[str, dict[str, object]]] = []

    async def execute(self, statement: object, parameters: dict[str, object]) -> _Result:
        self.executions.append((str(statement), parameters))
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _Transaction:
    def __init__(self, session: _RecordingSession) -> None:
        self._session = session

    async def __aenter__(self) -> _RecordingSession:
        return self._session

    async def __aexit__(self, *_: object) -> None:
        return None


class _SessionFactory:
    def __init__(self, session: _RecordingSession) -> None:
        self._session = session

    def begin(self) -> _Transaction:
        return _Transaction(self._session)


class PostgresMcpToolRateLimitRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_consume_is_one_database_clocked_atomic_upsert_statement(self) -> None:
        row = {
            "request_count": 4,
            "retry_after_seconds": 12,
            "window_start": WINDOW_START,
            "reset_at": WINDOW_START + timedelta(seconds=30),
        }
        session = _RecordingSession([_Result(row=row)])
        repository = PostgresMcpToolRateLimitRepository(_SessionFactory(session))  # type: ignore[arg-type]
        principal, tool = uuid4(), uuid4()

        receipt = await repository.consume(
            principal_subject=principal,
            tool_id=tool,
            quota=5,
            window_seconds=30,
        )

        self.assertEqual(4, receipt.request_count)
        self.assertEqual(1, len(session.executions))
        sql, parameters = session.executions[0]
        normalized = " ".join(sql.upper().split())
        for fragment in (
            "CLOCK_TIMESTAMP()",
            "AS MATERIALIZED",
            "FLOOR(EXTRACT(EPOCH FROM OBSERVED_AT) / :WINDOW_SECONDS)",
            "INSERT INTO TOOLING.TOOL_RATE_LIMIT_WINDOWS",
            "ON CONFLICT (PRINCIPAL_SUBJECT, TOOL_ID, WINDOW_START)",
            "DO UPDATE SET",
            "REQUEST_COUNT = TOOLING.TOOL_RATE_LIMIT_WINDOWS.REQUEST_COUNT + 1",
            "WHERE TOOLING.TOOL_RATE_LIMIT_WINDOWS.REQUEST_COUNT < :QUOTA",
            "RETURNING REQUEST_COUNT",
            "LEFT JOIN CONSUMED ON TRUE",
            "EXPIRED AS MATERIALIZED",
            "LIMIT :CLEANUP_BATCH_SIZE",
            "FOR UPDATE OF QUOTA SKIP LOCKED",
            "PRUNED AS",
            "DELETE FROM TOOLING.TOOL_RATE_LIMIT_WINDOWS AS QUOTA",
            "QUOTA.WINDOW_START <> CURRENT_WINDOW.WINDOW_START",
        ):
            self.assertIn(fragment, normalized)
        self.assertEqual(
            {
                "principal_subject": principal,
                "tool_id": tool,
                "quota": 5,
                "window_seconds": 30,
                "retention_seconds": 60,
                "cleanup_batch_size": 25,
            },
            parameters,
        )

    async def test_consume_wraps_database_failure_as_fail_closed_unavailable(self) -> None:
        session = _RecordingSession([SQLAlchemyError("database down")])
        repository = PostgresMcpToolRateLimitRepository(_SessionFactory(session))  # type: ignore[arg-type]

        with self.assertRaises(McpToolRateLimitUnavailable):
            await repository.consume(
                principal_subject=uuid4(),
                tool_id=uuid4(),
                quota=5,
                window_seconds=30,
            )

    async def test_cleanup_is_bounded_database_clocked_and_skip_locked(self) -> None:
        session = _RecordingSession([_Result(values=[1, 1, 1])])
        repository = PostgresMcpToolRateLimitRepository(_SessionFactory(session))  # type: ignore[arg-type]

        self.assertEqual(3, await repository.cleanup_expired(batch_size=25))
        sql, parameters = session.executions[0]
        normalized = " ".join(sql.upper().split())
        self.assertIn("EXPIRES_AT <= CLOCK_TIMESTAMP()", normalized)
        self.assertIn("LIMIT :BATCH_SIZE", normalized)
        self.assertIn("FOR UPDATE SKIP LOCKED", normalized)
        self.assertEqual({"batch_size": 25}, parameters)
        with self.assertRaises(ValueError):
            await repository.cleanup_expired(batch_size=0)


if __name__ == "__main__":
    unittest.main()
