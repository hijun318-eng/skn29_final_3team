"""v2 Metric의 Business Glossary 경계와 물리·권한·조인 교차계약을 검증한다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from metadata_contract_primitives import (
    SemanticMetadataError,
    array,
    exact_keys,
    identifier,
    mapping,
    text,
    unique_texts,
    urn,
)
from src.data.governance_contract import metric_asset_fqns
from src.data.metric_governance import (
    RUNTIME_GOVERNANCE_VERSION_V1,
    business_metric_ids,
    metric_contract_version,
    metric_governance,
)


_TERM_KEYS = {
    "id",
    "urn",
    "name",
    "definition",
    "aliases",
    "unit",
    "version",
    "approval_status",
    "owner_urn",
    "domain_urn",
    "approved_lifecycle_urn",
}


def validate_metric_terms(
    value: object,
    metrics: Mapping[str, Mapping[str, Any]],
    metric_domains: Mapping[str, str],
    governance: Mapping[str, frozenset[str]],
) -> None:
    """v1은 모든 Rule, v2는 BUSINESS Rule에만 정확히 한 Glossary Term을 요구한다."""

    terms: dict[str, Mapping[str, Any]] = {}
    urns: set[str] = set()
    versions: set[str] = set()
    for index, raw in enumerate(array(value, "metric_terms", non_empty=True, limit=64)):
        context = f"metric_term[{index}]"
        term = mapping(raw, context)
        exact_keys(term, _TERM_KEYS, context)
        metric_id = identifier(term["id"], f"{context}.id")
        term_urn = text(term["urn"], f"{context}.urn")
        text(term["name"], f"{context}.name")
        text(term["definition"], f"{context}.definition")
        versions.add(text(term["version"], f"{context}.version"))
        if term["approval_status"] != "APPROVED":
            raise SemanticMetadataError("metric terms must be explicitly approved")
        urn(term["owner_urn"], "urn:li:corpGroup:", f"{context}.owner_urn")
        urn(term["domain_urn"], "urn:li:domain:", f"{context}.domain_urn")
        urn(
            term["approved_lifecycle_urn"],
            "urn:li:lifecycleStageType:",
            f"{context}.approved_lifecycle_urn",
        )
        if (
            term["owner_urn"] not in governance["owners"]
            or term["domain_urn"] not in governance["domains"]
            or term["approved_lifecycle_urn"]
            not in governance["approved_lifecycles"]
        ):
            raise SemanticMetadataError(
                "metric term native governance references are undeclared"
            )
        aliases = unique_texts(term["aliases"], f"{context}.aliases", non_empty=True)
        metric = metrics.get(metric_id)
        if (
            metric is None
            or metric_id in terms
            or term_urn in urns
            or not term_urn.startswith("urn:li:glossaryTerm:")
            or term["unit"] != metric["unit"]
            or term["name"] not in aliases
            or term["domain_urn"] != metric_domains.get(metric_id)
        ):
            raise SemanticMetadataError("metric terms must exactly describe metric rules")
        _validate_v2_term_semantics(term, metric)
        terms[metric_id] = term
        urns.add(term_urn)

    try:
        version = metric_contract_version(metrics.values())
        expected = (
            frozenset(metrics)
            if version == RUNTIME_GOVERNANCE_VERSION_V1
            else business_metric_ids(metrics.values())
        )
    except ValueError as error:
        raise SemanticMetadataError(str(error)) from error
    if set(terms) != expected:
        raise SemanticMetadataError(
            "Glossary terms must exactly cover the release business metrics"
        )
    if len(versions) != 1:
        raise SemanticMetadataError("one publication bundle must use one glossary version")
    _validate_business_aliases(terms)


def validate_v2_metric_release(
    bundle: Mapping[str, Any],
    metrics: Mapping[str, Mapping[str, Any]],
) -> None:
    """v2 Rule이 실제 asset grain·time·entitlement·join graph와 일치하는지 검증한다."""

    try:
        if metric_contract_version(metrics.values()) == RUNTIME_GOVERNANCE_VERSION_V1:
            return
    except ValueError as error:
        raise SemanticMetadataError(str(error)) from error
    assets = {
        str(asset["fqn"]): asset for asset in bundle["schema_context"]["assets"]
    }
    edges = {
        str(edge["id"]): edge for edge in bundle["join_graph"]["edges"]
    }
    time_fields = {
        (str(item["field"]["asset_fqn"]), str(item["field"]["column"]))
        for item in bundle["time_rules"]["fields"]
    }
    release_timezone = str(bundle["time_rules"]["timezone"])
    for metric_id, metric in metrics.items():
        governance = metric_governance(metric)
        if governance is None:
            raise SemanticMetadataError("v2 metric governance is unavailable")
        source_fqns = metric_asset_fqns(metric, metrics)
        if len(source_fqns) != 1:
            raise SemanticMetadataError(
                "v2 metrics must resolve one physical calculation scope"
            )
        source_fqn = next(iter(source_fqns))
        asset = assets.get(source_fqn)
        if asset is None:
            raise SemanticMetadataError("metric source asset is outside the release")
        _validate_asset_scope(
            metric_id,
            governance,
            asset,
            source_fqn,
            time_fields,
            release_timezone,
        )
        _validate_permission(governance, asset)
        _validate_join_scope(governance, source_fqn, edges)
        if metric.get("source", {}).get("kind") == "ratio":
            _validate_ratio_governance(metric, governance, metrics)


def _validate_v2_term_semantics(
    term: Mapping[str, Any], metric: Mapping[str, Any]
) -> None:
    governance = metric_governance(metric)
    if governance is None:
        return
    semantic = mapping(governance["semantic"], "metric governance semantic")
    if any(
        term[key] != semantic[key]
        for key in ("name", "definition", "aliases")
    ):
        raise SemanticMetadataError(
            "business Glossary term differs from its v2 metric semantics"
        )


def _validate_asset_scope(
    metric_id: str,
    governance: Mapping[str, Any],
    asset: Mapping[str, Any],
    source_fqn: str,
    time_fields: set[tuple[str, str]],
    release_timezone: str,
) -> None:
    grain = mapping(governance["grain"], f"metric[{metric_id}].grain")
    asset_grain = mapping(asset["grain"], f"asset[{source_fqn}].grain")
    columns = {str(column["name"]) for column in asset["columns"]}
    if (
        set(map(str, grain["keys"])) != set(map(str, asset_grain["keys"]))
        or not set(map(str, grain["dimensions"])).issubset(columns)
    ):
        raise SemanticMetadataError("metric grain differs from its physical asset grain")
    time = mapping(governance["time"], f"metric[{metric_id}].time")
    if (
        (source_fqn, str(time["field"])) not in time_fields
        or time["timezone"] != release_timezone
    ):
        raise SemanticMetadataError("metric time governance differs from release time rules")


def _validate_permission(
    governance: Mapping[str, Any], asset: Mapping[str, Any]
) -> None:
    permission = mapping(governance["permission"], "metric permission")
    asset_entitlements = mapping(asset["entitlements"], "asset entitlements")
    roles = set(map(str, permission["roles"]))
    if (
        not roles.issubset(set(map(str, asset_entitlements["roles"])))
        or permission["synthetic"] is not asset["synthetic"]
    ):
        raise SemanticMetadataError("metric permission exceeds its source asset")


def _validate_join_scope(
    governance: Mapping[str, Any],
    source_fqn: str,
    edges: Mapping[str, Mapping[str, Any]],
) -> None:
    join = mapping(governance["join"], "metric join policy")
    for edge_id in map(str, join["allowed_edge_ids"]):
        edge = edges.get(edge_id)
        if edge is None or source_fqn not in {edge["left"], edge["right"]}:
            raise SemanticMetadataError(
                "metric join policy references an unrelated or unknown edge"
            )


def _validate_ratio_governance(
    metric: Mapping[str, Any],
    governance: Mapping[str, Any],
    metrics: Mapping[str, Mapping[str, Any]],
) -> None:
    source = mapping(metric["source"], "ratio source")
    operands = (
        metrics[str(source["numerator_metric_id"])],
        metrics[str(source["denominator_metric_id"])],
    )
    for operand in operands:
        operand_governance = metric_governance(operand)
        if operand_governance is None or any(
            governance[key] != operand_governance[key]
            for key in ("grain", "time", "join", "permission", "query_strategies")
        ):
            raise SemanticMetadataError(
                "ratio metric governance must match both executable operands"
            )


def _validate_business_aliases(terms: Mapping[str, Mapping[str, Any]]) -> None:
    observed: dict[str, str] = {}
    for metric_id, term in terms.items():
        for alias in term["aliases"]:
            normalized = " ".join(str(alias).casefold().split())
            previous = observed.get(normalized)
            if previous is not None and previous != metric_id:
                raise SemanticMetadataError(
                    "business metric aliases must be globally unambiguous"
                )
            observed[normalized] = metric_id
