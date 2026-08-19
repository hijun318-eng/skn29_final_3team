"""semantic publication 계약 검사가 공유하는 원시값 validator를 제공한다."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


class SemanticMetadataError(ValueError):
    """publication 입력이 거버넌스 runtime metadata가 될 수 없음을 나타낸다."""


def mapping(value: object, context: str) -> Mapping[str, Any]:
    """계약 값을 객체 형태로 제한하고 문맥을 포함해 실패한다."""

    if not isinstance(value, Mapping):
        raise SemanticMetadataError(f"{context} must be an object")
    return value


def array(
    value: object,
    context: str,
    *,
    non_empty: bool = False,
    limit: int | None = None,
) -> list[Any]:
    """크기가 제한된 list를 요구하고 선택적 non-empty 의미를 강제한다."""

    if (
        not isinstance(value, list)
        or (non_empty and not value)
        or (limit is not None and len(value) > limit)
    ):
        qualifier = "a non-empty" if non_empty else "a bounded"
        raise SemanticMetadataError(f"{context} must be {qualifier} array")
    return value


def text(value: object, context: str) -> str:
    """숨은 양끝 공백이 없는 정규화된 비어 있지 않은 text를 요구한다."""

    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SemanticMetadataError(f"{context} must be canonical non-empty text")
    return value


def identifier(value: object, context: str) -> str:
    """계약 key에 안전한 ASCII identifier 형식만 허용한다."""

    result = text(value, context)
    if not result.isascii() or not result.isidentifier():
        raise SemanticMetadataError(f"{context} must be an ASCII identifier")
    return result


def fqn(value: object, context: str) -> str:
    """정확히 세 부분으로 구성된 Trino fully qualified name을 요구한다."""

    result = text(value, context)
    if len(result.split(".")) != 3 or any(not part for part in result.split(".")):
        raise SemanticMetadataError(f"{context} must be a three-part Trino FQN")
    return result


def urn(value: object, prefix: str, context: str) -> str:
    """예상한 DataHub entity type의 비어 있지 않은 URN만 허용한다."""

    result = text(value, context)
    if not result.startswith(prefix) or result == prefix:
        raise SemanticMetadataError(f"{context} has an invalid entity type")
    return result


def unique_texts(
    value: object,
    context: str,
    *,
    non_empty: bool = False,
    limit: int = 128,
) -> tuple[str, ...]:
    """정규 문자열 sequence를 검증·중복 제거하고 최대 크기를 제한한다."""

    items = tuple(
        text(item, context)
        for item in array(value, context, non_empty=non_empty, limit=limit)
    )
    if len(items) != len(set(items)):
        raise SemanticMetadataError(f"{context} must contain unique values")
    return items


def exact_keys(
    value: Mapping[str, Any], expected: Iterable[str], context: str
) -> None:
    """계약에서 누락된 field와 예상하지 않은 field를 모두 거부한다."""

    expected_set = set(expected)
    if set(value) != expected_set:
        raise SemanticMetadataError(
            f"{context} keys differ: "
            f"missing={sorted(expected_set - set(value))}, "
            f"extra={sorted(set(value) - expected_set)}"
        )
