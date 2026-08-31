"""MCP Tool 호출의 principal·tool별 고정 window quota 계약을 정의한다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID


MCP_TOOL_RATE_LIMIT_QUOTA_ENV = "MCP_TOOL_RATE_LIMIT_QUOTA"
MCP_TOOL_RATE_LIMIT_WINDOW_SECONDS_ENV = "MCP_TOOL_RATE_LIMIT_WINDOW_SECONDS"
_POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807
_POSTGRES_INTEGER_MAX = 2_147_483_647


class McpToolRateLimitConfigurationError(RuntimeError):
    """누락되거나 유효하지 않은 quota 설정으로 호출을 허용할 수 없음을 알린다."""


class McpToolRateLimitUnavailable(RuntimeError):
    """영속 quota 저장소 장애 또는 손상된 응답으로 호출을 허용할 수 없음을 알린다."""


@dataclass(frozen=True)
class McpToolRateLimitSettings:
    """모든 MCP Tool에 적용할 양의 고정 window quota 설정이다."""

    quota: int
    window_seconds: int

    def __post_init__(self) -> None:
        if (
            self.quota <= 0
            or self.quota > _POSTGRES_BIGINT_MAX
            or self.window_seconds <= 0
            or self.window_seconds > _POSTGRES_INTEGER_MAX
        ):
            raise McpToolRateLimitConfigurationError(
                "MCP Tool rate limit quota and window must be positive"
            )
        try:
            # Repository TTL은 현재 window와 닫힌 직전 window 한 구간을 보존한다.
            timedelta(seconds=self.window_seconds * 2)
        except OverflowError as error:
            raise McpToolRateLimitConfigurationError(
                "MCP Tool rate limit window is too large"
            ) from error

    @classmethod
    def from_env(cls) -> "McpToolRateLimitSettings":
        """명시적인 환경 설정 두 개를 읽고 누락·비정수·비양수를 실패로 닫는다."""

        raw_quota = os.getenv(MCP_TOOL_RATE_LIMIT_QUOTA_ENV, "").strip()
        raw_window = os.getenv(MCP_TOOL_RATE_LIMIT_WINDOW_SECONDS_ENV, "").strip()
        try:
            quota = int(raw_quota)
            window_seconds = int(raw_window)
        except ValueError as error:
            raise McpToolRateLimitConfigurationError(
                "MCP Tool rate limit configuration is missing or invalid"
            ) from error
        return cls(quota=quota, window_seconds=window_seconds)


class McpToolRateLimitRepository(Protocol):
    """DB가 단일 원자 연산으로 quota를 소비하는 영속화 포트다."""

    async def consume(
        self,
        *,
        principal_subject: UUID,
        tool_id: UUID,
        quota: int,
        window_seconds: int,
    ) -> "McpToolRateLimitReceipt":
        """DB 시계로 계산한 원자 소비 결과와 reset receipt를 반환한다."""


@dataclass(frozen=True)
class McpToolRateLimitReceipt:
    """단일 DB statement가 계산한 소비 건수와 같은 시계 기준의 window 정보다."""

    request_count: int | None
    retry_after_seconds: int
    window_start: datetime
    reset_at: datetime


@dataclass(frozen=True)
class McpToolRateLimitDecision:
    """Router가 Retry-After와 잔여 quota를 손실 없이 응답할 수 있는 결정이다."""

    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    window_start: datetime
    window_end: datetime


class McpToolRateLimitService:
    """DB가 계산한 UTC 고정 window의 원자 소비 결과를 fail-closed로 해석한다."""

    def __init__(
        self,
        repository: McpToolRateLimitRepository,
        settings: McpToolRateLimitSettings,
    ) -> None:
        self._repository = repository
        self._settings = settings

    @classmethod
    def from_env(
        cls,
        repository: McpToolRateLimitRepository,
    ) -> "McpToolRateLimitService":
        """환경에서 검증된 quota 설정을 읽어 영속 저장소와 조립한다."""

        return cls(repository, McpToolRateLimitSettings.from_env())

    async def consume(
        self,
        *,
        principal_subject: UUID,
        tool_id: UUID,
    ) -> McpToolRateLimitDecision:
        """한 호출을 소비하며 저장소·설정 이상은 절대로 허용 결정으로 바꾸지 않는다.

        Window 경계와 reset 시각은 애플리케이션 replica 시계가 아니라 원자 UPSERT와 같은
        PostgreSQL statement가 계산한다.
        """

        try:
            receipt = await self._repository.consume(
                principal_subject=principal_subject,
                tool_id=tool_id,
                quota=self._settings.quota,
                window_seconds=self._settings.window_seconds,
            )
        except McpToolRateLimitUnavailable:
            raise
        except Exception as error:
            raise McpToolRateLimitUnavailable(
                "MCP Tool rate limit repository is unavailable"
            ) from error

        consumed = receipt.request_count
        if (
            (consumed is not None and not 1 <= consumed <= self._settings.quota)
            or receipt.retry_after_seconds <= 0
            or receipt.retry_after_seconds > self._settings.window_seconds
            or receipt.window_start.tzinfo is None
            or receipt.window_start.utcoffset() is None
            or receipt.reset_at.tzinfo is None
            or receipt.reset_at.utcoffset() is None
            or receipt.reset_at <= receipt.window_start
            or receipt.reset_at - receipt.window_start
            != timedelta(seconds=self._settings.window_seconds)
        ):
            raise McpToolRateLimitUnavailable(
                "MCP Tool rate limit repository returned an invalid receipt"
            )
        allowed = consumed is not None
        remaining = self._settings.quota - consumed if consumed is not None else 0
        return McpToolRateLimitDecision(
            allowed=allowed,
            limit=self._settings.quota,
            remaining=remaining,
            retry_after_seconds=receipt.retry_after_seconds,
            window_start=receipt.window_start,
            window_end=receipt.reset_at,
        )
