"""업무 승인 결정과 live binding을 결합해 물리값을 복제하지 않은 authoring policy를 만든다."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from metadata_contract_primitives import (
    SemanticMetadataError,
    array,
    exact_keys,
    fqn,
    mapping,
    text,
    unique_texts,
)
from release_bundle import ReleaseBinding
from semantic_authoring import (
    AUTHORING_CONTRACT_VERSION_V1,
    AUTHORING_CONTRACT_VERSION_V2,
)
from src.data.metric_governance import (
    RUNTIME_GOVERNANCE_VERSION_V1,
    RUNTIME_GOVERNANCE_VERSION_V2,
    metric_contract_version,
)


DECISION_CONTRACT_VERSION_V1 = "answervice.policy_decisions.v1"
DECISION_CONTRACT_VERSION_V2 = "answervice.policy_decisions.v2"
DECISION_CONTRACT_VERSION = DECISION_CONTRACT_VERSION_V1
_DECISION_VERSIONS = {
    DECISION_CONTRACT_VERSION_V1: (
        AUTHORING_CONTRACT_VERSION_V1,
        RUNTIME_GOVERNANCE_VERSION_V1,
    ),
    DECISION_CONTRACT_VERSION_V2: (
        AUTHORING_CONTRACT_VERSION_V2,
        RUNTIME_GOVERNANCE_VERSION_V2,
    ),
}
_DECISION_KEYS = {
    "contract_version",
    "catalog_version",
    "policy_version",
    "schema_context_version",
    "schema_version",
    "seed_version",
    "synthetic",
    "owner",
    "approved_lifecycle",
    "roles",
    "asset_grains",
    "metric_rules",
    "metric_terms",
    "dimensions",
    "join_graph",
    "time_rules",
    "parameter_contract",
    "query_policy",
}


def compile_authoring_policy(
    decision: Mapping[str, Any],
    bindings: tuple[ReleaseBinding, ...],
) -> dict[str, Any]:
    """승인 의미만 받아 live schema identity가 포함된 전체 authoring policy를 반환한다.

    URN, dataset domain, column 순서·native type·nullable·설명은 binding에서만
    가져온다. 승인 입력은 grain 승격, metric, dimension, time, entitlement처럼
    물리 discovery가 결정할 수 없는 의미만 소유한다.
    """

    source = mapping(decision, "policy decisions")
    exact_keys(source, _DECISION_KEYS, "policy decisions")
    versions = _DECISION_VERSIONS.get(source["contract_version"])
    if versions is None:
        raise SemanticMetadataError("policy decision contract version is unsupported")
    authoring_version, expected_runtime_version = versions
    if not bindings:
        raise SemanticMetadataError("policy decisions require live release bindings")
    owner = _governance(source["owner"], "owner", "urn:li:corpGroup:")
    lifecycle = _governance(
        source["approved_lifecycle"],
        "approved lifecycle",
        "urn:li:lifecycleStageType:",
        approved=True,
    )
    roles = list(unique_texts(source["roles"], "policy roles", non_empty=True))
    grain_overrides = _grain_overrides(source["asset_grains"])
    live_fqns = {binding.relation.fqn for binding in bindings}
    if not set(grain_overrides) <= live_fqns:
        raise SemanticMetadataError("grain decisions reference an unknown live asset")

    metrics = deepcopy(array(source["metric_rules"], "metric rules", non_empty=True))
    try:
        actual_runtime_version = metric_contract_version(
            mapping(item, "metric rule") for item in metrics
        )
    except ValueError as error:
        raise SemanticMetadataError("metric governance version is invalid") from error
    if actual_runtime_version != expected_runtime_version:
        raise SemanticMetadataError(
            "policy decision and metric governance versions differ"
        )
    terms = _metric_terms(source["metric_terms"], metrics, owner, lifecycle, bindings)
    time_rules = _time_rules(source["time_rules"], bindings)
    semantic_roles = _semantic_roles(metrics, source["dimensions"], time_rules)
    domains = _domains(bindings)
    assets = [
        _asset(
            binding,
            grain_overrides.get(binding.relation.fqn),
            semantic_roles,
            roles,
            source,
            owner,
            lifecycle,
        )
        for binding in sorted(bindings, key=lambda item: item.relation.fqn)
    ]
    return {
        "contract_version": authoring_version,
        "catalog_version": text(source["catalog_version"], "catalog version"),
        "policy_version": text(source["policy_version"], "policy version"),
        "schema_context_version": text(
            source["schema_context_version"], "schema context version"
        ),
        "governance_entities": {
            "owners": [owner],
            "domains": domains,
            "approved_lifecycles": [lifecycle],
        },
        "assets": assets,
        "metric_rules": metrics,
        "metric_terms": terms,
        "dimensions": deepcopy(source["dimensions"]),
        "join_graph": deepcopy(source["join_graph"]),
        "time_rules": time_rules,
        "parameter_contract": deepcopy(source["parameter_contract"]),
        "query_policy": deepcopy(source["query_policy"]),
    }


def _governance(
    value: object,
    context: str,
    prefix: str,
    *,
    approved: bool = False,
) -> dict[str, str]:
    item = mapping(value, context)
    exact_keys(item, {"urn", "name", "description"}, context)
    urn = text(item["urn"], f"{context}.urn")
    name = text(item["name"], f"{context}.name")
    description = text(item["description"], f"{context}.description")
    if not urn.startswith(prefix) or (approved and name != "APPROVED"):
        raise SemanticMetadataError(f"{context} has an invalid native identity")
    return {"urn": urn, "name": name, "description": description}


def _grain_overrides(value: object) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(array(value, "asset grains", limit=1_000)):
        item = mapping(raw, f"asset grain[{index}]")
        exact_keys(item, {"fqn", "kind", "keys"}, f"asset grain[{index}]")
        name = fqn(item["fqn"], f"asset grain[{index}].fqn")
        keys = list(unique_texts(item["keys"], f"{name}.grain.keys", non_empty=True))
        if name in result:
            raise SemanticMetadataError("asset grain decisions are duplicate")
        result[name] = {"kind": text(item["kind"], f"{name}.grain.kind"), "keys": keys}
    return result


def _domains(bindings: tuple[ReleaseBinding, ...]) -> list[dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for binding in bindings:
        domain = binding.dataset.domain
        if domain is None:
            raise SemanticMetadataError("live dataset domain is required for policy compilation")
        item = {
            "urn": _canonical_text(domain.urn, "dataset domain URN"),
            "name": _canonical_text(domain.name, "dataset domain name"),
            "description": _canonical_text(
                domain.description, "dataset domain description"
            ),
        }
        if not item["urn"].startswith("urn:li:domain:"):
            raise SemanticMetadataError("live dataset domain has an invalid URN")
        previous = result.get(item["urn"])
        if previous is not None and previous != item:
            raise SemanticMetadataError("live dataset domain definitions conflict")
        result[item["urn"]] = item
    return [result[urn] for urn in sorted(result)]


def _asset(
    binding: ReleaseBinding,
    override: Mapping[str, Any] | None,
    semantic_roles: Mapping[tuple[str, str], str],
    roles: list[str],
    source: Mapping[str, Any],
    owner: Mapping[str, str],
    lifecycle: Mapping[str, str],
) -> dict[str, Any]:
    relation, dataset = binding.relation, binding.dataset
    if dataset.domain is None or len(dataset.fields) != len(relation.columns):
        raise SemanticMetadataError("live asset metadata is incomplete")
    physical_keys = {field.name for field in dataset.fields if field.is_part_of_key is True}
    if override is None:
        if not physical_keys:
            raise SemanticMetadataError(
                f"asset without ingested keys requires an approved grain: {relation.fqn}"
            )
        grain = {"kind": "row", "keys": sorted(physical_keys)}
    else:
        grain = deepcopy(dict(override))
        if not physical_keys <= set(grain["keys"]):
            raise SemanticMetadataError("approved grain cannot remove an ingested key")
    columns = []
    for ordinal, (field, physical) in enumerate(
        zip(dataset.fields, relation.columns), start=1
    ):
        if field.name != physical.name or field.description is None:
            raise SemanticMetadataError("live column identity or description is incomplete")
        key = field.name in set(grain["keys"])
        role = "identifier" if key else semantic_roles.get((relation.fqn, field.name), "attribute")
        columns.append(
            {
                "name": field.name,
                "logical_type": _logical_type(physical.native_type),
                "is_part_of_key": key,
                "role": role,
                "description": _canonical_text(
                    field.description, f"{relation.fqn}.{field.name}.description"
                ),
            }
        )
    return {
        "fqn": relation.fqn,
        "description": _canonical_text(dataset.description, f"{relation.fqn}.description"),
        "schema_version": text(source["schema_version"], "schema version"),
        "seed_version": text(source["seed_version"], "seed version"),
        "synthetic": source["synthetic"],
        "approval_status": "APPROVED",
        "entitlements": {"roles": roles, "domains": [dataset.domain.urn]},
        "grain": grain,
        "columns": columns,
        "owner_urn": owner["urn"],
        "domain_urn": dataset.domain.urn,
        "approved_lifecycle_urn": lifecycle["urn"],
    }


def _semantic_roles(
    metrics: list[Any],
    dimensions: object,
    time_rules: Mapping[str, Any],
) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for raw in metrics:
        metric = mapping(raw, "metric rule")
        source = mapping(metric.get("source"), "metric source")
        kind = source.get("kind")
        if kind == "column":
            field = mapping(source.get("field"), "metric field")
            result[(str(field.get("asset_fqn")), str(field.get("column")))] = "measure"
        elif kind != "ratio":
            raise SemanticMetadataError("metric source kind is unsupported")
        for dimension in array(metric.get("dimensions"), "metric dimensions"):
            value = mapping(dimension, "metric dimension")
            result[(str(value.get("asset_fqn")), str(value.get("column")))] = "dimension"
    for raw in array(dimensions, "dimensions"):
        item = mapping(raw, "dimension")
        result[(str(item.get("asset_fqn")), str(item.get("column")))] = "dimension"
    for raw in array(time_rules["fields"], "time fields", non_empty=True):
        field = mapping(mapping(raw, "time rule")["field"], "time field")
        result[(str(field.get("asset_fqn")), str(field.get("column")))] = "time"
    return result


def _metric_terms(
    value: object,
    metrics: list[Any],
    owner: Mapping[str, str],
    lifecycle: Mapping[str, str],
    bindings: tuple[ReleaseBinding, ...],
) -> list[dict[str, Any]]:
    domain_by_fqn = {
        binding.relation.fqn: binding.dataset.domain.urn
        for binding in bindings
        if binding.dataset.domain is not None
    }
    metric_by_id = {mapping(item, "metric").get("id"): mapping(item, "metric") for item in metrics}
    metric_domains = _metric_domains(metric_by_id, domain_by_fqn)
    result = []
    for index, raw in enumerate(array(value, "metric terms", non_empty=True)):
        item = mapping(raw, f"metric term[{index}]")
        required = {"id", "urn", "name", "definition", "aliases", "unit", "version"}
        exact_keys(item, required, f"metric term[{index}]")
        metric = metric_by_id.get(item["id"])
        if metric is None:
            raise SemanticMetadataError("metric term has no matching metric rule")
        domain = metric_domains.get(str(item["id"]))
        if domain is None:
            raise SemanticMetadataError("metric source has no live domain")
        result.append(
            {
                **deepcopy(dict(item)),
                "approval_status": "APPROVED",
                "owner_urn": owner["urn"],
                "domain_urn": domain,
                "approved_lifecycle_urn": lifecycle["urn"],
            }
        )
    return result


def _metric_domains(
    metrics: Mapping[object, Mapping[str, Any]],
    domain_by_fqn: Mapping[str, str],
) -> dict[str, str]:
    """column source와 동일-domain ratio 참조에서 metric별 native domain을 계산한다."""

    result: dict[str, str] = {}
    ratio_metrics: list[tuple[str, Mapping[str, Any]]] = []
    for raw_id, metric in metrics.items():
        metric_id = str(raw_id)
        source = mapping(metric.get("source"), "metric source")
        if source.get("kind") == "column":
            field = mapping(source.get("field"), "metric field")
            domain = domain_by_fqn.get(str(field.get("asset_fqn")))
            if domain is None:
                raise SemanticMetadataError("metric source has no live domain")
            result[metric_id] = domain
        elif source.get("kind") == "ratio":
            ratio_metrics.append((metric_id, source))
        else:
            raise SemanticMetadataError("metric source kind is unsupported")
    for metric_id, source in ratio_metrics:
        numerator = result.get(str(source.get("numerator_metric_id")))
        denominator = result.get(str(source.get("denominator_metric_id")))
        if numerator is None or numerator != denominator:
            raise SemanticMetadataError(
                "ratio metric operands must resolve one live native domain"
            )
        result[metric_id] = numerator
    return result


def _time_rules(value: object, bindings: tuple[ReleaseBinding, ...]) -> dict[str, Any]:
    rules = mapping(value, "time rules")
    required = {"timezone", "calendar_id", "interval", "start_parameter", "end_parameter", "fields"}
    exact_keys(rules, required, "time rules")
    types = {
        (binding.relation.fqn, column.name): column.native_type
        for binding in bindings
        for column in binding.relation.columns
    }
    fields = []
    for raw in array(rules["fields"], "time fields", non_empty=True):
        item = mapping(raw, "time rule")
        exact_keys(item, {"field", "bucket", "timezone_mode"}, "time rule")
        field = mapping(item["field"], "time field")
        key = (str(field.get("asset_fqn")), str(field.get("column")))
        native_type = types.get(key)
        if native_type is None:
            raise SemanticMetadataError("time rule references an unknown live field")
        fields.append({**deepcopy(dict(item)), "native_type": native_type})
    return {**{key: deepcopy(value) for key, value in rules.items() if key != "fields"}, "fields": fields}


def _logical_type(native_type: str) -> str:
    value = native_type.lower()
    if "bool" in value or value.startswith("uint8"):
        return "boolean"
    if value == "date" or value.startswith("date("):
        return "date"
    if "timestamp" in value or "datetime" in value or value.startswith("time"):
        return "time"
    if any(token in value for token in ("int", "decimal", "numeric", "double", "real", "float")):
        return "number"
    if value.startswith("array"):
        return "array"
    if value.startswith("map"):
        return "map"
    if value.startswith("row"):
        return "record"
    if any(token in value for token in ("binary", "varbinary", "blob")):
        return "bytes"
    return "string"


def _canonical_text(value: object, context: str) -> str:
    """외부 metadata의 양끝 공백만 제거하고 빈 설명은 거부한다."""

    if not isinstance(value, str) or not value.strip():
        raise SemanticMetadataError(f"{context} must be non-empty text")
    return value.strip()
