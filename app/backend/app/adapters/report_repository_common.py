"""보고서 행의 UUID·JSON·enum·block 구조를 도메인 객체로 안전하게 변환하는 공용 함수를 제공한다."""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo


def _uuid(value: str, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(f"{field}는 UUID 형식이어야 합니다.") from error


def _advance_schedule(current: datetime, cadence: str) -> datetime:
    local = current.astimezone(ZoneInfo("Asia/Seoul"))
    if cadence == "daily":
        return local + timedelta(days=1)
    if cadence == "weekly":
        return local + timedelta(days=7)
    if cadence == "monthly":
        year = local.year + (1 if local.month == 12 else 0)
        month = 1 if local.month == 12 else local.month + 1
        return local.replace(year=year, month=month, day=min(local.day, monthrange(year, month)[1]))
    raise ValueError("지원하지 않는 Report cadence입니다.")
