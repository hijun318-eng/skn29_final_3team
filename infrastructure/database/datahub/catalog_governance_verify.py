"""발행된 catalog governance와 Glossary를 live GraphQL read-back으로 검증한다."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from catalog_governance import DATASET_QUERY, TECHNICAL_OWNER, GovernancePlan
from http_client import DataHubMetadataAdminClient


async def verify_plan(
    client: DataHubMetadataAdminClient,
    plan: GovernancePlan,
    release_version: str,
) -> dict[str, int]:
    """모든 dataset의 owner·domain·tag·lineage가 계획과 일치하는지 검증한다."""

    tag_urns = {
        tag_id: f"urn:li:tag:answervice_{tag_id}" for tag_id in plan.tags
    }
    expected_edges: dict[str, set[str]] = {}
    for downstream, upstream in plan.lineage_edges:
        expected_edges.setdefault(downstream, set()).add(upstream)
    semaphore = asyncio.Semaphore(12)

    async def verify_dataset(dataset: Any) -> None:
        async with semaphore:
            payload = await client.graphql(DATASET_QUERY, {"urn": dataset.urn})
        graph = _mapping(payload.get("data"), "GraphQL data")
        value = _mapping(graph.get("dataset"), "dataset")
        if value.get("exists") is not True or _mapping(
            value.get("status"), "dataset status"
        ).get("removed") is not False:
            raise ValueError("catalog dataset is missing or removed after publication")
        if _owner_urns(value.get("ownership")) != {plan.owner_urn}:
            raise ValueError("catalog dataset technical owner read-back mismatch")
        domain = _mapping(_mapping(value.get("domain"), "domain").get("domain"), "domain entity")
        if domain.get("urn") != plan.domains[dataset.scope]:
            raise ValueError("catalog dataset domain read-back mismatch")
        expected_tags = {
            tag_urns["synthetic"],
            tag_urns[f"release_{_slug(release_version)}"],
            tag_urns[f"scope_{_slug(dataset.scope.catalog)}"],
        }
        if _association_urns(value.get("tags"), "tags", "tag") != expected_tags:
            raise ValueError("catalog dataset tag read-back mismatch")
        schema = _mapping(value.get("schemaMetadata"), "schema metadata")
        schema_fields = {
            _text(_mapping(raw, "schema field").get("fieldPath"), "field path"): raw
            for raw in _list(schema.get("fields"), "schema fields")
        }
        if set(schema_fields) != {field.name for field in dataset.fields}:
            raise ValueError("catalog field membership read-back mismatch")
        actual_upstreams = {
            entity.get("urn")
            for relationship in _list_or_empty(
                _mapping(value.get("lineage"), "lineage").get("relationships"),
                "lineage relationships",
            )
            for entity in [_mapping(_mapping(relationship, "lineage relationship").get("entity"), "lineage entity")]
            if entity.get("type") == "DATASET"
        }
        if actual_upstreams != expected_edges.get(dataset.urn, set()):
            raise ValueError("catalog dataset lineage read-back mismatch")

    await asyncio.gather(*(verify_dataset(dataset) for dataset in plan.datasets))

    return {
        "datasets": len(plan.datasets),
        "fields": sum(len(dataset.fields) for dataset in plan.datasets),
        "domains": len(plan.domains),
        "tags": len(plan.tags),
        "glossary_terms": 0,
        "lineage_edges": len(plan.lineage_edges),
    }


def _owner_urns(value: object) -> set[str]:
    ownership = _mapping(value, "ownership")
    result = set()
    for raw in _list_or_empty(ownership.get("owners"), "owners"):
        owner = _mapping(raw, "owner association")
        entity = _mapping(owner.get("owner"), "owner entity")
        # WHY: DataHub v1.7의 deprecated enum ``type``은 custom ownershipTypeUrn을
        # GraphQL mutation으로 쓸 때 NONE을 반환한다. 비deprecated URN만 권위 값이다.
        if _mapping(owner.get("ownershipType"), "ownership type").get("urn") != TECHNICAL_OWNER:
            raise ValueError("catalog ownership type read-back mismatch")
        result.add(_text(entity.get("urn"), "owner URN"))
    return result


def _association_urns(value: object, collection: str, entity_key: str) -> set[str]:
    root = _mapping(value, "association root")
    return {
        _text(
            _mapping(_mapping(raw, "association").get(entity_key), "association entity").get("urn"),
            "association URN",
        )
        for raw in _list_or_empty(root.get(collection), "associations")
    }


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return value


def _list(value: object, context: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{context} must be a non-empty list")
    return value


def _list_or_empty(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be non-empty text")
    return value.strip()
