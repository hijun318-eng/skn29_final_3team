"""runtime filter와 parameter에 허용되는 scalar 타입·연산자·identifier 형태를 결정론적으로 판정해 잘못된 값을 context 계약 진입 전에 차단한다."""

from __future__ import annotations

import math
from datetime import date, datetime


FILTER_OPERATORS = frozenset({"eq", "neq", "gt", "gte", "lt", "lte"})


def _value_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _typed_value_is_valid(value_type: str, value: object) -> bool:
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
    return (
        bool(value)
        and value.isascii()
        and all(character.isalnum() or character == "_" for character in value)
        and (value[0].isalpha() or value[0] == "_")
    )
