"""승인된 semantic policy를 live DataHub 및 Trino identity와 정확히 결합한다.

The policy is an operator-controlled input boundary, not a runtime cache. Physical
identity, table shape, native types, ordinals, and nullability always come from the
live discovery clients. The resulting bundle is suitable for publication to
DataHub; runtime consumers continue to read DataHub and Trino only.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from metadata_contract import validate_bundle
from metadata_contract_primitives import (
    SemanticMetadataError,
    array,
    exact_keys,
    fqn,
    mapping,
    text,
)
from release_builder import ReadinessStage, reconcile_base
from release_bundle import ReleaseBinding
from release_datahub import PROPERTY_PREFIX, DataHubDataset, dataset_key
from release_scope import ReleaseScope
from release_trino import TrinoInventory


AUTHORING_CONTRACT_VERSION = "answervice.semantic_authoring.v1"
CLEAN_CATALOG_SHA256 = "0" * 64
_POLICY_KEYS = {
    "contract_version",
    "catalog_version",
    "policy_version",
    "schema_context_version",
    "governance_entities",
    "assets",
    "metric_rules",
    "metric_terms",
    "dimensions",
    "join_graph",
    "time_rules",
    "parameter_contract",
    "query_policy",
}
_ASSET_KEYS = {
    "fqn",
    "description",
    "schema_version",
    "seed_version",
    "synthetic",
    "approval_status",
    "entitlements",
    "grain",
    "columns",
    "owner_urn",
    "domain_urn",
    "approved_lifecycle_urn",
}
_COLUMN_KEYS = {
    "name",
    "logical_type",
    "is_part_of_key",
    "role",
    "description",
}


class TrinoAuthoringPort(Protocol):
    """metadata mutation 전 physical discovery를 수행하는 port 계약이다."""

    async def discover(self, scopes: tuple[ReleaseScope, ...]) -> TrinoInventory:
        """지정된 scope의 live Trino physical inventory를 반환한다."""
        ...


class DataHubAuthoringPort(Protocol):
    """ingestion 완전성을 증명할 base DataHub discovery port 계약이다."""

    async def discover_datasets(
        self, scopes: tuple[ReleaseScope, ...]
    ) -> tuple[DataHubDataset, ...]:
        """지정된 scope의 live DataHub dataset metadata를 반환한다."""
        ...


class BaseMetadataNotReady(RuntimeError):
    """live physical metadata가 불완전해 authoring이 DataHub를 변경할 수 없음을 나타낸다."""

    def __init__(self, stage: ReadinessStage) -> None:
        super().__init__("live DataHub and Trino base metadata are not ready")
        self.stage = stage


@dataclass(frozen=True)
class AuthoringCandidate:
    """정규 candidate와 prior metadata의 optimistic-concurrency hash를 묶는다."""

    bundle: dict[str, Any]
    previous_catalog_sha256: str


async def build_authoring_bundle(
    policy: Mapping[str, Any],
    scopes: tuple[ReleaseScope, ...],
    trino: TrinoAuthoringPort,
    datahub: DataHubAuthoringPort,
) -> dict[str, Any]:
    """live physical metadata를 발견하고 승인된 policy 하나를 정확히 결합한다."""

    return (await build_authoring_candidate(policy, scopes, trino, datahub)).bundle


async def build_authoring_candidate(
    policy: Mapping[str, Any],
    scopes: tuple[ReleaseScope, ...],
    trino: TrinoAuthoringPort,
    datahub: DataHubAuthoringPort,
) -> AuthoringCandidate:
    """target bundle과 정확한 live predecessor hash를 함께 반환한다."""

    inventory = await trino.discover(scopes)
    datasets = await datahub.discover_datasets(scopes)
    previous = _previous_catalog_sha256(datasets)
    stage, bindings = reconcile_base(scopes, inventory, datasets)
    if not stage.ready:
        raise BaseMetadataNotReady(stage)
    return AuthoringCandidate(assemble_authoring_bundle(policy, bindings), previous)


def assemble_authoring_bundle(
    policy: Mapping[str, Any],
    bindings: tuple[ReleaseBinding, ...],
) -> dict[str, Any]:
    """어떤 semantic 관계도 임의 추론하지 않고 정규 bundle을 생성한다."""

    policy = mapping(policy, "semantic authoring policy")
    exact_keys(policy, _POLICY_KEYS, "semantic authoring policy")
    if policy["contract_version"] != AUTHORING_CONTRACT_VERSION:
        raise SemanticMetadataError("semantic authoring contract version is unsupported")
    policies = _asset_policies(policy["assets"])
    live = {binding.relation.fqn: binding for binding in bindings}
    if set(policies) != set(live):
        raise SemanticMetadataError(
            "semantic policy assets must exactly cover live DataHub and Trino relations"
        )
    bundle = {
        "catalog_version": deepcopy(policy["catalog_version"]),
        "policy_version": deepcopy(policy["policy_version"]),
        "governance_entities": deepcopy(policy["governance_entities"]),
        "schema_context": {
            "version": deepcopy(policy["schema_context_version"]),
            "assets": [
                _asset(live[name], policies[name]) for name in sorted(live)
            ],
        },
        "metric_rules": deepcopy(policy["metric_rules"]),
        "metric_terms": deepcopy(policy["metric_terms"]),
        "dimensions": deepcopy(policy["dimensions"]),
        "join_graph": deepcopy(policy["join_graph"]),
        "time_rules": deepcopy(policy["time_rules"]),
        "parameter_contract": deepcopy(policy["parameter_contract"]),
        "query_policy": deepcopy(policy["query_policy"]),
    }
    validate_bundle(bundle)
    return bundle


def _asset_policies(value: object) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(
        array(value, "semantic policy assets", non_empty=True, limit=1_000)
    ):
        item = mapping(raw, f"semantic policy asset[{index}]")
        exact_keys(item, _ASSET_KEYS, f"semantic policy asset[{index}]")
        name = fqn(item["fqn"], f"semantic policy asset[{index}].fqn")
        if name in result:
            raise SemanticMetadataError("semantic policy asset FQNs are duplicate")
        result[name] = item
    return result


def _asset(
    binding: ReleaseBinding,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    relation, dataset = binding.relation, binding.dataset
    platform, key_name, origin = dataset_key(dataset.urn)
    if (
        dataset.removed is not False
        or dataset.platform_urn != platform
        or len(dataset.fields) != len(relation.columns)
    ):
        raise SemanticMetadataError("live DataHub dataset identity is incomplete")
    columns = _columns(policy["columns"], binding)
    return {
        "urn": dataset.urn,
        "fqn": relation.fqn,
        "description": deepcopy(policy["description"]),
        "schema_version": deepcopy(policy["schema_version"]),
        "seed_version": deepcopy(policy["seed_version"]),
        "synthetic": deepcopy(policy["synthetic"]),
        "approval_status": deepcopy(policy["approval_status"]),
        "entitlements": deepcopy(policy["entitlements"]),
        "grain": deepcopy(policy["grain"]),
        "columns": columns,
        "owner_urn": deepcopy(policy["owner_urn"]),
        "domain_urn": deepcopy(policy["domain_urn"]),
        "approved_lifecycle_urn": deepcopy(policy["approved_lifecycle_urn"]),
        "platform_urn": platform,
        "schema_name": dataset.schema_name,
        "schema_metadata_version": dataset.schema_version,
        "dataset_key": {"platform": platform, "name": key_name, "origin": origin},
        "table_type": relation.table_type,
    }


def _columns(value: object, binding: ReleaseBinding) -> list[dict[str, Any]]:
    policies = array(value, f"{binding.relation.fqn} columns", non_empty=True)
    if len(policies) != len(binding.relation.columns):
        raise SemanticMetadataError("semantic policy column count differs from live schema")
    result = []
    for index, (raw, physical, datahub) in enumerate(
        zip(policies, binding.relation.columns, binding.dataset.fields), start=1
    ):
        policy = mapping(raw, f"{binding.relation.fqn} column[{index}]")
        exact_keys(policy, _COLUMN_KEYS, f"{binding.relation.fqn} column[{index}]")
        name = text(policy["name"], f"{binding.relation.fqn} column[{index}].name")
        policy_key = policy["is_part_of_key"]
        if (
            physical.ordinal_position != index
            or physical.name != name
            or datahub.name != name
            or datahub.is_part_of_key is None
            or not isinstance(policy_key, bool)
            # WHY: ingestion이 이미 발견한 key를 policy가 제거하면 grain이 축소되어
            # 중복 집계 위험이 생긴다. 반대로 view/ClickHouse에서 표현되지 않은 key는
            # 서명된 semantic policy가 선언하고 발행 schema read-back으로 고정할 수 있다.
            or (datahub.is_part_of_key is True and policy_key is not True)
        ):
            raise SemanticMetadataError(
                "semantic policy column identity differs from live DataHub and Trino"
            )
        result.append(
            {
                "ordinal_position": physical.ordinal_position,
                "name": physical.name,
                "native_type": physical.native_type,
                "logical_type": deepcopy(policy["logical_type"]),
                "nullable": physical.nullable,
                "is_part_of_key": policy_key,
                "role": deepcopy(policy["role"]),
                "description": deepcopy(policy["description"]),
            }
        )
    return result


def _previous_catalog_sha256(datasets: tuple[DataHubDataset, ...]) -> str:
    governed = [
        {
            key.removeprefix(PROPERTY_PREFIX): value
            for key, value in dataset.custom_properties.items()
            if key.startswith(PROPERTY_PREFIX)
        }
        for dataset in datasets
    ]
    if not any(governed):
        return CLEAN_CATALOG_SHA256
    hashes = [item.get("catalog_sha256") for item in governed]
    if (
        any(not item for item in governed)
        or any(not isinstance(value, str) for value in hashes)
        or len(set(hashes)) != 1
    ):
        raise SemanticMetadataError(
            "live DataHub contains a partial or conflicting semantic release"
        )
    value = hashes[0]
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise SemanticMetadataError("live DataHub catalog checksum is invalid")
    return value
