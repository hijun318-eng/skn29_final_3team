"""검증된 SQLGlot AST의 named placeholder를 server-owned typed literal로 치환한다.

SQL parsing과 정책 검증은 :mod:`src.ai.sql_policy`가 소유한다. 이 모듈은 전달받은 AST를
복사하고 placeholder 집합과 서버 parameter 집합의 exact match를 확인한 뒤 literal node만
교체하므로, parameter 값이 SQL 구문으로 다시 해석되는 경로를 만들지 않는다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlglot import exp


class SqlBindingErrorCode(str, Enum):
    """검증·실행 계층이 parameter 집합·값·type context 실패를 구분하는 안정된 코드다."""

    PARAMETER_SET_MISMATCH = "PARAMETER_SET_MISMATCH"
    INVALID_BINDING = "INVALID_BINDING"
    INVALID_VALUE = "INVALID_VALUE"
    INVALID_TYPE_CONTEXT = "INVALID_TYPE_CONTEXT"


class SqlBindingError(ValueError):
    """AST placeholder와 server-owned typed parameter 계약이 달라 실행 전 binding이 거부됐음을 알린다."""

    def __init__(self, code: SqlBindingErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TypedSqlParameter:
    """서버가 소유한 placeholder 값과 SQL 표현식이 요구하는 논리 타입을 보존한다.

    binder는 ``value_type``에 맞는 Python 값만 literal AST로 바꾸며, date·timestamp는
    query AST에 명시적 변환 node가 있을 때만 허용해 session 의존 암시적 변환을 차단한다.
    """

    value_type: str
    value: str | bool | int | float


def bind_sql_parameters(
    tree: exp.Expression,
    parameters: Mapping[str, TypedSqlParameter | Mapping[str, Any]],
    *,
    dialect: str = "trino",
) -> str:
    """[책임] SQLGlot AST의 named placeholder 노드를 서버 소유의 typed literal 노드로 치환하여 실행 SQL을 생성한다.
    - 입출력: SQLGlot AST(tree) 및 파라미터 맵(parameters) 수신 → 바인딩이 완료된 최종 Trino SQL 문자열 반환
    - 주의조건: 파라미터 누락/초과, 타입 불일치, date/timestamp 형식 위반 시 SqlBindingError 발생 (문자열 단순 치환 금지)
    """

    if not isinstance(tree, exp.Expression):
        raise TypeError("tree must be a parsed sqlglot Expression")
    if any(not isinstance(name, str) for name in parameters):
        raise SqlBindingError(
            SqlBindingErrorCode.INVALID_BINDING,
            "SQL parameter names must be strings",
        )

    placeholders = tuple(tree.find_all(exp.Placeholder))
    placeholder_names = {_placeholder_name(item) for item in placeholders}
    supplied_names = set(parameters)
    if placeholder_names != supplied_names:
        missing = sorted(placeholder_names - supplied_names)
        extra = sorted(supplied_names - placeholder_names)
        raise SqlBindingError(
            SqlBindingErrorCode.PARAMETER_SET_MISMATCH,
            f"SQL parameter set mismatch: missing={missing}, extra={extra}",
        )

    typed = {
        name: _coerce_parameter(name, value) for name, value in parameters.items()
    }
    bound = tree.copy()
    for placeholder in tuple(bound.find_all(exp.Placeholder)):
        name = _placeholder_name(placeholder)
        parameter = typed[name]
        _validate_type_context(name, parameter.value_type, placeholder)
        if parameter.value_type == "date":
            literal = exp.Literal.string(_validated_date_string(parameter, name))
            parent = placeholder.parent
            if isinstance(parent, exp.Cast) and getattr(parent.args.get("to"), "this", None) == exp.DataType.Type.DATE:
                placeholder.replace(literal)
            else:
                placeholder.replace(exp.Cast(this=literal, to=exp.DataType.build("date")))
        elif parameter.value_type == "timestamp":
            literal = exp.Literal.string(_validated_timestamp_string(parameter, name))
            parent = placeholder.parent
            if isinstance(parent, (exp.FromISO8601Timestamp, exp.Cast)):
                placeholder.replace(literal)
            else:
                placeholder.replace(exp.Cast(this=literal, to=exp.DataType.build("timestamp")))
        else:
            placeholder.replace(_literal(parameter, name))
    return bound.sql(dialect=dialect)


def _placeholder_name(placeholder: exp.Placeholder) -> str:
    name = placeholder.this
    if (
        not isinstance(name, str)
        or not name
        or not name.isascii()
        or not (name[0].isalpha() or name[0] == "_")
        or any(not (character.isalnum() or character == "_") for character in name)
    ):
        raise SqlBindingError(
            SqlBindingErrorCode.INVALID_BINDING,
            "SQL placeholders must use an ASCII name such as :period_start",
        )
    return name


def _coerce_parameter(
    name: str,
    value: TypedSqlParameter | Mapping[str, Any],
) -> TypedSqlParameter:
    if isinstance(value, TypedSqlParameter):
        return value
    if not isinstance(value, Mapping) or set(value) != {"value_type", "value"}:
        raise SqlBindingError(
            SqlBindingErrorCode.INVALID_BINDING,
            f"SQL parameter {name!r} must contain only value_type and value",
        )
    value_type = value["value_type"]
    if not isinstance(value_type, str):
        raise SqlBindingError(
            SqlBindingErrorCode.INVALID_BINDING,
            f"SQL parameter {name!r} has a non-string value_type",
        )
    return TypedSqlParameter(value_type=value_type, value=value["value"])


def _literal(parameter: TypedSqlParameter, name: str) -> exp.Expression:
    value_type = parameter.value_type
    value = parameter.value
    if value_type == "boolean" and isinstance(value, bool):
        return exp.Boolean(this=value)
    if value_type == "number" and _is_finite_number(value):
        return exp.Literal.number(str(value))
    if value_type == "string" and isinstance(value, str):
        return exp.Literal.string(value)
    if value_type == "date" and isinstance(value, str):
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError:
            parsed_date = None
        if parsed_date is not None and parsed_date.isoformat() == value:
            return exp.Literal.string(value)
    if value_type == "timestamp" and isinstance(value, str):
        parsed_timestamp = _parse_timestamp(value)
        if parsed_timestamp is not None:
            return exp.Literal.string(parsed_timestamp.isoformat())
    raise SqlBindingError(
        SqlBindingErrorCode.INVALID_VALUE,
        f"SQL parameter {name!r} has an invalid {value_type!r} value",
    )


def _validated_date_string(parameter: TypedSqlParameter, name: str) -> str:
    value = parameter.value
    if isinstance(value, str):
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError:
            parsed_date = None
        if parsed_date is not None and parsed_date.isoformat() == value:
            return value
    raise SqlBindingError(
        SqlBindingErrorCode.INVALID_VALUE,
        f"SQL parameter {name!r} has an invalid date value",
    )


def _validated_timestamp_string(parameter: TypedSqlParameter, name: str) -> str:
    value = parameter.value
    if isinstance(value, str):
        parsed_timestamp = _parse_timestamp(value)
        if parsed_timestamp is not None:
            return parsed_timestamp.isoformat()
    raise SqlBindingError(
        SqlBindingErrorCode.INVALID_VALUE,
        f"SQL parameter {name!r} has an invalid timestamp value",
    )


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _validate_type_context(
    name: str,
    value_type: str,
    placeholder: exp.Placeholder,
) -> None:
    if value_type not in {"date", "timestamp"}:
        return
    parent = placeholder.parent
    if value_type == "date":
        if isinstance(parent, exp.Cast):
            target = parent.args.get("to")
            if isinstance(target, exp.DataType) and target.this == exp.DataType.Type.DATE:
                return
        if isinstance(parent, (exp.Binary, exp.Between, exp.In)):
            return
    if value_type == "timestamp":
        if isinstance(parent, (exp.FromISO8601Timestamp, exp.Cast)):
            if isinstance(parent, exp.FromISO8601Timestamp):
                return
            target = parent.args.get("to")
            if isinstance(target, exp.DataType) and target.this in {
                exp.DataType.Type.TIMESTAMP,
                exp.DataType.Type.TIMESTAMPTZ,
            }:
                return
        if isinstance(parent, (exp.Binary, exp.Between, exp.In)):
            return
    raise SqlBindingError(
        SqlBindingErrorCode.INVALID_TYPE_CONTEXT,
        f"SQL parameter {name!r} requires an explicit {value_type} conversion",
    )
