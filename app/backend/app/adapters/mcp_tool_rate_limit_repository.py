"""PostgreSQL 단일 statement로 MCP Tool fixed-window quota를 소비하고 정리한다."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.mcp_tool_rate_limit import (
    McpToolRateLimitReceipt,
    McpToolRateLimitUnavailable,
)


_OPPORTUNISTIC_CLEANUP_BATCH_SIZE = 25

_CONSUME_SQL = """
WITH observed AS MATERIALIZED (
    SELECT clock_timestamp() AS observed_at
), current_window AS MATERIALIZED (
    SELECT observed_at,
           to_timestamp(
               floor(extract(epoch FROM observed_at) / :window_seconds)
               * :window_seconds
           ) AS window_start
    FROM observed
), expired AS MATERIALIZED (
    SELECT quota.principal_subject, quota.tool_id, quota.window_start
    FROM tooling.tool_rate_limit_windows AS quota
    CROSS JOIN current_window
    WHERE quota.expires_at <= current_window.observed_at
      AND quota.window_start <> current_window.window_start
    ORDER BY quota.expires_at, quota.principal_subject,
             quota.tool_id, quota.window_start
    LIMIT :cleanup_batch_size
    FOR UPDATE OF quota SKIP LOCKED
), pruned AS (
    DELETE FROM tooling.tool_rate_limit_windows AS quota
    USING expired
    WHERE quota.principal_subject = expired.principal_subject
      AND quota.tool_id = expired.tool_id
      AND quota.window_start = expired.window_start
    RETURNING 1
), consumed AS (
    INSERT INTO tooling.tool_rate_limit_windows (
        principal_subject, tool_id, window_start, request_count, expires_at
    )
    SELECT :principal_subject, :tool_id, window_start, 1,
           window_start + make_interval(secs => :retention_seconds)
    FROM current_window
    WHERE true
    ON CONFLICT (principal_subject, tool_id, window_start)
    DO UPDATE SET
        request_count = tooling.tool_rate_limit_windows.request_count + 1,
        expires_at = GREATEST(
            tooling.tool_rate_limit_windows.expires_at,
            EXCLUDED.expires_at
        ),
        updated_at = clock_timestamp()
    WHERE tooling.tool_rate_limit_windows.request_count < :quota
    RETURNING request_count
)
SELECT consumed.request_count,
       current_window.window_start,
       current_window.window_start
           + make_interval(secs => :window_seconds) AS reset_at,
       greatest(
           1,
           ceil(extract(epoch FROM (
               current_window.window_start
                   + make_interval(secs => :window_seconds)
                   - current_window.observed_at
           )))::integer
       ) AS retry_after_seconds
FROM current_window
LEFT JOIN consumed ON true
"""

_CLEANUP_SQL = """
WITH expired AS (
    SELECT principal_subject, tool_id, window_start
    FROM tooling.tool_rate_limit_windows
    WHERE expires_at <= clock_timestamp()
    ORDER BY expires_at, principal_subject, tool_id, window_start
    LIMIT :batch_size
    FOR UPDATE SKIP LOCKED
)
DELETE FROM tooling.tool_rate_limit_windows AS quota
USING expired
WHERE quota.principal_subject = expired.principal_subject
  AND quota.tool_id = expired.tool_id
  AND quota.window_start = expired.window_start
RETURNING 1
"""


class PostgresMcpToolRateLimitRepository:
    """각 연산을 독립 transaction으로 commit해 후속 Tool 실패와 quota를 분리한다."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def consume(
        self,
        *,
        principal_subject: UUID,
        tool_id: UUID,
        quota: int,
        window_seconds: int,
    ) -> McpToolRateLimitReceipt:
        """한 INSERT/UPSERT에서 quota 조건과 증가를 함께 적용한다."""

        try:
            async with self._session_factory.begin() as session:
                result = await session.execute(
                    text(_CONSUME_SQL),
                    {
                        "principal_subject": principal_subject,
                        "tool_id": tool_id,
                        "quota": quota,
                        "window_seconds": window_seconds,
                        "retention_seconds": window_seconds * 2,
                        "cleanup_batch_size": _OPPORTUNISTIC_CLEANUP_BATCH_SIZE,
                    },
                )
                row = result.mappings().one()
        except SQLAlchemyError as error:
            raise McpToolRateLimitUnavailable(
                "MCP Tool rate limit storage is unavailable"
            ) from error
        consumed = row["request_count"]
        return McpToolRateLimitReceipt(
            request_count=int(consumed) if consumed is not None else None,
            retry_after_seconds=int(row["retry_after_seconds"]),
            window_start=row["window_start"],
            reset_at=row["reset_at"],
        )

    async def cleanup_expired(
        self,
        *,
        batch_size: int = 500,
    ) -> int:
        """TTL이 지난 row를 작은 SKIP LOCKED batch로 지워 요청 경로와 경합을 제한한다."""

        if batch_size <= 0:
            raise ValueError("MCP Tool rate limit cleanup batch size must be positive")
        try:
            async with self._session_factory.begin() as session:
                result = await session.execute(
                    text(_CLEANUP_SQL),
                    {
                        "batch_size": batch_size,
                    },
                )
                deleted = len(result.scalars().all())
        except SQLAlchemyError as error:
            raise McpToolRateLimitUnavailable(
                "MCP Tool rate limit cleanup is unavailable"
            ) from error
        return deleted
