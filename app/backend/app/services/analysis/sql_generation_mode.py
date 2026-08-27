"""분석 SQL 후보 생성 경로를 실행 설정으로 고정한다."""

from __future__ import annotations

import os
from enum import Enum


SQL_GENERATION_MODE_ENV = "ANALYSIS_SQL_GENERATION_MODE"


class SqlGenerationMode(str, Enum):
    """승인된 SQL 후보를 만들 때 Node 2 사용 여부를 구분한다."""

    HYBRID = "hybrid"
    COMPILER_ONLY = "compiler_only"


def parse_sql_generation_mode(value: str | None) -> SqlGenerationMode:
    """설정 누락은 기존 동작으로 유지하고 알 수 없는 값은 시작 전에 거부한다."""

    raw = SqlGenerationMode.HYBRID.value if value is None else value
    if raw != raw.strip():
        raise ValueError(f"{SQL_GENERATION_MODE_ENV} must not contain outer whitespace")
    try:
        return SqlGenerationMode(raw)
    except ValueError as error:
        allowed = ", ".join(item.value for item in SqlGenerationMode)
        raise ValueError(
            f"{SQL_GENERATION_MODE_ENV} must be one of: {allowed}"
        ) from error


def configured_sql_generation_mode() -> SqlGenerationMode:
    """현재 process 환경에서 SQL 후보 생성 모드를 읽는다."""

    return parse_sql_generation_mode(os.getenv(SQL_GENERATION_MODE_ENV))
