"""검증된 live metadata만 사용해 정규 semantic bundle을 재구성한다."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from metadata_contract import PROPERTY_PREFIX, validate_bundle
from release_datahub import DataHubDataset, DataHubTerm, NativeEntity, dataset_key
from release_trino import PhysicalRelation
from src.data.governance_contract import (
    DATASET_RUNTIME_PROPERTY_KEYS,
    RUNTIME_GOVERNANCE_VERSION,
    TERM_RUNTIME_PROPERTY_KEYS,
    canonical_sha256,
    datahub_schema_sha1,
    dataset_runtime_property_projection,
    release_manifest,
    term_runtime_property_projection,
    trino_schema_sha256,
)


class SemanticBundleError(ValueError):
    """live semantic metadata로 정규 release bundle을 재구성할 수 없음을 나타낸다."""


@dataclass(frozen=True)
class ReleaseBinding:
    """base reconciliation에서 확정된 physical relation과 catalog dataset의 정확한 쌍이다."""

    relation: PhysicalRelation
    dataset: DataHubDataset


def semantic_surface_issues(bindings: tuple[ReleaseBinding, ...]) -> tuple[str, ...]:
    """semantic payload 해석 전에 제한된 identity 수준 문제를 반환한다."""

    issues: list[str] = []
    for binding in bindings:
        dataset = binding.dataset
        properties = _governed_properties(dataset)
        if set(properties) != DATASET_RUNTIME_PROPERTY_KEYS:
            issues.append(f"semantic_properties:{binding.relation.fqn}")
        elif properties.get("contract_version") != RUNTIME_GOVERNANCE_VERSION:
            issues.append(f"semantic_contract_version:{binding.relation.fqn}")
        if dataset.removed is not False:
            issues.append(f"active_status:{binding.relation.fqn}")
        if len(dataset.owners) != 1 or dataset.owners[0].entity_type != "CorpGroup":
            issues.append(f"native_owner:{binding.relation.fqn}")
        if dataset.domain is None:
            issues.append(f"native_domain:{binding.relation.fqn}")
        if dataset.lifecycle is None or dataset.lifecycle.name != "APPROVED":
            issues.append(f"approved_lifecycle:{binding.relation.fqn}")
    return tuple(sorted(set(issues)))


def release_term_urns(bindings: tuple[ReleaseBinding, ...]) -> tuple[str, ...]:
    """live property에서 완전한 glossary term 집합을 추출하고 검증한다."""

    anchor = _anchor_properties(bindings)
    manifest = _json_object(anchor["release_manifest"], "release manifest")
    raw_terms = manifest.get("metric_terms")
    if not isinstance(raw_terms, list) or not raw_terms:
        raise SemanticBundleError("release manifest has no metric terms")
    urns = []
    for item in raw_terms:
        if not isinstance(item, dict) or set(item) != {"id", "urn", "semantic_sha256"}:
            raise SemanticBundleError("release manifest term entry is invalid")
        urn = item.get("urn")
        if not isinstance(urn, str) or not urn.startswith("urn:li:glossaryTerm:"):
            raise SemanticBundleError("release manifest term URN is invalid")
        urns.append(urn)
    if len(urns) != len(set(urns)):
        raise SemanticBundleError("release manifest term URNs are duplicated")
    return tuple(sorted(urns))


def assemble_release_bundle(
    bindings: tuple[ReleaseBinding, ...],
    terms: tuple[DataHubTerm, ...],
) -> dict[str, Any]:
    """누락된 semantic fact를 추론하지 않고 bundle을 재구성·재해시한다."""

    if not bindings:
        raise SemanticBundleError("release has no physical dataset bindings")
    surface = semantic_surface_issues(bindings)
    if surface:
        raise SemanticBundleError(f"semantic surface is incomplete: {surface[0]}")
    anchor = _anchor_properties(bindings)
    manifest = _json_object(anchor["release_manifest"], "release manifest")
    assets = [_asset(binding) for binding in sorted(bindings, key=lambda item: item.relation.fqn)]
    metric_terms, metric_rules = _terms(terms)
    governance = _governance_entities(assets, metric_terms, bindings, terms)
    bundle: dict[str, Any] = {
        "catalog_version": anchor["catalog_version"],
        "policy_version": anchor["policy_version"],
        "governance_entities": governance,
        "schema_context": {
            "version": anchor["schema_context_version"],
            "assets": assets,
        },
        "metric_rules": metric_rules,
        "metric_terms": metric_terms,
        "dimensions": _json_array(anchor["dimensions"], "dimensions"),
        "join_graph": _json_object(anchor["join_graph"], "join graph"),
        "time_rules": _json_object(anchor["time_rules"], "time rules"),
        "parameter_contract": _json_object(
            anchor["parameter_contract"], "parameter contract"
        ),
        "query_policy": _json_object(anchor["query_policy"], "query policy"),
    }
    try:
        validate_bundle(bundle)
    except ValueError as error:
        raise SemanticBundleError("reconstructed semantic bundle is invalid") from error
    calculated_manifest = release_manifest(bundle)
    if calculated_manifest != manifest:
        raise SemanticBundleError("live release manifest differs from reconstructed bundle")
    if anchor["manifest_sha256"] != canonical_sha256(manifest):
        raise SemanticBundleError("live release manifest checksum is invalid")
    _verify_dataset_readback(bundle, bindings, calculated_manifest)
    _verify_term_readback(bundle, terms, calculated_manifest)
    return bundle


def _anchor_properties(bindings: tuple[ReleaseBinding, ...]) -> dict[str, str]:
    if not bindings:
        raise SemanticBundleError("release has no dataset properties")
    shared_keys = {
        "catalog_version",
        "catalog_sha256",
        "schema_context_version",
        "governance_urns",
        "release_manifest",
        "manifest_sha256",
        "policy_version",
        "dimensions",
        "join_graph",
        "time_rules",
        "parameter_contract",
        "query_policy",
    }
    anchor = _governed_properties(bindings[0].dataset)
    if set(anchor) != DATASET_RUNTIME_PROPERTY_KEYS:
        raise SemanticBundleError("dataset semantic property keys are incomplete")
    for binding in bindings[1:]:
        actual = _governed_properties(binding.dataset)
        if set(actual) != DATASET_RUNTIME_PROPERTY_KEYS or any(
            actual[key] != anchor[key] for key in shared_keys
        ):
            raise SemanticBundleError("datasets do not share one semantic release identity")
    return anchor


def _asset(binding: ReleaseBinding) -> dict[str, Any]:
    dataset, relation = binding.dataset, binding.relation
    properties = _governed_properties(dataset)
    typed_columns = _json_array(properties["typed_columns"], "typed columns")
    if not isinstance(_json_object(properties["grain"], "grain"), dict):
        raise SemanticBundleError("dataset grain is invalid")
    platform, name, origin = dataset_key(dataset.urn)
    if (
        properties["fqn"] != relation.fqn
        or dataset.name != relation.fqn
        or dataset.qualified_name != relation.fqn
        or platform != dataset.platform_urn
        or len(dataset.owners) != 1
        or dataset.domain is None
        or dataset.lifecycle is None
    ):
        raise SemanticBundleError(f"dataset identity is incomplete: {relation.fqn}")
    _verify_columns(binding, typed_columns)
    synthetic = _json_boolean(properties["synthetic"], "synthetic provenance")
    return {
        "urn": dataset.urn,
        "fqn": relation.fqn,
        "description": _required_text(dataset.description, "dataset description"),
        "schema_version": properties["schema_version"],
        "seed_version": properties["seed_version"],
        "synthetic": synthetic,
        "approval_status": properties["approval_status"],
        "entitlements": _json_object(properties["entitlements"], "entitlements"),
        "grain": _json_object(properties["grain"], "grain"),
        "columns": typed_columns,
        "owner_urn": dataset.owners[0].urn,
        "domain_urn": dataset.domain.urn,
        "approved_lifecycle_urn": dataset.lifecycle.urn,
        "platform_urn": platform,
        "schema_name": dataset.schema_name,
        "schema_metadata_version": dataset.schema_version,
        "dataset_key": {"platform": platform, "name": name, "origin": origin},
        "table_type": relation.table_type,
    }


def _verify_columns(binding: ReleaseBinding, columns: list[Any]) -> None:
    dataset, relation = binding.dataset, binding.relation
    if len(columns) != len(dataset.fields) or len(columns) != len(relation.columns):
        raise SemanticBundleError(f"column count differs: {relation.fqn}")
    for ordinal, (raw, datahub, trino) in enumerate(
        zip(columns, dataset.fields, relation.columns), start=1
    ):
        if not isinstance(raw, dict):
            raise SemanticBundleError(f"typed column is invalid: {relation.fqn}")
        if (
            raw.get("ordinal_position") != ordinal
            or raw.get("name") != datahub.name
            or raw.get("native_type") != datahub.native_type
            or raw.get("nullable") is not datahub.nullable
            or raw.get("is_part_of_key") is not datahub.is_part_of_key
            or raw.get("description") != datahub.description
            or raw.get("name") != trino.name
            or raw.get("native_type") != trino.native_type
            or raw.get("nullable") is not trino.nullable
        ):
            raise SemanticBundleError(f"live column metadata differs: {relation.fqn}")


def _terms(
    terms: tuple[DataHubTerm, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    metric_terms: list[dict[str, Any]] = []
    metric_rules: list[dict[str, Any]] = []
    for term in sorted(terms, key=lambda item: item.urn):
        properties = _governed_properties(term)
        if (
            set(properties) != TERM_RUNTIME_PROPERTY_KEYS
            or term.exists is not True
            or term.removed is not False
            or len(term.owners) != 1
            or term.owners[0].entity_type != "CorpGroup"
            or term.domain is None
            or term.lifecycle is None
            or term.lifecycle.name != "APPROVED"
        ):
            raise SemanticBundleError(f"glossary term governance is incomplete: {term.urn}")
        rule = _json_object(properties["metric_rule"], "metric rule")
        metric_id = _required_text(properties["metric_id"], "metric id")
        if rule.get("id") != metric_id:
            raise SemanticBundleError(f"glossary metric identity differs: {term.urn}")
        metric_rules.append(rule)
        metric_terms.append(
            {
                "id": metric_id,
                "urn": term.urn,
                "name": _required_text(term.name, "glossary term name"),
                "definition": _required_text(term.description, "glossary definition"),
                "aliases": _json_array(properties["aliases"], "glossary aliases"),
                "unit": properties["unit"],
                "version": properties["glossary_version"],
                "approval_status": properties["approval_status"],
                "owner_urn": term.owners[0].urn,
                "domain_urn": term.domain.urn,
                "approved_lifecycle_urn": term.lifecycle.urn,
            }
        )
    if len({item["id"] for item in metric_rules}) != len(metric_rules):
        raise SemanticBundleError("glossary metric ids are duplicated")
    return metric_terms, sorted(metric_rules, key=lambda item: item["id"])


def _governance_entities(
    assets: list[dict[str, Any]],
    metric_terms: list[dict[str, Any]],
    bindings: tuple[ReleaseBinding, ...],
    terms: tuple[DataHubTerm, ...],
) -> dict[str, list[dict[str, str]]]:
    entities = [
        *(binding.dataset for binding in bindings),
        *terms,
    ]
    owners = [owner for entity in entities for owner in entity.owners]
    domains = [entity.domain for entity in entities if entity.domain is not None]
    lifecycles = [entity.lifecycle for entity in entities if entity.lifecycle is not None]
    result = {
        "owners": _unique_governance(owners, "urn:li:corpGroup:", "CorpGroup"),
        "domains": _unique_governance(domains, "urn:li:domain:", "Domain"),
        "approved_lifecycles": _unique_governance(
            lifecycles, "urn:li:lifecycleStageType:", "LifecycleStage", approved=True
        ),
    }
    referenced = [*assets, *metric_terms]
    for key, field in (
        ("owners", "owner_urn"),
        ("domains", "domain_urn"),
        ("approved_lifecycles", "approved_lifecycle_urn"),
    ):
        if {item["urn"] for item in result[key]} != {item[field] for item in referenced}:
            raise SemanticBundleError(f"native governance coverage differs: {key}")
    return result


def _unique_governance(
    values: list[NativeEntity],
    urn_prefix: str,
    entity_type: str,
    *,
    approved: bool = False,
) -> list[dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for value in values:
        item = {
            "urn": value.urn,
            "name": _required_text(value.name, "governance name"),
            "description": _required_text(value.description, "governance description"),
        }
        if (
            not value.urn.startswith(urn_prefix)
            or value.entity_type != entity_type
            or (approved and item["name"] != "APPROVED")
        ):
            raise SemanticBundleError("native governance entity type is invalid")
        previous = result.get(value.urn)
        if previous is not None and previous != item:
            raise SemanticBundleError("native governance entity details conflict")
        result[value.urn] = item
    return [result[urn] for urn in sorted(result)]


def _verify_dataset_readback(
    bundle: Mapping[str, Any],
    bindings: tuple[ReleaseBinding, ...],
    manifest: Mapping[str, Any],
) -> None:
    assets = {asset["urn"]: asset for asset in bundle["schema_context"]["assets"]}
    for binding in bindings:
        asset = assets[binding.dataset.urn]
        actual = _governed_properties(binding.dataset)
        expected = dataset_runtime_property_projection(bundle, asset, manifest)
        if actual != expected:
            raise SemanticBundleError(f"dataset semantic readback differs: {asset['fqn']}")
        if datahub_schema_sha1(asset) != binding.dataset.schema_hash:
            raise SemanticBundleError(f"DataHub schema hash differs: {asset['fqn']}")
        if trino_schema_sha256(asset) != next(
            item["trino_schema_sha256"]
            for item in manifest["datasets"]
            if item["urn"] == asset["urn"]
        ):
            raise SemanticBundleError(f"Trino schema hash differs: {asset['fqn']}")


def _verify_term_readback(
    bundle: Mapping[str, Any],
    terms: tuple[DataHubTerm, ...],
    manifest: Mapping[str, Any],
) -> None:
    definitions = {item["urn"]: item for item in bundle["metric_terms"]}
    metrics = {item["id"]: item for item in bundle["metric_rules"]}
    for term in terms:
        definition = definitions[term.urn]
        expected = term_runtime_property_projection(
            definition, metrics[definition["id"]], manifest
        )
        if _governed_properties(term) != expected:
            raise SemanticBundleError(f"glossary semantic readback differs: {term.urn}")


def _governed_properties(entity: DataHubDataset | DataHubTerm) -> dict[str, str]:
    return {
        key.removeprefix(PROPERTY_PREFIX): value
        for key, value in entity.custom_properties.items()
        if key.startswith(PROPERTY_PREFIX)
    }


def _json_object(value: str, context: str) -> dict[str, Any]:
    parsed = _json(value, context)
    if not isinstance(parsed, dict):
        raise SemanticBundleError(f"{context} must be an object")
    return parsed


def _json_array(value: str, context: str) -> list[Any]:
    parsed = _json(value, context)
    if not isinstance(parsed, list):
        raise SemanticBundleError(f"{context} must be an array")
    return parsed


def _json_boolean(value: str, context: str) -> bool:
    parsed = _json(value, context)
    if not isinstance(parsed, bool):
        raise SemanticBundleError(f"{context} must be boolean")
    return parsed


def _json(value: str, context: str) -> object:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as error:
        raise SemanticBundleError(f"{context} is not valid JSON") from error


def _required_text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticBundleError(f"{context} must be non-empty text")
    return value
