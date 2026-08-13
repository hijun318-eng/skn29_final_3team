"""Publish the versioned serving Semantic Catalog to a local DataHub GMS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG = ROOT / "src/data/serving_semantic_catalog.i4.v1.json"
LOCAL_GMS_HOSTS = {"localhost", "127.0.0.1", "::1", "datahub-gms", "datahub-gms-quickstart"}


def canonical_catalog_hash(catalog: dict[str, Any]) -> str:
    payload = {key: value for key, value in catalog.items() if key != "catalog_sha256"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    token: str | None = None,
    timeout: float = 30,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    validate_local_server(server)
    catalog, contract = load_catalog(catalog_path)
    endpoint = f"{server.rstrip('/')}/openapi/v3/entity/dataset?async=false"
    aspect_count = 0
    for urn, aspect_name, aspect in iter_aspects(catalog, contract):
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
        "aspect_upserts": aspect_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("DATAHUB_GMS_URL", "http://localhost:18081"))
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    result = publish(
        args.server,
        args.catalog,
        token=os.getenv("DATAHUB_GMS_TOKEN"),
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
