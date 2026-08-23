"""DataHub GraphQL 재조회 결과를 publication 계약과 대조해 검증한다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from metadata_aspects import iter_aspects
from metadata_contract import PROPERTY_PREFIX
from src.data.governance_contract import (
    datahub_schema_readback_sha1,
    metric_asset_fqns,
)


DATASET_QUERY = """
query PublishedDataset($urn: String!) {
  dataset(urn: $urn) {
    urn name
    status { removed lifecycleStage { urn name } }
    ownership {
      owners {
        type associatedUrn ownershipType { urn }
        owner { ... on CorpUser { urn } ... on CorpGroup { urn } }
      }
    }
    domain { domain { urn } }
    properties { name qualifiedName description customProperties { key value } }
    glossaryTerms { terms { term { urn } } }
    schemaMetadata {
      version name hash
      fields {
        fieldPath nativeDataType nullable isPartOfKey description
        glossaryTerms { terms { term { urn } } }
      }
    }
    editableSchemaMetadata {
      editableSchemaFieldInfo { fieldPath description }
    }
  }
}
""".strip()

TERM_QUERY = """
query PublishedGlossaryTerm($urn: String!) {
  glossaryTerm(urn: $urn) {
    urn exists
    status { removed lifecycleStage { urn name } }
    ownership {
      owners {
        type associatedUrn ownershipType { urn }
        owner { ... on CorpUser { urn } ... on CorpGroup { urn } }
      }
    }
    domain { domain { urn } }
    glossaryTermInfo {
      name description termSource sourceRef customProperties { key value }
    }
  }
}
""".strip()

SEARCH_QUERY = """
query GovernedReleaseEntities($input: SearchAcrossEntitiesInput!) {
  searchAcrossEntities(input: $input) {
    start count total
    searchResults { entity { urn type } }
  }
}
""".strip()


async def verify_graphql(client: Any, bundle: Mapping[str, Any]) -> None:
    """거버넌스 release 구성원 전체와 native GraphQL field를 정확히 검증한다."""

    expected = _expected_aspects(bundle)
    terms = {term["id"]: term for term in bundle["metric_terms"]}
    metrics = list(bundle["metric_rules"])
    first_asset = bundle["schema_context"]["assets"][0]
    catalog_digest = expected[first_asset["urn"]]["datasetProperties"][
        "customProperties"
    ][f"{PROPERTY_PREFIX}catalog_sha256"]
    datasets = await _release_entities(
        client, "DATASET", "dataset", DATASET_QUERY, catalog_digest
    )
    glossary_terms = await _release_entities(
        client, "GLOSSARY_TERM", "glossaryTerm", TERM_QUERY, catalog_digest
    )
    _assert_release_membership(
        datasets,
        {asset["urn"] for asset in bundle["schema_context"]["assets"]},
        "dataset",
    )
    _assert_release_membership(
        glossary_terms,
        {term["urn"] for term in bundle["metric_terms"]},
        "glossary term",
    )
    for asset in bundle["schema_context"]["assets"]:
        value = datasets[asset["urn"]]
        _assert_native(value, asset)
        _assert_dataset(value, asset, metrics, terms, expected[asset["urn"]])
    for term in bundle["metric_terms"]:
        value = glossary_terms[term["urn"]]
        # WHY: pinned DataHub v1.7 GraphQL은 GlossaryTerm.status를 null로 반환한다.
        # status/lifecycle은 직전 Rest.li 전체 aspect 검증이 권위 있게 대조한다.
        _assert_native(value, term, require_graphql_status=False)
        _assert_term(value, term, expected[term["urn"]])


async def _release_entities(
    client: Any,
    entity_type: str,
    field: str,
    entity_query: str,
    catalog_digest: str,
) -> dict[str, dict[str, Any]]:
    start, page_size, total_bound = 0, 100, 10_000
    result: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    while True:
        payload = await client.graphql(
            SEARCH_QUERY,
            {"input": {"types": [entity_type], "query": "*", "start": start, "count": page_size}},
        )
        page = payload.get("data", {}).get("searchAcrossEntities")
        rows = page.get("searchResults") if isinstance(page, dict) else None
        total = page.get("total") if isinstance(page, dict) else None
        if (
            not isinstance(rows, list)
            or not isinstance(total, int)
            or total < 0
            or total > total_bound
            or page.get("start") != start
        ):
            raise ValueError("DataHub GraphQL search pagination is invalid")
        for row in rows:
            entity = row.get("entity") if isinstance(row, dict) else None
            urn = entity.get("urn") if isinstance(entity, dict) else None
            if (
                not isinstance(urn, str)
                or entity.get("type") != entity_type
                or urn in seen
            ):
                raise ValueError("DataHub GraphQL search entity identity is invalid")
            seen.add(urn)
            entity_payload = await client.graphql(entity_query, {"urn": urn})
            value = _entity(entity_payload, field, urn)
            if _catalog_digest(value, field) == catalog_digest:
                result[urn] = value
        if start + len(rows) >= total:
            break
        if not rows:
            raise ValueError("DataHub GraphQL search pagination made no progress")
        start += len(rows)
    if len(seen) != total:
        raise ValueError("DataHub GraphQL search total does not match its result set")
    return result


def _catalog_digest(value: Mapping[str, Any], field: str) -> str | None:
    container = value.get("properties") if field == "dataset" else value.get("glossaryTermInfo")
    properties = container.get("customProperties") if isinstance(container, dict) else None
    if not isinstance(properties, list):
        return None
    values = {
        item.get("key"): item.get("value")
        for item in properties
        if isinstance(item, dict) and set(item) >= {"key", "value"}
    }
    digest = values.get(f"{PROPERTY_PREFIX}catalog_sha256")
    return digest if isinstance(digest, str) else None


def _assert_release_membership(
    actual: Mapping[str, Any], expected: set[str], entity_name: str
) -> None:
    if set(actual) != expected:
        raise ValueError(f"DataHub governed {entity_name} release membership mismatch")


def _expected_aspects(bundle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for _entity_type, urn, aspect, value in iter_aspects(bundle):
        result.setdefault(urn, {})[aspect] = value
    return result


def _entity(payload: object, field: str, urn: str) -> dict[str, Any]:
    value = payload.get("data", {}).get(field) if isinstance(payload, dict) else None
    if not isinstance(value, dict) or value.get("urn") != urn:
        raise ValueError(f"DataHub GraphQL did not return governed {field}: {urn}")
    return value


def _assert_native(
    value: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    require_graphql_status: bool = True,
) -> None:
    """GraphQL이 노출하는 native owner/domain과 지원 entity의 status를 대조한다."""

    status = value.get("status")
    lifecycle = status.get("lifecycleStage") if isinstance(status, dict) else None
    if require_graphql_status and (
        not isinstance(status, dict)
        or status.get("removed") is not False
        or not isinstance(lifecycle, dict)
        or lifecycle.get("urn") != expected["approved_lifecycle_urn"]
        or lifecycle.get("name") != "APPROVED"
    ):
        raise ValueError("DataHub native APPROVED lifecycle readback mismatch")
    ownership = value.get("ownership")
    owners = ownership.get("owners") if isinstance(ownership, dict) else None
    owner_urns = {
        item.get("owner", {}).get("urn")
        for item in owners or []
        if isinstance(item, dict) and isinstance(item.get("owner"), dict)
    }
    if (
        owner_urns != {expected["owner_urn"]}
        or len(owners or []) != 1
        or owners[0].get("type") != "TECHNICAL_OWNER"
        or owners[0].get("associatedUrn") != expected["urn"]
        or owners[0].get("ownershipType", {}).get("urn")
        != "urn:li:ownershipType:__system__technical_owner"
    ):
        raise ValueError("DataHub native owner readback mismatch")
    domain = value.get("domain")
    domain_value = domain.get("domain") if isinstance(domain, dict) else None
    if not isinstance(domain_value, dict) or domain_value.get("urn") != expected["domain_urn"]:
        raise ValueError("DataHub native domain readback mismatch")


def _assert_dataset(
    value: Mapping[str, Any],
    asset: Mapping[str, Any],
    metrics: list[Mapping[str, Any]],
    terms: Mapping[str, Mapping[str, Any]],
    aspects: Mapping[str, Any],
) -> None:
    fqn = asset["fqn"]
    properties = value.get("properties")
    if value.get("name") != fqn or not isinstance(properties, dict):
        raise ValueError("DataHub dataset identity readback mismatch")
    expected_properties = aspects["datasetProperties"]
    for name in ("name", "qualifiedName", "description"):
        if properties.get(name) != expected_properties[name]:
            raise ValueError(f"DataHub dataset property readback mismatch: {name}")
    _assert_custom_properties(
        properties.get("customProperties"),
        expected_properties["customProperties"],
    )
    schema = value.get("schemaMetadata")
    if (
        not isinstance(schema, dict)
        or schema.get("name") != asset["schema_name"]
        or schema.get("version") != asset["schema_metadata_version"]
    ):
        raise ValueError("DataHub base schema identity readback mismatch")
    # WHY: pinned v1.7은 editableSchemaMetadata의 field glossary 연결을
    # schemaMetadata.fields.glossaryTerms에 투영하지 않는다. 컬럼별 exact mapping은
    # Rest.li aspect 검증이 담당하고 GraphQL은 dataset aggregate를 교차검증한다.
    if _assert_fields(schema.get("fields"), asset["columns"]) != asset["datahub_schema_hash"]:
        raise ValueError("DataHub base schema fingerprint readback mismatch")
    _assert_editable_descriptions(value.get("editableSchemaMetadata"), asset["columns"])
    if _term_urns(value.get("glossaryTerms")) != _dataset_terms(
        asset, metrics, terms
    ):
        raise ValueError("DataHub dataset glossary association readback mismatch")


def _assert_term(
    value: Mapping[str, Any],
    term: Mapping[str, Any],
    aspects: Mapping[str, Any],
) -> None:
    info = value.get("glossaryTermInfo")
    expected = aspects["glossaryTermInfo"]
    if value.get("exists") is not True or not isinstance(info, dict):
        raise ValueError("DataHub glossary term does not exist")
    for actual_name, expected_name in (
        ("name", "name"),
        ("description", "definition"),
        ("termSource", "termSource"),
        ("sourceRef", "sourceRef"),
    ):
        if info.get(actual_name) != expected[expected_name]:
            raise ValueError(f"DataHub glossary term readback mismatch: {actual_name}")
    _assert_custom_properties(info.get("customProperties"), expected["customProperties"])


def _assert_fields(
    value: object,
    columns: list[Mapping[str, Any]],
) -> str:
    if not isinstance(value, list):
        raise ValueError("DataHub base schema fields are missing")
    fields = {
        field.get("fieldPath"): field for field in value if isinstance(field, dict)
    }
    if len(fields) != len(value) or set(fields) != {column["name"] for column in columns}:
        raise ValueError("DataHub base schema field set mismatch")
    for column in columns:
        field = fields[column["name"]]
        if not isinstance(field.get("nativeDataType"), str) or not field["nativeDataType"].strip():
            raise ValueError(
                f"DataHub schema field native type is missing: {column['name']}"
            )
        for graph_name, contract_name in (
            ("nullable", "nullable"),
            ("isPartOfKey", "is_part_of_key"),
        ):
            if field.get(graph_name) != column[contract_name]:
                raise ValueError(f"DataHub schema field mismatch: {column['name']}.{graph_name}")
    return datahub_schema_readback_sha1(
        [
            {
                "ordinal_position": ordinal,
                "name": field["fieldPath"],
                "native_type": field["nativeDataType"].strip(),
                "nullable": field["nullable"],
            }
            for ordinal, field in enumerate(value, start=1)
        ]
    )


def _assert_editable_descriptions(
    value: object,
    columns: list[Mapping[str, Any]],
) -> None:
    if not isinstance(value, dict) or not isinstance(
        value.get("editableSchemaFieldInfo"), list
    ):
        raise ValueError("DataHub editable schema fields are missing")
    fields = value["editableSchemaFieldInfo"]
    by_name = {
        field.get("fieldPath"): field for field in fields if isinstance(field, dict)
    }
    if len(by_name) != len(fields) or set(by_name) != {
        column["name"] for column in columns
    }:
        raise ValueError("DataHub editable schema field set mismatch")
    for column in columns:
        if by_name[column["name"]].get("description") != column["description"]:
            raise ValueError(
                f"DataHub editable field description mismatch: {column['name']}"
            )


def _dataset_terms(
    asset: Mapping[str, Any],
    metrics: list[Mapping[str, Any]],
    terms: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    """직접 column metric과 operand로 연결된 derived ratio term의 dataset association을 계산한다."""

    metrics_by_id = {str(metric["id"]): metric for metric in metrics}
    return {
        str(terms[str(metric["id"])]["urn"])
        for metric in metrics
        # SUPPORT operands are execution facts and intentionally have no searchable
        # GlossaryTerm. This must match metadata_aspects._asset_aspects exactly.
        if str(metric["id"]) in terms
        if asset["fqn"] in metric_asset_fqns(metric, metrics_by_id)
    }


def _assert_custom_properties(value: object, expected: Mapping[str, str]) -> None:
    if not isinstance(value, list):
        raise ValueError("DataHub custom property readback is missing")
    properties = {
        item.get("key"): item.get("value")
        for item in value
        if isinstance(item, dict) and set(item) >= {"key", "value"}
    }
    governed = {key: item for key, item in properties.items() if str(key).startswith(PROPERTY_PREFIX)}
    if governed != dict(expected):
        raise ValueError("DataHub governed custom property readback mismatch")


def _term_urns(value: object) -> set[str]:
    if value is None:
        return set()
    terms = value.get("terms") if isinstance(value, dict) else None
    if not isinstance(terms, list):
        raise ValueError("DataHub glossary association readback is invalid")
    return {
        item.get("term", {}).get("urn")
        for item in terms
        if isinstance(item, dict) and isinstance(item.get("term"), dict)
    }
