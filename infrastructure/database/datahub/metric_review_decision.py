"""검증된 Metric 검토안을 checksum-bound v2 업무 승인 결정으로 승격한다.

이 모듈은 질문 문구나 특정 Metric ID를 알지 못한다. SQL 근거로 검증된 review,
현재 live release에서 재구성한 의미 계약, 명시적인 target version만 결합한다.
물리 URN·native type·ordinal은 이후 authoring discovery가 다시 결정한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from metadata_contract import validate_bundle
from metadata_contract_primitives import (
    SemanticMetadataError,
    array,
    exact_keys,
    mapping,
    text,
    unique_texts,
)
from metric_review_transition import READY_STATUS, plan_metric_review_transition
from policy_compiler import DECISION_CONTRACT_VERSION_V2
from src.data.governance_contract import canonical_sha256, catalog_hash
from src.data.metric_governance import (
    RUNTIME_GOVERNANCE_VERSION_V2,
    business_metric_ids,
    metric_contract_version,
)


APPROVAL_CONTRACT_VERSION = "answervice.metric_review_approval.v1"
APPROVAL_STATUS = "APPROVED_FOR_POLICY_DECISION"
_APPROVAL_KEYS = {
    "contract_version",
    "status",
    "authority_urn",
    "review_candidate_sha256",
    "source_sql_sha256",
    "baseline_catalog_version",
    "baseline_catalog_sha256",
    "business_metric_ids",
    "support_metric_ids",
    "decision_sha256",
    "decision",
}


def build_metric_review_approval(
    review: Mapping[str, Any],
    review_validation: Mapping[str, Any],
    baseline_bundle: Mapping[str, Any],
    *,
    catalog_version: str,
    policy_version: str,
    schema_context_version: str,
    schema_version: str,
    seed_version: str,
    glossary_version: str,
) -> dict[str, Any]:
    """제거 위험이 없는 검토안만 v2 compact decision과 승인 receipt로 만든다."""

    transition = plan_metric_review_transition(
        review,
        review_validation,
        baseline_bundle,
    )
    if transition["status"] != READY_STATUS:
        raise SemanticMetadataError(
            "metric review requires an explicit retirement decision before approval"
        )
    validate_bundle(baseline_bundle)
    source = mapping(review, "metric review")
    target_catalog = _target_version(
        catalog_version,
        "target catalog version",
        predecessor=text(baseline_bundle.get("catalog_version"), "baseline catalog version"),
    )
    target_policy = _target_version(policy_version, "target policy version")
    target_context = _target_version(
        schema_context_version,
        "target schema context version",
    )
    target_schema = _target_version(schema_version, "target schema version")
    target_seed = _target_version(seed_version, "target seed version")
    target_glossary = _target_version(glossary_version, "target glossary version")
    owner = _review_owner(source, baseline_bundle)
    lifecycle = _approved_lifecycle(baseline_bundle)
    assets = _baseline_assets(baseline_bundle)
    asset_fields = {
        str(asset["fqn"]): {
            str(mapping(column, "baseline column")["name"])
            for column in array(asset["columns"], "baseline columns", non_empty=True)
        }
        for asset in assets
    }
    metric_rules = [
        _metric_rule(mapping(item, "review metric"), asset_fields)
        for item in array(source.get("metrics"), "review metrics", non_empty=True)
    ]
    if metric_contract_version(metric_rules) != RUNTIME_GOVERNANCE_VERSION_V2:
        raise SemanticMetadataError("approved Metric Rules must use runtime governance v2")
    baseline_terms = {
        str(mapping(item, "baseline metric term")["id"]): mapping(
            item, "baseline metric term"
        )
        for item in array(baseline_bundle.get("metric_terms"), "baseline metric terms")
    }
    metric_terms = [
        _metric_term(rule, baseline_terms.get(str(rule["id"])), target_glossary)
        for rule in metric_rules
        if rule["governance"]["visibility"] == "BUSINESS"
    ]
    synthetic = _shared_asset_value(assets, "synthetic")
    if not isinstance(synthetic, bool):
        raise SemanticMetadataError("baseline synthetic provenance must be boolean")
    decision = {
        "contract_version": DECISION_CONTRACT_VERSION_V2,
        "catalog_version": target_catalog,
        "policy_version": target_policy,
        "schema_context_version": target_context,
        "schema_version": target_schema,
        "seed_version": target_seed,
        "synthetic": synthetic,
        "owner": owner,
        "approved_lifecycle": lifecycle,
        "roles": list(unique_texts(source.get("allowed_roles"), "allowed roles", non_empty=True)),
        "asset_grains": [
            {
                "fqn": asset["fqn"],
                **deepcopy(mapping(asset["grain"], "baseline asset grain")),
            }
            for asset in assets
        ],
        "metric_rules": metric_rules,
        "metric_terms": metric_terms,
        "dimensions": deepcopy(baseline_bundle["dimensions"]),
        "join_graph": deepcopy(baseline_bundle["join_graph"]),
        "time_rules": _decision_time_rules(
            baseline_bundle["time_rules"],
            array(source.get("metrics"), "review metrics", non_empty=True),
        ),
        "parameter_contract": deepcopy(baseline_bundle["parameter_contract"]),
        "query_policy": _query_policy(baseline_bundle["query_policy"], metric_rules),
    }
    business_ids = sorted(business_metric_ids(metric_rules))
    all_ids = {str(item["id"]) for item in metric_rules}
    approval = {
        "contract_version": APPROVAL_CONTRACT_VERSION,
        "status": APPROVAL_STATUS,
        "authority_urn": owner["urn"],
        "review_candidate_sha256": review_validation["candidate_sha256"],
        "source_sql_sha256": source["source_sql_sha256"],
        "baseline_catalog_version": baseline_bundle["catalog_version"],
        "baseline_catalog_sha256": catalog_hash(baseline_bundle),
        "business_metric_ids": business_ids,
        "support_metric_ids": sorted(all_ids - set(business_ids)),
        "decision_sha256": canonical_sha256(decision),
        "decision": decision,
    }
    return approval


def unwrap_metric_review_approval(document: Mapping[str, Any]) -> dict[str, Any]:
    """stdin approval receipt의 exact shape와 decision checksum을 검증해 결정을 반환한다."""

    approval = mapping(document, "metric review approval")
    exact_keys(approval, _APPROVAL_KEYS, "metric review approval")
    if (
        approval["contract_version"] != APPROVAL_CONTRACT_VERSION
        or approval["status"] != APPROVAL_STATUS
    ):
        raise SemanticMetadataError("metric review approval contract is unsupported")
    authority = text(approval["authority_urn"], "approval authority")
    if not authority.startswith("urn:li:corpGroup:"):
        raise SemanticMetadataError("metric review approval authority is invalid")
    for key in (
        "review_candidate_sha256",
        "source_sql_sha256",
        "baseline_catalog_sha256",
        "decision_sha256",
    ):
        value = text(approval[key], key.replace("_", " "))
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise SemanticMetadataError("metric review approval checksum is invalid")
    decision = mapping(approval["decision"], "approved policy decision")
    if canonical_sha256(decision) != approval["decision_sha256"]:
        raise SemanticMetadataError("metric review approval decision checksum differs")
    owner = mapping(decision.get("owner"), "approved decision owner")
    if owner.get("urn") != authority:
        raise SemanticMetadataError("metric review approval authority and owner differ")
    metrics = [mapping(item, "approved metric") for item in array(decision.get("metric_rules"), "approved metrics", non_empty=True)]
    business_ids = sorted(business_metric_ids(metrics))
    all_ids = {str(item["id"]) for item in metrics}
    if (
        list(unique_texts(approval["business_metric_ids"], "approved business metric ids"))
        != business_ids
        or list(unique_texts(approval["support_metric_ids"], "approved support metric ids"))
        != sorted(all_ids - set(business_ids))
    ):
        raise SemanticMetadataError("metric review approval Metric scope differs")
    return deepcopy(dict(decision))


def _metric_rule(
    review_metric: Mapping[str, Any],
    asset_fields: Mapping[str, set[str]],
) -> dict[str, Any]:
    """review 전용 formula/source 표현을 실행 가능한 v2 Rule 하나로 변환한다."""

    source = mapping(review_metric["source"], "review metric source")
    formula = mapping(review_metric["formula"], "review metric formula")
    if source.get("kind") == "COLUMN":
        asset = text(source.get("asset_fqn"), "review source asset")
        column = text(source.get("column"), "review source column")
        time = mapping(review_metric["time"], "review metric time")
        grain = mapping(review_metric["grain"], "review metric grain")
        required = {
            column,
            text(time.get("field"), "review time field"),
            *unique_texts(grain.get("keys"), "review grain keys", non_empty=True),
            *unique_texts(grain.get("dimensions"), "review grain dimensions"),
        }
        if asset not in asset_fields or not required <= asset_fields[asset]:
            raise SemanticMetadataError(
                "review Metric references a field outside the live baseline scope"
            )
        executable_source: dict[str, Any] = {
            "kind": "column",
            "field": {"asset_fqn": asset, "column": column},
        }
        aggregation = formula["aggregation"]
        reduction = formula["reduction"]
        time_field: dict[str, str] | None = {
            "asset_fqn": asset,
            "column": time["field"],
        }
        dimensions = [
            {"asset_fqn": asset, "column": dimension}
            for dimension in grain["dimensions"]
        ]
    elif source.get("kind") == "METRIC_OPERANDS":
        executable_source = {
            "kind": "ratio",
            "numerator_metric_id": formula["numerator_metric_id"],
            "denominator_metric_id": formula["denominator_metric_id"],
            "zero_policy": formula["zero_policy"],
        }
        aggregation = "ratio"
        reduction = "ratio"
        time_field = None
        dimensions = []
    else:
        raise SemanticMetadataError("review Metric source kind is unsupported")
    semantic_aliases = _semantic_aliases(
        text(review_metric["name"], "review Metric name"),
        review_metric["aliases"],
    )
    return {
        "id": review_metric["id"],
        "source": executable_source,
        "aggregation": aggregation,
        "result_field": review_metric["result_field"],
        "unit": review_metric["unit"],
        "time_field": time_field,
        "reduction": reduction,
        "dimensions": dimensions,
        "required_filters": [],
        "governance": {
            "visibility": review_metric["visibility"],
            "semantic": {
                "name": review_metric["name"],
                "definition": review_metric["definition"],
                "aliases": semantic_aliases,
            },
            "grain": deepcopy(review_metric["grain"]),
            "time": {
                key: deepcopy(review_metric["time"][key])
                for key in ("field", "semantics", "timezone", "interval")
            },
            "join": deepcopy(review_metric["join"]),
            "permission": deepcopy(review_metric["permission"]),
            "query_strategies": deepcopy(review_metric["query_strategies"]),
        },
    }


def _metric_term(
    rule: Mapping[str, Any],
    baseline_term: Mapping[str, Any] | None,
    glossary_version: str,
) -> dict[str, Any]:
    """BUSINESS Rule만 공개 Glossary Term으로 만들고 기존 identity는 보존한다."""

    semantic = mapping(mapping(rule["governance"], "metric governance")["semantic"], "metric semantic")
    metric_id = str(rule["id"])
    urn = (
        text(baseline_term["urn"], "baseline term URN")
        if baseline_term is not None
        else f"urn:li:glossaryTerm:{metric_id}"
    )
    return {
        "id": metric_id,
        "urn": urn,
        "name": semantic["name"],
        "definition": semantic["definition"],
        "aliases": deepcopy(semantic["aliases"]),
        "unit": rule["unit"],
        "version": glossary_version,
    }


def _review_owner(
    review: Mapping[str, Any],
    baseline_bundle: Mapping[str, Any],
) -> dict[str, str]:
    urn = text(review.get("review_owner_candidate_urn"), "review owner candidate")
    governance = mapping(baseline_bundle["governance_entities"], "baseline governance")
    owners = {
        str(mapping(item, "baseline owner")["urn"]): mapping(item, "baseline owner")
        for item in array(governance.get("owners"), "baseline owners", non_empty=True)
    }
    if urn not in owners:
        raise SemanticMetadataError("review owner is not a governed live CorpGroup")
    return deepcopy(dict(owners[urn]))


def _approved_lifecycle(baseline_bundle: Mapping[str, Any]) -> dict[str, str]:
    governance = mapping(baseline_bundle["governance_entities"], "baseline governance")
    approved = [
        mapping(item, "baseline lifecycle")
        for item in array(
            governance.get("approved_lifecycles"),
            "baseline approved lifecycles",
            non_empty=True,
        )
        if mapping(item, "baseline lifecycle").get("name") == "APPROVED"
    ]
    if len(approved) != 1:
        raise SemanticMetadataError("baseline must contain one APPROVED lifecycle")
    return deepcopy(dict(approved[0]))


def _baseline_assets(baseline_bundle: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    schema = mapping(baseline_bundle["schema_context"], "baseline schema context")
    return sorted(
        (mapping(item, "baseline asset") for item in array(schema.get("assets"), "baseline assets", non_empty=True)),
        key=lambda item: str(item["fqn"]),
    )


def _shared_asset_value(assets: list[Mapping[str, Any]], key: str) -> Any:
    values = {asset[key] for asset in assets}
    if len(values) != 1:
        raise SemanticMetadataError(f"baseline assets do not share one {key}")
    return deepcopy(values.pop())


def _decision_time_rules(value: object, review_metrics: list[Any]) -> dict[str, Any]:
    """기존 전역 시간 규칙에 review가 명시한 새 column scope를 충돌 없이 병합한다."""

    rules = mapping(value, "baseline time rules")
    result = deepcopy(dict(rules))
    fields: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in array(rules.get("fields"), "baseline time fields", non_empty=True):
        item = {
            key: deepcopy(item_value)
            for key, item_value in mapping(raw, "baseline time field").items()
            if key != "native_type"
        }
        field = mapping(item["field"], "baseline time field identity")
        fields[(str(field["asset_fqn"]), str(field["column"]))] = item
    for raw in review_metrics:
        metric = mapping(raw, "review metric")
        source = mapping(metric["source"], "review metric source")
        if source.get("kind") != "COLUMN":
            continue
        time = mapping(metric["time"], "review metric time")
        if time["timezone"] != rules["timezone"]:
            raise SemanticMetadataError(
                "review Metric timezone differs from the baseline release"
            )
        key = (str(source["asset_fqn"]), str(time["field"]))
        approved = {
            "field": {"asset_fqn": key[0], "column": key[1]},
            "bucket": time["bucket"],
            "timezone_mode": time["timezone_mode"],
        }
        previous = fields.get(key)
        if previous is not None and previous != approved:
            raise SemanticMetadataError(
                "review Metric time rule conflicts with the baseline release"
            )
        fields[key] = approved
    result["fields"] = [fields[key] for key in sorted(fields)]
    return result


def _semantic_aliases(name: str, value: object) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for alias in (name, *unique_texts(value, "review Metric aliases", non_empty=True)):
        normalized = alias.casefold()
        if normalized not in seen:
            seen.add(normalized)
            result.append(alias)
    return result


def _query_policy(value: object, metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """검토된 계산식이 필수로 사용하는 함수만 기존 정책에 결정론적으로 추가한다."""
    policy = deepcopy(dict(mapping(value, "baseline query policy")))
    allowed = list(
        unique_texts(
            policy.get("allowed_functions"),
            "baseline query policy allowed functions",
        )
    )
    normalized = {item.casefold() for item in allowed}
    aggregation_functions = {
        "sum": "sum",
        "count": "count",
        "count_distinct": "count",
        "min": "min",
        "max": "max",
        "average": "avg",
    }
    required: set[str] = set()
    for metric in metrics:
        aggregation = str(metric["aggregation"])
        function = aggregation_functions.get(aggregation)
        if function is not None:
            required.add(function)
        if mapping(metric["source"], "approved metric source").get("kind") == "ratio":
            required.add("nullif")
    for function in sorted(required):
        if function.casefold() not in normalized:
            normalized.add(function.casefold())
            allowed.append(function)
    policy["allowed_functions"] = allowed
    return policy


def _target_version(value: object, context: str, *, predecessor: str | None = None) -> str:
    result = text(value, context)
    if len(result) > 255 or result == predecessor:
        raise SemanticMetadataError(f"{context} is invalid or not a successor")
    return result
