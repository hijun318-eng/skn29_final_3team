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
import json
from typing import Any, Protocol

from metadata_contract import validate_bundle, validate_metric_query_policy
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
from src.data.metric_governance import (
    RUNTIME_GOVERNANCE_VERSION_V1,
    RUNTIME_GOVERNANCE_VERSION_V2,
    metric_contract_version,
)
from src.data.entitlement_roles import validate_entitlement_roles


AUTHORING_CONTRACT_VERSION_V1 = "answervice.semantic_authoring.v1"
AUTHORING_CONTRACT_VERSION_V2 = "answervice.semantic_authoring.v2"
AUTHORING_CONTRACT_VERSION_V3 = "answervice.semantic_authoring.v3"
AUTHORING_CONTRACT_VERSION_V4 = "answervice.semantic_authoring.v4"
AUTHORING_CONTRACT_VERSION = AUTHORING_CONTRACT_VERSION_V3
AUTHORING_RUNTIME_VERSIONS = {
    AUTHORING_CONTRACT_VERSION_V1: RUNTIME_GOVERNANCE_VERSION_V1,
    AUTHORING_CONTRACT_VERSION_V2: RUNTIME_GOVERNANCE_VERSION_V2,
    AUTHORING_CONTRACT_VERSION_V3: RUNTIME_GOVERNANCE_VERSION_V1,
    AUTHORING_CONTRACT_VERSION_V4: RUNTIME_GOVERNANCE_VERSION_V2,
}
CURRENT_AUTHORING_FOR_RUNTIME = {
    RUNTIME_GOVERNANCE_VERSION_V1: AUTHORING_CONTRACT_VERSION_V3,
    RUNTIME_GOVERNANCE_VERSION_V2: AUTHORING_CONTRACT_VERSION_V4,
}
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
_CURRENT_ASSET_KEYS = _ASSET_KEYS - {"description"}
_COLUMN_KEYS = {
    "name",
    "logical_type",
    "is_part_of_key",
    "role",
    "description",
}
_CURRENT_COLUMN_KEYS = _COLUMN_KEYS - {"description"}
_CURRENT_AUTHORING_VERSIONS = {
    AUTHORING_CONTRACT_VERSION_V3,
    AUTHORING_CONTRACT_VERSION_V4,
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


def migrate_authoring_policy(
    source_bundle: Mapping[str, Any],
    *,
    catalog_version: str,
    policy_version: str,
    schema_context_version: str,
    roles: tuple[str, ...],
) -> dict[str, Any]:
    """검증된 이전 release에서 의미만 보존한 새 authoring policy를 만든다.

    ordinal/native type/nullability와 dataset identity는 복사하지 않는다. target
    authoring 단계가 live DataHub와 Trino에서 다시 채우므로 schema migration을
    문자열 치환이나 특정 relation 예외로 처리하지 않는다.
    """

    validate_bundle(source_bundle)
    try:
        validate_entitlement_roles(roles)
    except ValueError as error:
        raise SemanticMetadataError("target authoring roles are unsupported") from error
    if not roles:
        raise SemanticMetadataError("target authoring roles cannot be empty")
    runtime_version = metric_contract_version(
        array(source_bundle["metric_rules"], "metric rules", non_empty=True)
    )
    contract_version = CURRENT_AUTHORING_FOR_RUNTIME.get(runtime_version)
    if contract_version is None:
        raise SemanticMetadataError("source runtime governance version is unsupported")

    def version(value: str, context: str) -> str:
        result = text(value, context)
        if len(result) > 255:
            raise SemanticMetadataError(f"{context} exceeds its length bound")
        return result

    migrated_metrics = deepcopy(source_bundle["metric_rules"])
    for metric in migrated_metrics:
        governance = metric.get("governance")
        if isinstance(governance, dict):
            permission = governance.get("permission")
            if isinstance(permission, dict):
                permission["roles"] = list(roles)
    assets = []
    for source in source_bundle["schema_context"]["assets"]:
        entitlements = deepcopy(source["entitlements"])
        entitlements["roles"] = list(roles)
        grain_keys = set(source["grain"]["keys"])
        assets.append(
            {
                "fqn": source["fqn"],
                "schema_version": source["schema_version"],
                "seed_version": source["seed_version"],
                "synthetic": source["synthetic"],
                "approval_status": source["approval_status"],
                "entitlements": entitlements,
                "grain": deepcopy(source["grain"]),
                "columns": [
                    {
                        "name": column["name"],
                        "logical_type": column["logical_type"],
                        "is_part_of_key": column["name"] in grain_keys,
                        "role": column["role"],
                    }
                    for column in source["columns"]
                ],
                "owner_urn": source["owner_urn"],
                "domain_urn": source["domain_urn"],
                "approved_lifecycle_urn": source["approved_lifecycle_urn"],
            }
        )
    policy = {
        "contract_version": contract_version,
        "catalog_version": version(catalog_version, "target catalog version"),
        "policy_version": version(policy_version, "target policy version"),
        "schema_context_version": version(
            schema_context_version, "target schema context version"
        ),
        "governance_entities": deepcopy(source_bundle["governance_entities"]),
        "assets": assets,
        "metric_rules": migrated_metrics,
        "metric_terms": deepcopy(source_bundle["metric_terms"]),
        "dimensions": deepcopy(source_bundle["dimensions"]),
        "join_graph": deepcopy(source_bundle["join_graph"]),
        "time_rules": deepcopy(source_bundle["time_rules"]),
        "parameter_contract": deepcopy(source_bundle["parameter_contract"]),
        "query_policy": deepcopy(source_bundle["query_policy"]),
    }
    # Shape와 Role 검증은 target binding 전에도 가능한 범위에서 즉시 수행한다.
    _asset_policies(policy["assets"], contract_version)
    return policy


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
    stage, bindings = reconcile_base(scopes, inventory, datasets)
    if not stage.ready:
        raise BaseMetadataNotReady(stage)
    # Discovery는 같은 platform instance의 과거/connector system dataset을 포함할 수
    # 있다. predecessor는 승인 scope와 exact 대조된 binding에 대해서만 계산해야 하며,
    # 범위 밖 entity가 authoring 대상에 들어오거나 정상 release를 partial로 만들 수 없다.
    previous = _previous_catalog_sha256(
        tuple(binding.dataset for binding in bindings)
    )
    return AuthoringCandidate(assemble_authoring_bundle(policy, bindings), previous)


def assemble_authoring_bundle(
    policy: Mapping[str, Any],
    bindings: tuple[ReleaseBinding, ...],
) -> dict[str, Any]:
    """어떤 semantic 관계도 임의 추론하지 않고 정규 bundle을 생성한다."""

    policy = mapping(policy, "semantic authoring policy")
    exact_keys(policy, _POLICY_KEYS, "semantic authoring policy")
    contract_version = policy["contract_version"]
    expected_runtime_version = AUTHORING_RUNTIME_VERSIONS.get(contract_version)
    if expected_runtime_version is None:
        raise SemanticMetadataError("semantic authoring contract version is unsupported")
    try:
        actual_runtime_version = metric_contract_version(
            array(policy["metric_rules"], "metric rules", non_empty=True)
        )
    except ValueError as error:
        raise SemanticMetadataError("metric governance version is invalid") from error
    if actual_runtime_version != expected_runtime_version:
        raise SemanticMetadataError(
            "semantic authoring and metric governance versions differ"
        )
    policies = _asset_policies(policy["assets"], contract_version)
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
                _asset(live[name], policies[name], contract_version)
                for name in sorted(live)
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
    validate_metric_query_policy(bundle)
    return bundle


def _asset_policies(
    value: object,
    contract_version: object,
) -> dict[str, Mapping[str, Any]]:
    current = contract_version in _CURRENT_AUTHORING_VERSIONS
    expected_keys = _CURRENT_ASSET_KEYS if current else _ASSET_KEYS
    result: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(
        array(value, "semantic policy assets", non_empty=True, limit=1_000)
    ):
        item = mapping(raw, f"semantic policy asset[{index}]")
        exact_keys(item, expected_keys, f"semantic policy asset[{index}]")
        name = fqn(item["fqn"], f"semantic policy asset[{index}].fqn")
        if name in result:
            raise SemanticMetadataError("semantic policy asset FQNs are duplicate")
        result[name] = item
    return result


def _asset(
    binding: ReleaseBinding,
    policy: Mapping[str, Any],
    contract_version: str,
) -> dict[str, Any]:
    relation, dataset = binding.relation, binding.dataset
    platform, key_name, origin = dataset_key(dataset.urn)
    if (
        dataset.removed is not False
        or dataset.platform_urn != platform
        or len(dataset.fields) != len(relation.columns)
    ):
        raise SemanticMetadataError("live DataHub dataset identity is incomplete")
    current = contract_version in _CURRENT_AUTHORING_VERSIONS
    columns = _columns(
        policy["columns"], policy["grain"], binding, current=current
    )
    return {
        "urn": dataset.urn,
        "fqn": relation.fqn,
        "description": (
            text(dataset.description, f"{relation.fqn} live dataset description")
            if current
            else deepcopy(policy["description"])
        ),
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
        "datahub_schema_hash": dataset.schema_hash,
        "dataset_key": {"platform": platform, "name": key_name, "origin": origin},
        "table_type": relation.table_type,
    }


def _columns(
    value: object,
    grain_value: object,
    binding: ReleaseBinding,
    *,
    current: bool,
) -> list[dict[str, Any]]:
    policies = array(value, f"{binding.relation.fqn} columns", non_empty=True)
    if len(policies) != len(binding.relation.columns):
        raise SemanticMetadataError("semantic policy column count differs from live schema")
    grain = mapping(grain_value, f"{binding.relation.fqn} grain")
    exact_keys(grain, {"kind", "keys"}, f"{binding.relation.fqn} grain")
    grain_keys = {
        text(item, f"{binding.relation.fqn} grain key")
        for item in array(
            grain["keys"], f"{binding.relation.fqn} grain keys", non_empty=True
        )
    }
    result = []
    policy_keys = set()
    for index, (raw, physical, datahub) in enumerate(
        zip(policies, binding.relation.columns, binding.dataset.fields), start=1
    ):
        policy = mapping(raw, f"{binding.relation.fqn} column[{index}]")
        exact_keys(
            policy,
            _CURRENT_COLUMN_KEYS if current else _COLUMN_KEYS,
            f"{binding.relation.fqn} column[{index}]",
        )
        name = text(policy["name"], f"{binding.relation.fqn} column[{index}].name")
        policy_key = policy["is_part_of_key"]
        if policy_key is True:
            policy_keys.add(name)
        if (
            physical.ordinal_position != index
            or physical.name != name
            or datahub.name != name
            or datahub.is_part_of_key is None
            or not isinstance(policy_key, bool)
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
                # 물리 key는 connector read-back 소유다. 승인된 업무 grain은 별도
                # policy에 남으며 아래 subset 불변식으로 물리 key 축소를 차단한다.
                "is_part_of_key": datahub.is_part_of_key,
                "role": deepcopy(policy["role"]),
                "description": (
                    text(
                        datahub.description,
                        f"{binding.relation.fqn}.{physical.name} live description",
                    )
                    if current
                    else deepcopy(policy["description"])
                ),
            }
        )
    physical_keys = {
        field.name for field in binding.dataset.fields if field.is_part_of_key is True
    }
    if policy_keys != grain_keys or not physical_keys <= grain_keys:
        raise SemanticMetadataError(
            "semantic grain keys differ from policy columns or remove a physical key"
        )
    return result


def _previous_catalog_sha256(datasets: tuple[DataHubDataset, ...]) -> str:
    governed = {
        dataset.urn: {
            key.removeprefix(PROPERTY_PREFIX): value
            for key, value in dataset.custom_properties.items()
            if key.startswith(PROPERTY_PREFIX)
        }
        for dataset in datasets
        if any(key.startswith(PROPERTY_PREFIX) for key in dataset.custom_properties)
    }
    if not governed:
        return CLEAN_CATALOG_SHA256
    hashes = [item.get("catalog_sha256") for item in governed.values()]
    if any(not isinstance(value, str) for value in hashes) or len(set(hashes)) != 1:
        raise SemanticMetadataError(
            "live DataHub contains a partial or conflicting semantic release"
        )
    value = hashes[0]
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise SemanticMetadataError("live DataHub catalog checksum is invalid")

    # Scope 확장에서는 이전 release 자산과 base-ingested 신규 자산이 함께 발견된다.
    # 신규 자산에 semantic property가 없다는 이유만으로 전이를 막지는 않되, 각 기존
    # 자산에 복제된 manifest가 동일하고 그 manifest의 dataset 집합이 정확히 모두
    # 존재할 때에만 predecessor를 인정한다. 기존 자산 하나가 빠진 교체·축소는 여전히
    # partial release로 닫히므로 이 경로가 삭제 승인 우회가 되지 않는다.
    manifests: list[dict[str, Any]] = []
    for properties in governed.values():
        raw_manifest = properties.get("release_manifest")
        if not isinstance(raw_manifest, str):
            raise SemanticMetadataError(
                "live DataHub contains a partial or conflicting semantic release"
            )
        try:
            manifest = json.loads(raw_manifest)
        except json.JSONDecodeError as error:
            raise SemanticMetadataError(
                "live DataHub release manifest is invalid"
            ) from error
        if not isinstance(manifest, dict) or manifest.get("catalog_sha256") != value:
            raise SemanticMetadataError("live DataHub release manifest is invalid")
        manifests.append(manifest)
    canonical_manifests = {
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for item in manifests
    }
    if len(canonical_manifests) != 1:
        raise SemanticMetadataError(
            "live DataHub contains a partial or conflicting semantic release"
        )
    manifest_datasets = manifests[0].get("datasets")
    if not isinstance(manifest_datasets, list):
        raise SemanticMetadataError("live DataHub release manifest is invalid")
    expected_urns = {
        item.get("urn")
        for item in manifest_datasets
        if isinstance(item, dict) and isinstance(item.get("urn"), str)
    }
    if (
        len(expected_urns) != len(manifest_datasets)
        or set(governed) != expected_urns
    ):
        raise SemanticMetadataError(
            "live DataHub contains a partial or conflicting semantic release"
        )
    return value
