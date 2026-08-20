"""런타임 필터, 파라미터 바인딩 및 스칼라 값 타입 검증 모듈.

[핵심 목적]
런타임 필터 및 SQL 바인딩 파라미터에 허용되는 스칼라 타입(boolean, number, string, date, timestamp),
비교 연산자(eq, neq, gt, gte, lt, lte), 그리고 식별자(Identifier) 명명 규칙을 결정론적으로 검증하여
잘못된 데이터나 인젝션 위험이 있는 값이 컨텍스트 계약 단계로 진입하지 못하도록 사전 차단합니다.
"""

from __future__ import annotations

import math
from datetime import date, datetime

from src.data.governance_contract import RATIO_ZERO_POLICIES

# 거버넌스 허용 비교 연산자 집합
FILTER_OPERATORS = frozenset({"eq", "neq", "gt", "gte", "lt", "lte"})

def _value_type(value: object) -> str:
    """Python 원시 객체의 스칼라 값 타입을 표준 문자열로 판정합니다.

    Args:
        value: 임의의 Python 값

    Returns:
        'boolean' | 'number' | 'string'
    """
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _typed_value_is_valid(value_type: str, value: object) -> bool:
    """주어진 값과 선언된 value_type이 일치하고 유효한 포맷인지 검증합니다.

    Args:
        value_type: 'boolean' | 'number' | 'string' | 'date' | 'timestamp'
        value: 검증 대상 값

    Returns:
        유효성 검증 성공 여부 (bool)
    """
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if value_type == "string":
        return isinstance(value, str) and bool(value)
    if value_type == "date" and isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    if value_type == "timestamp" and isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return False
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    return False


def _is_identifier(value: str) -> bool:
    """문자열이 안전한 ASCII 식별자(알파벳/숫자/언더스코어) 규칙을 만족하는지 검증합니다."""
    return (
        bool(value)
        and value.isascii()
        and all(character.isalnum() or character == "_" for character in value)
        and (value[0].isalpha() or value[0] == "_")
    )
