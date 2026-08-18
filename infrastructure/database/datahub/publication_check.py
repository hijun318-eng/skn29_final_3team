"""DataHub 발행 전후에 확인할 live 범위와 catalog checksum을 계산한다.

이 모듈은 승인 시스템을 흉내 내지 않는다. 읽기 전용 검사에서 관측한 목표
catalog와 현재 predecessor를 발행 명령에 다시 제시하게 해, 검토하지 않은 변경이나
중간 drift가 mutation으로 이어지는 것만 차단한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from metadata_contract_primitives import SemanticMetadataError, exact_keys, text
from src.data.governance_contract import canonical_sha256, catalog_hash


_CHECK_KEYS = {
    "subject",
    "actor",
    "policy_sha256",
    "physical_scope_sha256",
    "previous_catalog_sha256",
    "catalog_sha256",
}


def publication_check(
    policy: Mapping[str, Any],
    bundle: Mapping[str, Any],
    *,
    actor: str,
    previous_catalog_sha256: str,
) -> dict[str, str]:
    """현재 policy·물리 범위·이전 release를 사람이 비교할 checksum으로 반환한다."""

    check = {
        "subject": _subject(bundle),
        "actor": _corpuser(actor),
        "policy_sha256": canonical_sha256(policy),
        "physical_scope_sha256": physical_scope_sha256(bundle),
        "previous_catalog_sha256": _sha256(
            previous_catalog_sha256, "previous catalog checksum"
        ),
        "catalog_sha256": catalog_hash(bundle),
    }
    exact_keys(check, _CHECK_KEYS, "semantic publication check")
    return check


def verify_expected_release(
    check: Mapping[str, str],
    *,
    expected_catalog_sha256: str,
    expected_previous_catalog_sha256: str,
) -> None:
    """발행자가 확인한 목표와 predecessor가 새 live discovery와 같은지 검증한다."""

    expected_catalog = _sha256(expected_catalog_sha256, "expected catalog checksum")
    expected_previous = _sha256(
        expected_previous_catalog_sha256, "expected previous catalog checksum"
    )
    if check["catalog_sha256"] != expected_catalog:
        raise SemanticMetadataError("target catalog differs from the checked release")
    if check["previous_catalog_sha256"] != expected_previous:
        raise SemanticMetadataError("live predecessor differs from the checked release")


def physical_scope_sha256(bundle: Mapping[str, Any]) -> str:
    """live asset identity와 schema field만 투영해 물리 범위 SHA256을 계산한다."""

    projection = [
        {
            "urn": asset["urn"],
            "fqn": asset["fqn"],
            "platform_urn": asset["platform_urn"],
            "schema_name": asset["schema_name"],
            "schema_metadata_version": asset["schema_metadata_version"],
            "dataset_key": asset["dataset_key"],
            "table_type": asset["table_type"],
            "columns": [
                {
                    "ordinal_position": column["ordinal_position"],
                    "name": column["name"],
                    "native_type": column["native_type"],
                    "nullable": column["nullable"],
                    "is_part_of_key": column["is_part_of_key"],
                }
                for column in asset["columns"]
            ],
        }
        for asset in sorted(
            bundle["schema_context"]["assets"], key=lambda item: item["urn"]
        )
    ]
    return canonical_sha256(projection)


def _subject(bundle: Mapping[str, Any]) -> str:
    return f"answervice.semantic_catalog:{text(bundle['catalog_version'], 'catalog version')}"


def _corpuser(value: object) -> str:
    actor = text(value, "publication actor")
    if not actor.startswith("urn:li:corpuser:"):
        raise SemanticMetadataError("publication actor must be a DataHub corpuser URN")
    return actor


def _sha256(value: object, context: str) -> str:
    result = text(value, context)
    if len(result) != 64 or any(
        character not in "0123456789abcdef" for character in result
    ):
        raise SemanticMetadataError(f"{context} must be lowercase SHA256")
    return result
