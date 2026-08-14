"""Publish the versioned serving Semantic Catalog to a local DataHub GMS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG = ROOT / "src/data/serving_semantic_catalog.i4.v1.json"
DEFAULT_GLOSSARY = ROOT / "src/ai/contracts/metric_glossary.i5.v1.json"
LOCAL_GMS_HOSTS = {"localhost", "127.0.0.1", "::1", "datahub-gms", "datahub-gms-quickstart"}


def canonical_catalog_hash(catalog: dict[str, Any]) -> str:
    payload = {key: value for key, value in catalog.items() if key != "catalog_sha256"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_glossary_hash(glossary: dict[str, Any]) -> str:
    canonical = json.dumps(
        glossary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_metric_glossary(path: Path = DEFAULT_GLOSSARY) -> dict[str, Any]:
    glossary = json.loads(path.read_text(encoding="utf-8"))
    metrics = glossary.get("metrics")
    definitions = glossary.get("definitions")
    units = glossary.get("units")
    if (
        not isinstance(glossary.get("version"), str)
        or not isinstance(metrics, dict)
        or not metrics
        or set(metrics) != set(definitions or {})
        or set(metrics) != set(units or {})
        or any(
            not isinstance(metric_id, str)
            or not metric_id
            or not isinstance(aliases, list)
            or not aliases
            or any(not isinstance(alias, str) or not alias.strip() for alias in aliases)
            or not isinstance(definitions[metric_id], str)
            or not definitions[metric_id].strip()
            or not isinstance(units[metric_id], str)
            or not units[metric_id].strip()
            for metric_id, aliases in metrics.items()
        )
    ):
        raise ValueError("Metric Glossary bootstrap contract is invalid")
    return glossary


def load_catalog(path: Path = DEFAULT_CATALOG) -> tuple[dict[str, Any], dict[str, Any]]:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    contract = json.loads((ROOT / catalog["source_contract"]).read_text(encoding="utf-8"))
    validate_catalog(catalog, contract)
    return catalog, contract


def validate_catalog(catalog: dict[str, Any], contract: dict[str, Any]) -> None:
    views = contract["views"]
    fqns = {view["fqn"] for view in views}
    fields = [name for view in views for name in view["columns"]]
    counts = catalog["counts"]
    expected = {
        "datasets": len(views),
        "field_occurrences": len(fields),
        "unique_fields": len(set(fields)),
    }
    if counts != expected:
        raise ValueError(f"catalog cardinality mismatch: expected {expected}, got {counts}")
    if set(catalog["dataset_descriptions"]) != fqns:
        raise ValueError("catalog dataset FQNs do not match the serving contract")
    if set(catalog["field_descriptions"]) != set(fields):
        raise ValueError("catalog fields do not match the serving contract")
    if catalog["source_views_sha256"] != contract["verification"]["trino_columns"]["canonical_sha256"]:
        raise ValueError("catalog source view hash does not match the serving contract")
    actual_hash = canonical_catalog_hash(catalog)
    if catalog["catalog_sha256"] != actual_hash:
        raise ValueError(f"catalog hash mismatch: expected {actual_hash}")


def catalog_marker(catalog: dict[str, Any]) -> str:
    return f"[Semantic Catalog: {catalog['catalog_version']} | sha256:{catalog['catalog_sha256']}]"


def iter_aspects(catalog: dict[str, Any], contract: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    marker = catalog_marker(catalog)
    for view in contract["views"]:
        fqn = view["fqn"]
        yield view["urn"], "editableDatasetProperties", {
            "description": f"{catalog['dataset_descriptions'][fqn]}\n\n{marker}"
        }
        yield view["urn"], "editableSchemaMetadata", {
            "editableSchemaFieldInfo": [
                {"fieldPath": field, "description": catalog["field_descriptions"][field]}
                for field in view["columns"]
            ]
        }


def iter_metric_glossary_aspects(
    glossary: dict[str, Any],
) -> Iterator[tuple[str, str, dict[str, Any]]]:
    alias_counts = Counter(
        alias for aliases in glossary["metrics"].values() for alias in aliases
    )
    glossary_hash = canonical_glossary_hash(glossary)
    for metric_id, aliases in glossary["metrics"].items():
        label = next((alias for alias in aliases if alias_counts[alias] == 1), None)
        if label is None:
            raise ValueError(f"Metric has no unique DataHub display name: {metric_id}")
        urn = f"urn:li:glossaryTerm:{metric_id}"
        yield urn, "glossaryTermKey", {"name": metric_id}
        yield urn, "glossaryTermInfo", {
            "id": metric_id,
            "name": label,
            "definition": glossary["definitions"][metric_id],
            "termSource": "INTERNAL",
            "sourceRef": glossary["version"],
            "customProperties": {
                "answervice.metric_id": metric_id,
                "answervice.aliases": json.dumps(
                    aliases, ensure_ascii=False, separators=(",", ":")
                ),
                "answervice.unit": glossary["units"][metric_id],
                "answervice.glossary_version": glossary["version"],
                "answervice.glossary_sha256": glossary_hash,
            },
        }


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-RestLi-Protocol-Version": "2.0.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def validate_local_server(server: str) -> None:
    parsed = urlparse(server)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOCAL_GMS_HOSTS:
        raise ValueError("Semantic Catalog publish/verify is restricted to local DataHub GMS")


def publish(
    server: str,
    catalog_path: Path = DEFAULT_CATALOG,
    glossary_path: Path = DEFAULT_GLOSSARY,
    token: str | None = None,
    timeout: float = 30,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    validate_local_server(server)
    catalog, contract = load_catalog(catalog_path)
    glossary = load_metric_glossary(glossary_path)
    aspect_count = 0
    aspect_groups = (
        ("dataset", iter_aspects(catalog, contract)),
        ("glossaryTerm", iter_metric_glossary_aspects(glossary)),
    )
    for entity_type, aspects in aspect_groups:
        endpoint = f"{server.rstrip('/')}/openapi/v3/entity/{entity_type}?async=false"
        for urn, aspect_name, aspect in aspects:
            proposal = [
                {
                    "urn": urn,
                    aspect_name: {
                        "value": aspect,
                        "headers": {},
                    },
                }
            ]
            request = Request(
                endpoint,
                data=json.dumps(proposal, ensure_ascii=False).encode("utf-8"),
                headers=_headers(token),
                method="POST",
            )
            with opener(request, timeout=timeout) as response:
                response.read()
            aspect_count += 1
    return {
        "status": "PUBLISHED",
        "catalog_version": catalog["catalog_version"],
        "catalog_sha256": catalog["catalog_sha256"],
        "dataset_descriptions": catalog["counts"]["datasets"],
        "column_descriptions": catalog["counts"]["field_occurrences"],
        "metric_glossary_terms": len(glossary["metrics"]),
        "metric_glossary_version": glossary["version"],
        "metric_glossary_sha256": canonical_glossary_hash(glossary),
        "aspect_upserts": aspect_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("DATAHUB_GMS_URL", "http://localhost:18081"))
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--glossary", type=Path, default=DEFAULT_GLOSSARY)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    result = publish(
        args.server,
        args.catalog,
        args.glossary,
        token=os.getenv("DATAHUB_GMS_TOKEN"),
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
