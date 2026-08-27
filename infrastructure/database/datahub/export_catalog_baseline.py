"""기술형 Dataset·Field Glossary 정리 전 상태를 읽기 전용으로 봉인한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.datahub_catalog import DataHubCatalogClient  # noqa: E402
from src.data.governance_contract import canonical_json, canonical_sha256  # noqa: E402


BASELINE_SCHEMA_VERSION = "answervice.datahub-technical-glossary-baseline.v1"
BASELINE_SCOPE = "GENERATED_DATASET_FIELD_GLOSSARY"
_TECHNICAL_TERM_URN = re.compile(
    r"^urn:li:glossaryTerm:answervice_.+_(dataset|field)_[0-9a-f]{24}$"
)
_CATALOG_RELEASE_PROPERTY = "answervice.catalog_release"
_READ_CONCURRENCY = 12


async def build_catalog_baseline(client: Any) -> dict[str, Any]:
    """기술형 Term과 영향받은 Dataset 연결을 canonical snapshot으로 만든다."""

    term_hits = await client.list_glossary_terms()
    term_urns = tuple(sorted(hit.urn for hit in term_hits))
    term_values = await _bounded_read(term_urns, client.get_glossary_term)
    technical_values: list[tuple[str, Mapping[str, Any]]] = []
    for expected_urn, raw in zip(term_urns, term_values, strict=True):
        value = _mapping(raw, "glossary term")
        if value.get("urn") != expected_urn:
            raise ValueError("DataHub glossary term identity changed during baseline read")
        kind = _technical_term_kind(value)
        if kind is not None:
            technical_values.append((kind, value))

    technical_values.sort(key=lambda item: _text(item[1].get("urn"), "term URN"))
    status_values = await _bounded_read(
        tuple(_text(value.get("urn"), "term URN") for _, value in technical_values),
        client.get_entity_status,
    )
    terms = [
        _term_snapshot(kind, value, status)
        for (kind, value), status in zip(
            technical_values, status_values, strict=True
        )
    ]
    technical_urns = {term["urn"] for term in terms}

    dataset_hits = await client.list_datasets()
    dataset_urns = tuple(sorted(hit.urn for hit in dataset_hits))
    dataset_values = await _bounded_read(dataset_urns, client.get_dataset)
    affected_datasets: list[dict[str, Any]] = []
    for expected_urn, raw in zip(dataset_urns, dataset_values, strict=True):
        value = _mapping(raw, "dataset")
        if value.get("urn") != expected_urn:
            raise ValueError("DataHub dataset identity changed during baseline read")
        snapshot = _dataset_snapshot(value)
        if _dataset_term_urns(snapshot) & technical_urns:
            affected_datasets.append(snapshot)

    payload = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "scope": BASELINE_SCOPE,
        "inventory": {
            "scanned_datasets": len(dataset_urns),
            "scanned_glossary_terms": len(term_urns),
            "affected_datasets": len(affected_datasets),
            "technical_terms": len(terms),
        },
        "terms": terms,
        "datasets": affected_datasets,
    }
    document = {**payload, "content_sha256": canonical_sha256(payload)}
    validate_catalog_baseline(document)
    return document


def validate_catalog_baseline(document: Mapping[str, Any]) -> None:
    """checksum·정렬·참조 범위가 복구 입력으로 사용할 수 있는지 검증한다."""

    if document.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise ValueError("catalog baseline schema version is invalid")
    if document.get("scope") != BASELINE_SCOPE:
        raise ValueError("catalog baseline scope is invalid")
    checksum = document.get("content_sha256")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("catalog baseline checksum is invalid")
    payload = dict(document)
    payload.pop("content_sha256", None)
    if canonical_sha256(payload) != checksum:
        raise ValueError("catalog baseline checksum does not match its content")

    terms = _list(document.get("terms"), "baseline terms")
    datasets = _list_or_empty(document.get("datasets"), "baseline datasets")
    term_urns = [_text(_mapping(item, "baseline term").get("urn"), "term URN") for item in terms]
    dataset_urns = [
        _text(_mapping(item, "baseline dataset").get("urn"), "dataset URN")
        for item in datasets
    ]
    if term_urns != sorted(set(term_urns)):
        raise ValueError("catalog baseline term identities are not canonical")
    if dataset_urns != sorted(set(dataset_urns)):
        raise ValueError("catalog baseline dataset identities are not canonical")
    technical_urns = set(term_urns)
    for term in terms:
        value = _mapping(term, "baseline term")
        match = _TECHNICAL_TERM_URN.fullmatch(_text(value.get("urn"), "term URN"))
        if match is None or value.get("kind") != match.group(1):
            raise ValueError("catalog baseline contains a non-technical term")
    for dataset in datasets:
        if not _dataset_term_urns(_mapping(dataset, "baseline dataset")) & technical_urns:
            raise ValueError("catalog baseline contains an unaffected dataset")

    inventory = _mapping(document.get("inventory"), "baseline inventory")
    if inventory.get("technical_terms") != len(terms) or inventory.get(
        "affected_datasets"
    ) != len(datasets):
        raise ValueError("catalog baseline inventory does not match its content")


def write_catalog_baseline(document: Mapping[str, Any], output: Path) -> dict[str, Any]:
    """기존 파일을 덮어쓰지 않고 canonical baseline 한 건을 생성한다."""

    validate_catalog_baseline(document)
    if not output.is_absolute():
        raise ValueError("catalog baseline output path must be absolute")
    parent = output.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("catalog baseline output directory is unavailable")
    target = parent / output.name
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(document))
        stream.write("\n")
    inventory = _mapping(document.get("inventory"), "baseline inventory")
    return {
        "schema_version": "answervice.datahub-baseline-export-receipt.v1",
        "status": "EXPORTED_WITHOUT_MUTATION",
        "content_sha256": document["content_sha256"],
        "technical_terms": inventory["technical_terms"],
        "affected_datasets": inventory["affected_datasets"],
        "output": str(target),
    }


async def _bounded_read(
    identities: Sequence[str],
    reader: Callable[[str], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], ...]:
    semaphore = asyncio.Semaphore(_READ_CONCURRENCY)

    async def read(identity: str) -> dict[str, Any]:
        async with semaphore:
            return await reader(identity)

    return tuple(await asyncio.gather(*(read(identity) for identity in identities)))


def _technical_term_kind(value: Mapping[str, Any]) -> str | None:
    urn = _text(value.get("urn"), "term URN")
    match = _TECHNICAL_TERM_URN.fullmatch(urn)
    if match is None:
        return None
    info = _mapping(value.get("glossaryTermInfo"), "technical term info")
    properties = _custom_properties(info.get("customProperties"))
    release = properties.get(_CATALOG_RELEASE_PROPERTY)
    if (
        not isinstance(release, str)
        or not release
        or info.get("sourceRef") != release
        or info.get("termSource") != "INTERNAL"
    ):
        raise ValueError("technical-shaped term is missing publication provenance")
    return match.group(1)


def _term_snapshot(
    kind: str,
    value: Mapping[str, Any],
    status_document: Mapping[str, Any],
) -> dict[str, Any]:
    urn = _text(value.get("urn"), "term URN")
    if status_document.get("urn") != urn:
        raise ValueError("DataHub term status identity changed during baseline read")
    status = _mapping(status_document.get("status"), "term status")
    if not isinstance(status.get("removed"), bool):
        raise ValueError("DataHub term status is incomplete")
    info = _mapping(value.get("glossaryTermInfo"), "term info")
    ownership = _mapping(value.get("ownership"), "term ownership")
    owners = []
    for raw in _list(ownership.get("owners"), "term owners"):
        owner = _mapping(raw, "term owner")
        owners.append(
            {
                "owner_urn": _text(
                    _mapping(owner.get("owner"), "term owner entity").get("urn"),
                    "term owner URN",
                ),
                "associated_urn": _text(
                    owner.get("associatedUrn"), "term associated URN"
                ),
                "ownership_type_urn": _text(
                    _mapping(owner.get("ownershipType"), "ownership type").get(
                        "urn"
                    ),
                    "ownership type URN",
                ),
                "type": _text(owner.get("type"), "ownership type"),
            }
        )
    owners.sort(key=canonical_json)
    domain = _mapping(
        _mapping(value.get("domain"), "term domain").get("domain"),
        "term domain entity",
    )
    return {
        "urn": urn,
        "kind": kind,
        "removed": status["removed"],
        "name": _text(info.get("name"), "term name"),
        "description": _text(info.get("description"), "term description"),
        "term_source": _text(info.get("termSource"), "term source"),
        "source_ref": _text(info.get("sourceRef"), "term source reference"),
        "custom_properties": _custom_properties(info.get("customProperties")),
        "owners": owners,
        "domain_urn": _text(domain.get("urn"), "term domain URN"),
    }


def _dataset_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    schema = value.get("schemaMetadata")
    schema_fields = []
    if schema is not None:
        schema_fields = _field_snapshots(
            _mapping(schema, "dataset schema").get("fields"), "schema fields"
        )
    editable = value.get("editableSchemaMetadata")
    editable_fields = []
    if editable is not None:
        editable_fields = _field_snapshots(
            _mapping(editable, "editable schema").get("editableSchemaFieldInfo"),
            "editable schema fields",
        )
    return {
        "urn": _text(value.get("urn"), "dataset URN"),
        "dataset_term_urns": list(_term_urns(value.get("glossaryTerms"))),
        "schema_fields": schema_fields,
        "editable_fields": editable_fields,
    }


def _field_snapshots(value: object, context: str) -> list[dict[str, Any]]:
    result = []
    for raw in _list_or_empty(value, context):
        field = _mapping(raw, "schema field")
        description = field.get("description")
        if description is not None and not isinstance(description, str):
            raise ValueError("schema field description is invalid")
        result.append(
            {
                "field_path": _text(field.get("fieldPath"), "field path"),
                "description": description,
                "term_urns": list(_term_urns(field.get("glossaryTerms"))),
            }
        )
    result.sort(key=lambda item: item["field_path"])
    if len({item["field_path"] for item in result}) != len(result):
        raise ValueError("schema field paths are duplicate")
    return result


def _dataset_term_urns(value: Mapping[str, Any]) -> set[str]:
    result = set(_text(item, "dataset term URN") for item in value.get("dataset_term_urns", []))
    for collection in ("schema_fields", "editable_fields"):
        for raw in value.get(collection, []):
            field = _mapping(raw, "baseline field")
            result.update(
                _text(item, "field term URN") for item in field.get("term_urns", [])
            )
    return result


def _term_urns(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    root = _mapping(value, "glossary associations")
    urns = []
    for raw in _list_or_empty(root.get("terms"), "glossary associations"):
        term = _mapping(_mapping(raw, "glossary association").get("term"), "term")
        urns.append(_text(term.get("urn"), "associated term URN"))
    if len(urns) != len(set(urns)):
        raise ValueError("glossary associations contain duplicate terms")
    return tuple(sorted(urns))


def _custom_properties(value: object) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in _list_or_empty(value, "custom properties"):
        item = _mapping(raw, "custom property")
        key = _text(item.get("key"), "custom property key")
        if key in result:
            raise ValueError("custom properties contain a duplicate key")
        result[key] = _text(item.get("value"), "custom property value")
    return {key: result[key] for key in sorted(result)}


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return value


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
    return parser.parse_args(argv)


async def _async_main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    async with DataHubCatalogClient.from_env(
        timeout_seconds=30,
        page_size=100,
        max_entities=10_000,
    ) as client:
        document = await build_catalog_baseline(client)
    print(canonical_json(write_catalog_baseline(document, arguments.output)))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """민감정보 없이 export receipt만 출력하고 예상 실패는 유형만 반환한다."""

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
