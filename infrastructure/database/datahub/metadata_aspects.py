"""검증된 semantic metadata를 DataHub v1.7 aspect로 결정론적으로 렌더링한다."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from src.data.governance_contract import (
    column_metric_asset,
    dataset_runtime_property_projection,
    dimension_member_term_runtime_property_projection,
    dimension_members,
    metric_asset_fqns,
    release_manifest,
    term_runtime_property_projection,
)
from src.data.metric_governance import metric_visibility
from metadata_contract import (
    PROPERTY_PREFIX,
    validate_bundle,
)


Aspect = tuple[str, str, str, dict[str, Any]]


def iter_aspects(bundle: Mapping[str, Any]) -> Iterator[Aspect]:
    """전체 검증 뒤 glossary와 dataset upsert를 결정론적 순서로 생성한다."""

    validate_bundle(bundle)
    manifest = release_manifest(bundle)
    metrics = list(bundle["metric_rules"])
    metrics_by_id = {item["id"]: item for item in metrics}
    terms = {item["id"]: item for item in bundle["metric_terms"]}
    members = dimension_members(bundle)
    yield from _governance_aspects(bundle["governance_entities"])
    for term in bundle["metric_terms"]:
        yield from _term_aspects(term, _metric(metrics, term["id"]), manifest)
    for member in members:
        yield from _dimension_member_term_aspects(member, manifest)
    for asset in bundle["schema_context"]["assets"]:
        asset_metrics = [
            metric
            for metric in metrics
            if column_metric_asset(metric) == asset["fqn"]
        ]
        dataset_term_urns = [
            str(terms[metric["id"]]["urn"])
            for metric in metrics
            if metric["id"] in terms
            and asset["fqn"] in metric_asset_fqns(metric, metrics_by_id)
        ]
        dataset_term_urns.extend(
            str(member["urn"])
            for member in members
            if member["asset_fqn"] == asset["fqn"]
        )
        yield from _asset_aspects(
            bundle,
            asset,
            asset_metrics,
            terms,
            manifest,
            dataset_term_urns,
            [
                member
                for member in members
                if member["asset_fqn"] == asset["fqn"]
            ],
        )


def aspect_counts(bundle: Mapping[str, Any]) -> dict[str, int]:
    """발행 receipt에 기록할 entity와 column 수를 결정론적으로 계산한다."""

    assets = len(bundle["schema_context"]["assets"])
    terms = len(bundle["metric_terms"])
    members = len(dimension_members(bundle))
    columns = sum(len(asset["columns"]) for asset in bundle["schema_context"]["assets"])
    governance = bundle["governance_entities"]
    references = sum(len(governance[name]) for name in governance)
    return {
        "datasets": assets,
        "columns": columns,
        "metric_terms": terms,
        "dimension_member_terms": members,
        "governance_entities": references,
        "aspects": (
            2 * len(governance["domains"])
            + 3 * len(governance["approved_lifecycles"])
            + 7 * assets
            + 5 * (terms + members)
        ),
    }


def _governance_aspects(governance: Mapping[str, Any]) -> Iterator[Aspect]:
    for domain in governance["domains"]:
        yield "domain", domain["urn"], "domainKey", {
            "id": _urn_id(domain["urn"], "urn:li:domain:")
        }
        yield "domain", domain["urn"], "domainProperties", {
            "name": domain["name"],
            "description": domain["description"],
        }
    for lifecycle in governance["approved_lifecycles"]:
        yield "lifecycleStageType", lifecycle["urn"], "lifecycleStageTypeKey", {
            "id": _urn_id(lifecycle["urn"], "urn:li:lifecycleStageType:")
        }
        yield "lifecycleStageType", lifecycle["urn"], "lifecycleStageTypeInfo", {
            "name": lifecycle["name"],
            "description": lifecycle["description"],
            "entityTypes": ["dataset", "glossaryTerm"],
            "settings": {"hideInSearch": False},
        }
        yield "lifecycleStageType", lifecycle["urn"], "status", {"removed": False}


def _asset_aspects(
    bundle: Mapping[str, Any],
    asset: Mapping[str, Any],
    metrics: list[Mapping[str, Any]],
    terms: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
    dataset_term_urns: list[str],
    dimension_members_for_asset: list[Mapping[str, Any]],
) -> Iterator[Aspect]:
    urn, fqn = str(asset["urn"]), str(asset["fqn"])
    field_terms: dict[str, list[str]] = {}
    for metric in metrics:
        if metric_visibility(metric) != "BUSINESS":
            continue
        column = str(metric["source"]["field"]["column"])
        field_terms.setdefault(column, []).append(str(terms[metric["id"]]["urn"]))
    for member in dimension_members_for_asset:
        field_terms.setdefault(str(member["column"]), []).append(str(member["urn"]))
    runtime_properties = dataset_runtime_property_projection(bundle, asset, manifest)
    properties = {
        f"{PROPERTY_PREFIX}{key}": value for key, value in runtime_properties.items()
    }
    yield "dataset", urn, "datasetKey", dict(asset["dataset_key"])
    yield "dataset", urn, "datasetProperties", {
        "name": fqn,
        "qualifiedName": fqn,
        "description": asset["description"],
        "customProperties": properties,
    }
    yield "dataset", urn, "status", _status(asset)
    yield "dataset", urn, "ownership", _ownership(asset)
    yield "dataset", urn, "domains", {"domains": [asset["domain_urn"]]}
    yield "dataset", urn, "editableSchemaMetadata", {
        "editableSchemaFieldInfo": [
            _editable_field(column, field_terms.get(str(column["name"]), []))
            for column in asset["columns"]
        ]
    }
    yield "dataset", urn, "glossaryTerms", {
        "terms": [{"urn": term_urn} for term_urn in sorted(set(dataset_term_urns))]
    }


def _term_aspects(
    term: Mapping[str, Any],
    metric: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> Iterator[Aspect]:
    urn = str(term["urn"])
    # WHY: DataHub entity key는 업무 metric id가 아니라 URN의 canonical id다.
    # 두 값이 다르면 GMS가 key를 자동 정규화해 발행값과 read-back이 갈라진다.
    yield "glossaryTerm", urn, "glossaryTermKey", {
        "name": _urn_id(urn, "urn:li:glossaryTerm:")
    }
    yield "glossaryTerm", urn, "glossaryTermInfo", {
        "id": term["id"],
        "name": term["name"],
        "definition": term["definition"],
        "termSource": "INTERNAL",
        "sourceRef": term["version"],
        "customProperties": {
            f"{PROPERTY_PREFIX}{key}": value
            for key, value in term_runtime_property_projection(
                term,
                metric,
                manifest,
            ).items()
        },
    }
    yield "glossaryTerm", urn, "status", _status(term)
    yield "glossaryTerm", urn, "ownership", _ownership(term)
    yield "glossaryTerm", urn, "domains", {"domains": [term["domain_urn"]]}


def _dimension_member_term_aspects(
    member: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> Iterator[Aspect]:
    """승인 Dimension Member를 독립 Glossary Term으로 발행한다."""

    urn = str(member["urn"])
    yield "glossaryTerm", urn, "glossaryTermKey", {
        "name": _urn_id(urn, "urn:li:glossaryTerm:")
    }
    yield "glossaryTerm", urn, "glossaryTermInfo", {
        "id": member["id"],
        "name": member["name"],
        "definition": member["definition"],
        "termSource": "INTERNAL",
        "sourceRef": member["version"],
        "customProperties": {
            f"{PROPERTY_PREFIX}{key}": value
            for key, value in dimension_member_term_runtime_property_projection(
                member,
                manifest,
            ).items()
        },
    }
    yield "glossaryTerm", urn, "status", _status(member)
    yield "glossaryTerm", urn, "ownership", _ownership(member)
    yield "glossaryTerm", urn, "domains", {"domains": [member["domain_urn"]]}


def _editable_field(column: Mapping[str, Any], term_urns: list[str]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "fieldPath": column["name"],
        "description": column["description"],
    }
    if term_urns:
        value["glossaryTerms"] = {
            "terms": [{"urn": urn} for urn in sorted(term_urns)]
        }
    return value


def _status(value: Mapping[str, Any]) -> dict[str, Any]:
    return {"removed": False, "lifecycleStage": value["approved_lifecycle_urn"]}


def _ownership(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "owners": [{"owner": value["owner_urn"], "type": "TECHNICAL_OWNER"}]
    }


def _metric(metrics: list[Mapping[str, Any]], metric_id: str) -> Mapping[str, Any]:
    return next(item for item in metrics if item["id"] == metric_id)


def _urn_id(urn: str, prefix: str) -> str:
    return urn.removeprefix(prefix)
