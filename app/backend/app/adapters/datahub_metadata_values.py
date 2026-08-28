"""DataHub runtime 거버넌스의 문자열·URN·checksum·native aspect를 fail-closed로 검증한다."""

from __future__ import annotations

from typing import Any


class GovernedMetadataError(ValueError):
    """실시간 DataHub metadata가 누락되었거나 서로 모순되어 분석에 사용할 수 없음을 알린다."""


def custom_properties(value: object) -> dict[str, str]:
    """DataHub ``customProperties`` 배열을 유일한 문자열 key/value dict로 바꾸고 중복·형식 오류를 거부한다."""
    if not isinstance(value, list):
        raise GovernedMetadataError("DataHub customProperties must be an array")
    result: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict) or set(item) != {"key", "value"}:
            raise GovernedMetadataError("DataHub custom property is invalid")
        key, item_value = item["key"], item["value"]
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(item_value, str)
            or key in result
        ):
            raise GovernedMetadataError("DataHub custom property identity is invalid")
        result[key] = item_value
    return result


def dataset_has_runtime_governance(value: object) -> bool:
    """dataset이 Answervice contract version 속성을 명시했는지 안전하게 판별하며 malformed 값은 후보에서 제외한다."""
    if not isinstance(value, dict) or not isinstance(value.get("properties"), dict):
        return False
    try:
        properties = custom_properties(value["properties"].get("customProperties"))
    except GovernedMetadataError:
        return False
    return "answervice.contract_version" in properties


def term_has_runtime_governance(value: object) -> bool:
    """Glossary Term이 metric id 또는 rule 속성을 가진 runtime 관리 대상인지 형식 오류 없이 판별한다."""
    if not isinstance(value, dict) or not isinstance(
        value.get("glossaryTermInfo"), dict
    ):
        return False
    try:
        properties = custom_properties(
            value["glossaryTermInfo"].get("customProperties")
        )
    except GovernedMetadataError:
        return False
    return (
        "answervice.metric_rule" in properties
        or "answervice.metric_id" in properties
        or "answervice.term_kind" in properties
    )


def dimension_member_term_record(value: object) -> bool:
    """runtime 관리 Term이 Dimension Member로 명시됐는지 판별한다."""

    if not isinstance(value, dict) or not isinstance(
        value.get("glossaryTermInfo"), dict
    ):
        return False
    try:
        properties = custom_properties(
            value["glossaryTermInfo"].get("customProperties")
        )
    except GovernedMetadataError:
        return False
    return properties.get("answervice.term_kind") == "DIMENSION_MEMBER"


def term_urns(value: object) -> frozenset[str]:
    """schema·dataset의 glossary association에서 유일한 Term URN 집합을 추출하고 중복 연결은 거부한다."""
    if value is None:
        return frozenset()
    if not isinstance(value, dict) or not isinstance(value.get("terms"), list):
        raise GovernedMetadataError("DataHub glossary term association is invalid")
    urns = []
    for item in value["terms"]:
        term = item.get("term") if isinstance(item, dict) else None
        urn = term.get("urn") if isinstance(term, dict) else None
        urns.append(required_text(urn, "associated glossary term urn"))
    if len(set(urns)) != len(urns):
        raise GovernedMetadataError("DataHub glossary associations are duplicate")
    return frozenset(urns)


def string_set(value: object, name: str) -> set[str]:
    """최대 128개의 비어 있지 않은 문자열 배열을 set으로 바꾸며 중복으로 인한 의미 축약을 거부한다."""
    if not isinstance(value, list) or len(value) > 128:
        raise GovernedMetadataError(f"DataHub {name} must be a bounded array")
    values = {required_text(item, name) for item in value}
    if len(values) != len(value):
        raise GovernedMetadataError(f"DataHub {name} contains duplicates")
    return values


def required_text(value: object, name: str) -> str:
    """필수 DataHub 필드를 공백 제거한 문자열로 반환하고 누락·빈 값은 ``GovernedMetadataError``로 닫는다."""
    if not isinstance(value, str) or not value.strip():
        raise GovernedMetadataError(f"DataHub {name} is missing")
    return value.strip()


def identifier(value: object, name: str) -> str:
    """metric·dimension 식별자를 ASCII identifier로 제한해 SQL/context key 해석의 모호성을 방지한다."""
    text = required_text(value, name)
    if not text.isascii() or not text.isidentifier():
        raise GovernedMetadataError(f"DataHub {name} is not an identifier")
    return text


def fqn(value: object) -> str:
    """Trino asset 이름이 정확히 catalog·schema·relation 3부분인지 검증해 물리 대상의 모호성을 막는다."""
    text = required_text(value, "Trino FQN")
    parts = text.split(".")
    if len(parts) != 3 or any(not part for part in parts):
        raise GovernedMetadataError("DataHub Trino FQN must have three parts")
    return text


def checksum(value: object) -> str:
    """release checksum을 64자리 SHA-256 hex로 정규화하며 잘못된 길이·문자는 거부한다."""
    text = required_text(value, "glossary checksum").casefold()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise GovernedMetadataError("DataHub glossary checksum is invalid")
    return text


def native_governance(
    value: object,
    entity_name: str,
) -> tuple[frozenset[str], str, str]:
    """엔터티의 삭제 상태·APPROVED lifecycle·technical owner·domain을 native aspect에서 검증해 URN들을 반환한다."""
    if not isinstance(value, dict):
        raise GovernedMetadataError(f"DataHub {entity_name} is invalid")
    status = value.get("status")
    lifecycle = status.get("lifecycleStage") if isinstance(status, dict) else None
    if (
        not isinstance(status, dict)
        or status.get("removed") is not False
        or not isinstance(lifecycle, dict)
        or required_text(lifecycle.get("name"), "lifecycle stage") != "APPROVED"
        or not required_text(lifecycle.get("urn"), "lifecycle stage urn")
    ):
        raise GovernedMetadataError(
            f"DataHub {entity_name} is not in the native APPROVED lifecycle"
        )
    # custom approval만 확인하면 native lifecycle 철회나 ownership 변조를 놓치므로 DataHub 원생 aspect를 필수로 읽는다.
    ownership = value.get("ownership")
    raw_owners = ownership.get("owners") if isinstance(ownership, dict) else None
    if not isinstance(raw_owners, list) or not raw_owners:
        raise GovernedMetadataError(f"DataHub {entity_name} has no native owner")
    owners: set[str] = set()
    entity_urn = required_text(value.get("urn"), f"{entity_name} urn")
    for item in raw_owners:
        owner = item.get("owner") if isinstance(item, dict) else None
        urn = owner.get("urn") if isinstance(owner, dict) else None
        owner_urn = required_text(urn, "owner urn")
        ownership_type = item.get("ownershipType")
        if (
            item.get("type") not in {"TECHNICAL_OWNER", "CUSTOM", "NONE"}
            or not isinstance(ownership_type, dict)
            or ownership_type.get("urn")
            != "urn:li:ownershipType:__system__technical_owner"
            or item.get("associatedUrn") != entity_urn
            or owner_urn in owners
        ):
            raise GovernedMetadataError(
                f"DataHub {entity_name} ownership classification is invalid"
            )
        owners.add(owner_urn)
    association = value.get("domain")
    domain = association.get("domain") if isinstance(association, dict) else None
    domain_urn = required_text(
        domain.get("urn") if isinstance(domain, dict) else None,
        "domain urn",
    )
    return frozenset(owners), domain_urn, required_text(
        lifecycle.get("urn"), "lifecycle stage urn"
    )


def clone_mapping(value: dict[str, Any]) -> dict[str, Any]:
    """mapping을 JSON 값으로 왕복시켜 사용자 정의 객체를 거부하고 내부 metadata와 분리된 복사본을 만든다."""
    import json

    return json.loads(json.dumps(value))
