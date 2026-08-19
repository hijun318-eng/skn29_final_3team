"""DataHub Rest.li 재조회와 외부 owner entity 사전조건을 검증한다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from metadata_aspects import iter_aspects


async def preflight_owner_entities(client: Any, bundle: Mapping[str, Any]) -> None:
    """native owner가 없으면 mutation 전에 전체 publication을 거부한다."""

    for owner in bundle["governance_entities"]["owners"]:
        entity = await client.get_entity(owner["urn"], ("corpGroupInfo", "status"))
        info = aspect_value(entity, "corpGroupInfo")
        status = optional_aspect_value(entity, "status")
        if (
            info.get("displayName") != owner["name"]
            or info.get("description") != owner["description"]
            # WHY: DataHub UI에서 새 CorpGroup을 만들면 status aspect가 없으며,
            # soft-delete된 그룹에만 status.removed=true가 기록된다. aspect가
            # 존재하는 경우에는 반드시 명시적 false여야 한다.
            or (status is not None and status.get("removed") is not False)
        ):
            raise ValueError(f"DataHub native owner precondition failed: {owner['urn']}")


async def verify_rest_aspects(client: Any, bundle: Mapping[str, Any]) -> None:
    """발행된 모든 aspect를 재조회하고 거버넌스 값을 재귀적으로 대조한다."""

    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for entity_type, urn, name, value in iter_aspects(bundle):
        grouped.setdefault((entity_type, urn), {})[name] = value
    for (_entity_type, urn), expected_aspects in grouped.items():
        entity = await client.get_entity(urn, tuple(expected_aspects))
        for name, expected in expected_aspects.items():
            assert_contains(aspect_value(entity, name), expected, f"{urn}.{name}")


def aspect_value(entity: Mapping[str, Any], name: str) -> dict[str, Any]:
    """객체형 aspect 하나를 추출하고 wire 구조가 없거나 다르면 실패한다."""

    try:
        value = entity["aspects"][name]["value"]
    except (KeyError, TypeError) as error:
        raise ValueError(f"missing DataHub aspect: {name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"invalid DataHub aspect: {name}")
    return value


def optional_aspect_value(
    entity: Mapping[str, Any], name: str
) -> dict[str, Any] | None:
    """선택 aspect가 없으면 None을, 존재하면 검증된 객체 값을 반환한다."""

    aspects = entity.get("aspects")
    if not isinstance(aspects, Mapping):
        raise ValueError("invalid DataHub entity aspects")
    if name not in aspects:
        return None
    return aspect_value(entity, name)


def assert_contains(actual: object, expected: object, context: str) -> None:
    """server 생성 field는 허용하되 거버넌스 값은 정확한 일치를 요구한다."""

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise ValueError(f"DataHub readback type mismatch: {context}")
        for key, value in expected.items():
            if key not in actual:
                raise ValueError(f"DataHub readback is missing {context}.{key}")
            assert_contains(actual[key], value, f"{context}.{key}")
        return
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ValueError(f"DataHub readback list mismatch: {context}")
        for index, value in enumerate(expected):
            assert_contains(actual[index], value, f"{context}[{index}]")
        return
    if actual != expected:
        raise ValueError(f"DataHub readback value mismatch: {context}")
