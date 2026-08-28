"""P0 DataHub metadata 전체를 mutation 없이 canonical baseline으로 봉인한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.datahub_catalog import DataHubCatalogClient  # noqa: E402
from http_client import DataHubMetadataAdminClient  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import canonical_json, canonical_sha256  # noqa: E402


BASELINE_SCHEMA_VERSION = "answervice.datahub-metadata-baseline.v1"
BASELINE_SCOPE = "P0_CANONICAL_METADATA_RECOVERY"
EXPORT_RECEIPT_VERSION = "answervice.datahub-metadata-baseline-export.v1"
VERIFY_RECEIPT_VERSION = "answervice.datahub-metadata-baseline-verify.v1"
_READ_CONCURRENCY = 12
_MAX_ENTITY_COUNT = 100_000
_AUDIT_KEYS = frozenset(
    {"auditStamp", "created", "lastModified", "lifecycleLastUpdated"}
)

_PRIMARY_ASPECTS: dict[str, tuple[str, ...]] = {
    "dataset": (
        "datasetKey",
        "datasetProperties",
        "schemaMetadata",
        "editableSchemaMetadata",
        "status",
        "ownership",
        "domains",
        "globalTags",
        "glossaryTerms",
        "upstreamLineage",
        "subTypes",
        "structuredProperties",
    ),
    "glossaryTerm": (
        "glossaryTermKey",
        "glossaryTermInfo",
        "status",
        "ownership",
        "domains",
        "globalTags",
        "structuredProperties",
    ),
    "metric": (
        "metricKey",
        "metricInfo",
        "aiContext",
        "status",
        "ownership",
        "domains",
        "globalTags",
        "glossaryTerms",
        "metricRelationships",
        "metricUpstreams",
        "structuredProperties",
    ),
}
_REFERENCE_ASPECTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "domain": (
        "urn:li:domain:",
        ("domainKey", "domainProperties", "status"),
    ),
    "corpGroup": (
        "urn:li:corpGroup:",
        ("corpGroupKey", "corpGroupInfo", "corpGroupEditableInfo", "status"),
    ),
    "corpUser": (
        "urn:li:corpuser:",
        ("corpUserKey", "corpUserInfo", "corpUserEditableInfo", "status"),
    ),
    "tag": (
        "urn:li:tag:",
        ("tagKey", "tagProperties", "status"),
    ),
    "lifecycleStageType": (
        "urn:li:lifecycleStageType:",
        ("lifecycleStageTypeKey", "lifecycleStageTypeInfo", "status"),
    ),
}
_KEY_ASPECTS = {
    "dataset": "datasetKey",
    "glossaryTerm": "glossaryTermKey",
    "metric": "metricKey",
    "domain": "domainKey",
    "corpGroup": "corpGroupKey",
    "corpUser": "corpUserKey",
    "tag": "tagKey",
    "lifecycleStageType": "lifecycleStageTypeKey",
}
_PRIMARY_PREFIXES = {
    "dataset": "urn:li:dataset:",
    "glossaryTerm": "urn:li:glossaryTerm:",
    "metric": "urn:li:metric:",
}


async def build_datahub_metadata_baseline(
    catalog: Any,
    reader: Any,
    *,
    actor_urn: str,
    read_at: datetime,
) -> dict[str, Any]:
    """Dataset·Column·Term·거버넌스·Metric·Lineage를 읽어 exact set으로 봉인한다."""

    if not actor_urn.startswith("urn:li:corpuser:service_"):
        raise ValueError("baseline actor must be a DataHub read service account")
    if read_at.tzinfo is None or read_at.utcoffset() is None:
        raise ValueError("baseline read time must be timezone-aware")

    dataset_hits, term_hits, metric_hits = await asyncio.gather(
        catalog.list_datasets(),
        catalog.list_glossary_terms(),
        catalog.list_metrics(),
    )
    identities: dict[str, set[str]] = {
        "dataset": {_text(hit.urn, "dataset URN") for hit in dataset_hits},
        "glossaryTerm": {
            _text(hit.urn, "Glossary Term URN") for hit in term_hits
        },
        "metric": {_text(hit.urn, "Metric URN") for hit in metric_hits},
    }
    if not identities["dataset"]:
        raise ValueError("DataHub baseline dataset membership is empty")
    if sum(len(values) for values in identities.values()) > _MAX_ENTITY_COUNT:
        raise ValueError("DataHub baseline entity bound was exceeded")

    snapshots: dict[str, dict[str, Any]] = {}
    audit_records: list[dict[str, Any]] = []
    while True:
        pending = [
            (entity_type, urn, _PRIMARY_ASPECTS[entity_type])
            for entity_type in sorted(identities)
            for urn in sorted(identities[entity_type])
            if urn not in snapshots
        ]
        if pending:
            rows = await _read_entities(reader, pending)
            for snapshot, receipts in rows:
                snapshots[snapshot["urn"]] = snapshot
                audit_records.extend(receipts)

        references = _referenced_urns(snapshots.values())
        changed = False
        for entity_type, prefix in _PRIMARY_PREFIXES.items():
            discovered = {urn for urn in references if urn.startswith(prefix)}
            additions = discovered - identities[entity_type]
            if additions:
                identities[entity_type].update(additions)
                changed = True
        if not changed:
            break
        if sum(len(values) for values in identities.values()) > _MAX_ENTITY_COUNT:
            raise ValueError("DataHub baseline reference closure exceeded its bound")

    references = _referenced_urns(snapshots.values())
    reference_requests = [
        (entity_type, urn, aspects)
        for entity_type, (prefix, aspects) in sorted(_REFERENCE_ASPECTS.items())
        for urn in sorted(item for item in references if item.startswith(prefix))
        if urn not in snapshots
    ]
    for snapshot, receipts in await _read_entities(reader, reference_requests):
        snapshots[snapshot["urn"]] = snapshot
        audit_records.extend(receipts)

    entities = sorted(
        snapshots.values(), key=lambda item: (item["entity_type"], item["urn"])
    )
    exact_sets = _derive_exact_sets(entities)
    inventory = _inventory(entities, exact_sets)
    exact_set_sha256 = {
        name: canonical_sha256(values) for name, values in exact_sets.items()
    }
    content = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "scope": BASELINE_SCOPE,
        "inventory": inventory,
        "entities": entities,
        "exact_sets": exact_sets,
        "exact_set_sha256": exact_set_sha256,
    }
    content_sha256 = canonical_sha256(content)
    deployment_receipt = {
        "schema_version": "answervice.datahub-metadata-read-receipt.v1",
        "content_sha256": content_sha256,
        "actor_urn": actor_urn,
        "read_at": read_at.astimezone(timezone.utc).isoformat(),
        "source_audit_sha256": canonical_sha256(
            sorted(audit_records, key=canonical_json)
        ),
        "mutation_count": 0,
    }
    document = {
        **content,
        "content_sha256": content_sha256,
        "deployment_receipt": deployment_receipt,
        "deployment_receipt_sha256": canonical_sha256(deployment_receipt),
    }
    validate_datahub_metadata_baseline(document)
    return document


def validate_datahub_metadata_baseline(document: Mapping[str, Any]) -> None:
    """Baseline checksum, exact membership, 참조 완결성과 audit 분리를 다시 검증한다."""

    expected_keys = {
        "schema_version",
        "scope",
        "inventory",
        "entities",
        "exact_sets",
        "exact_set_sha256",
        "content_sha256",
        "deployment_receipt",
        "deployment_receipt_sha256",
    }
    if set(document) != expected_keys:
        raise ValueError("DataHub metadata baseline fields differ")
    if (
        document.get("schema_version") != BASELINE_SCHEMA_VERSION
        or document.get("scope") != BASELINE_SCOPE
    ):
        raise ValueError("DataHub metadata baseline identity differs")

    entities = _list(document.get("entities"), "baseline entities")
    identities = [
        (
            _text(_mapping(item, "baseline entity").get("entity_type"), "entity type"),
            _text(_mapping(item, "baseline entity").get("urn"), "entity URN"),
        )
        for item in entities
    ]
    if identities != sorted(set(identities)):
        raise ValueError("DataHub metadata baseline entities are not canonical")
    if _contains_audit_key(entities):
        raise ValueError("DataHub metadata content contains deployment audit fields")
    for raw in entities:
        entity = _mapping(raw, "baseline entity")
        aspects = _mapping(entity.get("aspects"), "baseline aspects")
        key_aspect = _KEY_ASPECTS.get(str(entity.get("entity_type")))
        if key_aspect is None or key_aspect not in aspects:
            raise ValueError("DataHub metadata baseline key aspect is missing")

    exact_sets = _derive_exact_sets(entities)
    if document.get("exact_sets") != exact_sets:
        raise ValueError("DataHub metadata baseline exact sets differ")
    exact_hashes = {
        name: canonical_sha256(values) for name, values in exact_sets.items()
    }
    if document.get("exact_set_sha256") != exact_hashes:
        raise ValueError("DataHub metadata baseline exact set checksums differ")
    if document.get("inventory") != _inventory(entities, exact_sets):
        raise ValueError("DataHub metadata baseline inventory differs")

    content = {
        name: document[name]
        for name in (
            "schema_version",
            "scope",
            "inventory",
            "entities",
            "exact_sets",
            "exact_set_sha256",
        )
    }
    if document.get("content_sha256") != canonical_sha256(content):
        raise ValueError("DataHub metadata baseline content checksum differs")
    receipt = _mapping(document.get("deployment_receipt"), "deployment receipt")
    if (
        receipt.get("content_sha256") != document.get("content_sha256")
        or receipt.get("mutation_count") != 0
        or document.get("deployment_receipt_sha256")
        != canonical_sha256(receipt)
    ):
        raise ValueError("DataHub metadata baseline deployment receipt checksum differs")
    _validate_reference_completeness(entities, exact_sets)


async def verify_datahub_metadata_baseline(
    document: Mapping[str, Any], catalog: Any, reader: Any
) -> dict[str, Any]:
    """저장 후보와 두 번째 live full read의 content·exact set을 독립 비교한다."""

    validate_datahub_metadata_baseline(document)
    receipt = _mapping(document["deployment_receipt"], "deployment receipt")
    read_at = datetime.fromisoformat(_text(receipt.get("read_at"), "read time"))
    live = await build_datahub_metadata_baseline(
        catalog,
        reader,
        actor_urn=_text(receipt.get("actor_urn"), "read actor"),
        read_at=read_at,
    )
    if (
        live["content_sha256"] != document["content_sha256"]
        or live["exact_set_sha256"] != document["exact_set_sha256"]
    ):
        raise ValueError("live DataHub content differs from the exported baseline")
    return {
        "schema_version": VERIFY_RECEIPT_VERSION,
        "status": "LIVE_EXACT_SET_VERIFIED_WITHOUT_MUTATION",
        "content_sha256": document["content_sha256"],
        "exact_set_sha256": document["exact_set_sha256"],
        "mutation_count": 0,
    }


def write_datahub_metadata_baseline(
    document: Mapping[str, Any], output: Path
) -> dict[str, Any]:
    """검증된 baseline을 기존 파일을 덮지 않는 새 절대경로에만 기록한다."""

    validate_datahub_metadata_baseline(document)
    if not output.is_absolute():
        raise ValueError("DataHub metadata baseline output path must be absolute")
    parent = output.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("DataHub metadata baseline output directory is unavailable")
    target = parent / output.name
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(document))
        stream.write("\n")
    return {
        "schema_version": EXPORT_RECEIPT_VERSION,
        "status": "EXPORTED_WITHOUT_MUTATION",
        "content_sha256": document["content_sha256"],
        "exact_set_sha256": document["exact_set_sha256"],
        "output": str(target),
        "mutation_count": 0,
    }


async def _read_entities(
    reader: Any,
    requests: Sequence[tuple[str, str, tuple[str, ...]]],
) -> tuple[tuple[dict[str, Any], list[dict[str, Any]]], ...]:
    semaphore = asyncio.Semaphore(_READ_CONCURRENCY)

    async def read(
        entity_type: str, urn: str, aspects: tuple[str, ...]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        async with semaphore:
            raw = await reader.get_entity(urn, aspects)
        return _snapshot_entity(entity_type, urn, aspects, raw)

    return tuple(
        await asyncio.gather(
            *(read(entity_type, urn, aspects) for entity_type, urn, aspects in requests)
        )
    )


def _snapshot_entity(
    entity_type: str,
    expected_urn: str,
    requested_aspects: tuple[str, ...],
    raw: object,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    entity = _mapping(raw, "DataHub entity")
    if entity.get("urn") != expected_urn:
        raise ValueError("DataHub entity identity changed during baseline read")
    wrappers = _mapping(entity.get("aspects"), "DataHub entity aspects")
    aspects: dict[str, Any] = {}
    audit_records: list[dict[str, Any]] = []
    for name in requested_aspects:
        if name not in wrappers:
            continue
        wrapper = _mapping(wrappers[name], f"{expected_urn}.{name}")
        value = _mapping(wrapper.get("value"), f"{expected_urn}.{name}.value")
        semantic, receipts = _strip_audit(value, path="$")
        aspects[name] = semantic
        audit_records.extend(
            {
                "urn": expected_urn,
                "aspect": name,
                **receipt,
            }
            for receipt in receipts
        )
    key_aspect = _KEY_ASPECTS[entity_type]
    if key_aspect not in aspects:
        raise ValueError(f"DataHub referenced entity is missing {key_aspect}: {expected_urn}")
    return {
        "entity_type": entity_type,
        "urn": expected_urn,
        "aspects": {name: aspects[name] for name in sorted(aspects)},
    }, audit_records


def _strip_audit(value: object, *, path: str) -> tuple[object, list[dict[str, Any]]]:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        receipts: list[dict[str, Any]] = []
        for key in sorted(value):
            name = _text(key, "aspect field")
            child_path = f"{path}.{name}"
            if name in _AUDIT_KEYS and _is_audit_stamp(value[key]):
                receipts.append({"path": child_path, "value": value[key]})
                continue
            child, child_receipts = _strip_audit(value[key], path=child_path)
            result[name] = child
            receipts.extend(child_receipts)
        return result, receipts
    if isinstance(value, list):
        result = []
        receipts = []
        for index, item in enumerate(value):
            child, child_receipts = _strip_audit(item, path=f"{path}[{index}]")
            result.append(child)
            receipts.extend(child_receipts)
        return result, receipts
    if value is None or isinstance(value, (str, int, float, bool)):
        return value, []
    raise ValueError("DataHub aspect contains a non-JSON value")


def _referenced_urns(entities: Sequence[Mapping[str, Any]]) -> set[str]:
    return {
        value
        for entity in entities
        for value in _walk_strings(entity.get("aspects"))
        if value.startswith("urn:li:")
    }


def _walk_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _derive_exact_sets(entities: Sequence[Mapping[str, Any]]) -> dict[str, list[Any]]:
    by_type: dict[str, list[Mapping[str, Any]]] = {}
    for raw in entities:
        entity = _mapping(raw, "baseline entity")
        by_type.setdefault(str(entity.get("entity_type")), []).append(entity)

    dataset_urns = sorted(_text(item.get("urn"), "dataset URN") for item in by_type.get("dataset", []))
    glossary_urns = sorted(_text(item.get("urn"), "term URN") for item in by_type.get("glossaryTerm", []))
    metric_urns = sorted(_text(item.get("urn"), "metric URN") for item in by_type.get("metric", []))
    columns: set[tuple[str, str, str, bool]] = set()
    dataset_terms: set[tuple[str, str]] = set()
    field_terms: set[tuple[str, str, str]] = set()
    lineage: set[tuple[str, str]] = set()
    dataset_domains: set[tuple[str, str]] = set()
    dataset_owners: set[tuple[str, str]] = set()
    dataset_tags: set[tuple[str, str]] = set()
    dataset_lifecycles: set[tuple[str, str]] = set()

    for entity in by_type.get("dataset", []):
        urn = _text(entity.get("urn"), "dataset URN")
        aspects = _mapping(entity.get("aspects"), "dataset aspects")
        schema = _optional_mapping(aspects.get("schemaMetadata"), "schemaMetadata")
        for raw_field in _list_or_empty(schema.get("fields"), "schema fields"):
            field = _mapping(raw_field, "schema field")
            path = _text(field.get("fieldPath"), "schema field path")
            native_type = _text(field.get("nativeDataType"), "schema native type")
            nullable = field.get("nullable")
            if not isinstance(nullable, bool):
                raise ValueError("schema nullable must be boolean")
            columns.add((urn, path, native_type, nullable))
            for term_urn in _association_urns(field.get("glossaryTerms"), "terms"):
                field_terms.add((urn, path, term_urn))
        editable = _optional_mapping(
            aspects.get("editableSchemaMetadata"), "editableSchemaMetadata"
        )
        for raw_field in _list_or_empty(
            editable.get("editableSchemaFieldInfo"), "editable schema fields"
        ):
            field = _mapping(raw_field, "editable schema field")
            path = _text(field.get("fieldPath"), "editable field path")
            for term_urn in _association_urns(field.get("glossaryTerms"), "terms"):
                field_terms.add((urn, path, term_urn))
        dataset_terms.update(
            (urn, term_urn)
            for term_urn in _association_urns(aspects.get("glossaryTerms"), "terms")
        )
        upstream = _optional_mapping(aspects.get("upstreamLineage"), "upstream lineage")
        for edge in _list_or_empty(upstream.get("upstreams"), "upstream datasets"):
            upstream_urn = _urn_from(_mapping(edge, "upstream edge").get("dataset"), "upstream dataset")
            lineage.add((upstream_urn, urn))
        dataset_domains.update((urn, item) for item in _domain_urns(aspects.get("domains")))
        dataset_owners.update((urn, item) for item in _owner_urns(aspects.get("ownership")))
        dataset_tags.update((urn, item) for item in _tag_urns(aspects.get("globalTags")))
        status = _optional_mapping(aspects.get("status"), "dataset status")
        if status.get("lifecycleStage") is not None:
            dataset_lifecycles.add((urn, _urn_from(status["lifecycleStage"], "dataset lifecycle")))

    metric_inputs: set[tuple[str, str, str | None]] = set()
    metric_terms: set[tuple[str, str]] = set()
    metric_relationships: set[tuple[str, str, str]] = set()
    for entity in by_type.get("metric", []):
        urn = _text(entity.get("urn"), "metric URN")
        aspects = _mapping(entity.get("aspects"), "metric aspects")
        metric_terms.update(
            (urn, term_urn)
            for term_urn in _association_urns(aspects.get("glossaryTerms"), "terms")
        )
        upstreams = _optional_mapping(aspects.get("metricUpstreams"), "metric upstreams")
        for edge in _list_or_empty(upstreams.get("datasetUpstreams"), "metric dataset upstreams"):
            destination = _urn_from(_mapping(edge, "metric dataset edge").get("destinationUrn"), "metric dataset")
            metric_inputs.add((urn, destination, None))
        for edge in _list_or_empty(upstreams.get("fieldUpstreams"), "metric field upstreams"):
            destination = _urn_from(_mapping(edge, "metric field edge").get("destinationUrn"), "metric field")
            dataset_urn, field_path = _parse_schema_field_urn(destination)
            metric_inputs.add((urn, dataset_urn, field_path))
        relationships = _optional_mapping(aspects.get("metricRelationships"), "metric relationships")
        for kind in ("derivedFrom", "relatedMetrics"):
            for edge in _list_or_empty(relationships.get(kind), f"metric {kind}"):
                destination = _urn_from(_mapping(edge, "metric relationship").get("destinationUrn"), "related metric")
                metric_relationships.add((urn, kind, destination))

    return {
        "dataset_urns": dataset_urns,
        "columns": _canonical_rows(columns),
        "glossary_term_urns": glossary_urns,
        "metric_urns": metric_urns,
        "dataset_term_edges": _canonical_rows(dataset_terms),
        "field_term_edges": _canonical_rows(field_terms),
        "dataset_domain_edges": _canonical_rows(dataset_domains),
        "dataset_owner_edges": _canonical_rows(dataset_owners),
        "dataset_tag_edges": _canonical_rows(dataset_tags),
        "dataset_lifecycle_edges": _canonical_rows(dataset_lifecycles),
        "dataset_lineage_edges": _canonical_rows(lineage),
        "metric_term_edges": _canonical_rows(metric_terms),
        "metric_input_edges": _canonical_rows(metric_inputs),
        "metric_relationship_edges": _canonical_rows(metric_relationships),
    }


def _inventory(
    entities: Sequence[Mapping[str, Any]], exact_sets: Mapping[str, list[Any]]
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw in entities:
        entity_type = str(_mapping(raw, "baseline entity").get("entity_type"))
        counts[entity_type] = counts.get(entity_type, 0) + 1
    return {
        "datasets": counts.get("dataset", 0),
        "columns": len(exact_sets["columns"]),
        "glossary_terms": counts.get("glossaryTerm", 0),
        "metrics": counts.get("metric", 0),
        "domains": counts.get("domain", 0),
        "owners": counts.get("corpGroup", 0) + counts.get("corpUser", 0),
        "tags": counts.get("tag", 0),
        "lifecycle_stages": counts.get("lifecycleStageType", 0),
        "dataset_lineage_edges": len(exact_sets["dataset_lineage_edges"]),
        "metric_input_edges": len(exact_sets["metric_input_edges"]),
    }


def _validate_reference_completeness(
    entities: Sequence[Mapping[str, Any]], exact_sets: Mapping[str, list[Any]]
) -> None:
    identities = {_text(item.get("urn"), "entity URN") for item in entities}
    references = _referenced_urns(entities)
    governed_prefixes = tuple(
        [*_PRIMARY_PREFIXES.values()]
        + [prefix for prefix, _aspects in _REFERENCE_ASPECTS.values()]
    )
    missing = sorted(
        urn for urn in references if urn.startswith(governed_prefixes) and urn not in identities
    )
    if missing:
        raise ValueError("DataHub metadata baseline has unresolved entity references")
    dataset_urns = set(exact_sets["dataset_urns"])
    glossary_urns = set(exact_sets["glossary_term_urns"])
    metric_urns = set(exact_sets["metric_urns"])
    if any(row[0] not in dataset_urns or row[1] not in dataset_urns for row in exact_sets["dataset_lineage_edges"]):
        raise ValueError("DataHub metadata baseline lineage references an unknown dataset")
    if any(row[0] not in metric_urns or row[1] not in dataset_urns for row in exact_sets["metric_input_edges"]):
        raise ValueError("DataHub metadata baseline Metric input is unresolved")
    if any(row[-1] not in glossary_urns for name in ("dataset_term_edges", "field_term_edges", "metric_term_edges") for row in exact_sets[name]):
        raise ValueError("DataHub metadata baseline Term association is unresolved")


def _association_urns(value: object, collection: str) -> tuple[str, ...]:
    root = _optional_mapping(value, "association")
    result = []
    for raw in _list_or_empty(root.get(collection), "associations"):
        item = _mapping(raw, "association item")
        result.append(_urn_from(item.get("urn", item.get("term")), "association URN"))
    if len(result) != len(set(result)):
        raise ValueError("DataHub association contains duplicate URNs")
    return tuple(sorted(result))


def _domain_urns(value: object) -> tuple[str, ...]:
    root = _optional_mapping(value, "domains")
    raw = root.get("domains")
    if raw is None:
        raw = [item.get("domain") for item in _list_or_empty(root.get("domainAssociations"), "domain associations") if isinstance(item, Mapping)]
    return _unique_urns(raw, "domains")


def _owner_urns(value: object) -> tuple[str, ...]:
    root = _optional_mapping(value, "ownership")
    return _unique_urns(
        [_mapping(item, "owner").get("owner") for item in _list_or_empty(root.get("owners"), "owners")],
        "owners",
    )


def _tag_urns(value: object) -> tuple[str, ...]:
    root = _optional_mapping(value, "global tags")
    return _unique_urns(
        [_mapping(item, "tag").get("tag") for item in _list_or_empty(root.get("tags"), "tags")],
        "tags",
    )


def _unique_urns(value: object, context: str) -> tuple[str, ...]:
    urns = tuple(_urn_from(item, context) for item in _list_or_empty(value, context))
    if len(urns) != len(set(urns)):
        raise ValueError(f"DataHub {context} contain duplicate URNs")
    return tuple(sorted(urns))


def _urn_from(value: object, context: str) -> str:
    if isinstance(value, Mapping):
        value = value.get("urn")
    urn = _text(value, context)
    if not urn.startswith("urn:li:"):
        raise ValueError(f"{context} must be a DataHub URN")
    return urn


def _parse_schema_field_urn(urn: str) -> tuple[str, str]:
    prefix = "urn:li:schemaField:("
    if not urn.startswith(prefix) or not urn.endswith(")"):
        raise ValueError("Metric field upstream is not a schemaField URN")
    body = urn[len(prefix) : -1]
    try:
        dataset_urn, encoded_field = body.rsplit(",", 1)
    except ValueError as error:
        raise ValueError("Metric field upstream is malformed") from error
    field = unquote(encoded_field)
    if not dataset_urn.startswith("urn:li:dataset:(") or not field:
        raise ValueError("Metric field upstream is malformed")
    return dataset_urn, field


def _canonical_rows(values: set[tuple[Any, ...]]) -> list[list[Any]]:
    rows = [list(value) for value in values]
    return sorted(rows, key=canonical_json)


def _contains_audit_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            (key in _AUDIT_KEYS and _is_audit_stamp(item))
            or _contains_audit_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_audit_key(item) for item in value)
    return False


def _is_audit_stamp(value: object) -> bool:
    """동명 custom property가 아니라 DataHub AuditStamp 객체일 때만 분리한다."""

    return (
        isinstance(value, Mapping)
        and isinstance(value.get("actor"), str)
        and value.get("actor", "").startswith("urn:li:")
        and isinstance(value.get("time"), (int, float))
        and not isinstance(value.get("time"), bool)
    )


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return value


def _optional_mapping(value: object, context: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    return _mapping(value, context)


def _list(value: object, context: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{context} must be a non-empty list")
    return value


def _list_or_empty(value: object, context: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be non-empty text")
    return value.strip()


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args(argv)


async def _async_main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    settings = DataHubConnectionSettings.from_env()
    async with DataHubCatalogClient(
        settings.base_url,
        settings.token,
        ca_file=settings.ca_file,
        expected_actor_urn=settings.actor_urn,
        timeout_seconds=arguments.timeout,
        page_size=100,
        max_entities=_MAX_ENTITY_COUNT,
    ) as catalog, DataHubMetadataAdminClient(
        settings.base_url,
        token=settings.token,
        ca_file=settings.ca_file,
        timeout_seconds=arguments.timeout,
    ) as reader:
        if not await catalog.health():
            raise RuntimeError("DataHub read service identity is unavailable")
        document = await build_datahub_metadata_baseline(
            catalog,
            reader,
            actor_urn=settings.actor_urn,
            read_at=datetime.now(timezone.utc),
        )
        verification = await verify_datahub_metadata_baseline(
            document, catalog, reader
        )
    export = write_datahub_metadata_baseline(document, arguments.output)
    print(canonical_json({"export": export, "verification": verification}))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """민감정보 없이 read-only export·검증 receipt만 출력한다."""

    try:
        return asyncio.run(_async_main(argv))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"status": "ERROR", "error_type": type(error).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
