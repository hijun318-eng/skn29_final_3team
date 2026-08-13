"""Verify exact serving dataset and column descriptions in local DataHub."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import Request, urlopen


sys.path.insert(0, str(Path(__file__).resolve().parent))
from publish_semantic_catalog import (  # noqa: E402
    DEFAULT_CATALOG,
    _headers,
    catalog_marker,
    load_catalog,
    validate_local_server,
)


def _aspect_value(entity: dict[str, Any], name: str) -> dict[str, Any]:
    try:
        return entity["aspects"][name]["value"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"missing DataHub aspect: {name}") from exc


def verify(
    server: str,
    catalog_path: Path = DEFAULT_CATALOG,
    token: str | None = None,
    timeout: float = 30,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    validate_local_server(server)
    catalog, contract = load_catalog(catalog_path)
    marker = catalog_marker(catalog)
    dataset_count = 0
    column_count = 0
    # Rest.li collection parameters must preserve the List(...) syntax. Encoding
    # the comma makes GMS interpret the whole value as one aspect name.
    query = "aspects=List(editableDatasetProperties,editableSchemaMetadata)"
    for view in contract["views"]:
        endpoint = f"{server.rstrip('/')}/entitiesV2/{quote(view['urn'], safe='')}?{query}"
        request = Request(endpoint, headers=_headers(token), method="GET")
        with opener(request, timeout=timeout) as response:
            entity = json.loads(response.read().decode("utf-8"))

        expected_dataset = f"{catalog['dataset_descriptions'][view['fqn']]}\n\n{marker}"
        actual_dataset = _aspect_value(entity, "editableDatasetProperties").get("description")
        if actual_dataset != expected_dataset:
            raise ValueError(f"dataset description mismatch: {view['fqn']}")
        dataset_count += 1

        field_info = _aspect_value(entity, "editableSchemaMetadata").get("editableSchemaFieldInfo", [])
        actual_fields = {item.get("fieldPath"): item.get("description") for item in field_info}
        expected_fields = {
            field: catalog["field_descriptions"][field]
            for field in view["columns"]
        }
        if actual_fields != expected_fields:
            raise ValueError(f"column description mismatch: {view['fqn']}")
        column_count += len(actual_fields)

    if dataset_count != catalog["counts"]["datasets"] or column_count != catalog["counts"]["field_occurrences"]:
        raise ValueError("verified description cardinality mismatch")
    return {
        "status": "VERIFIED",
        "catalog_version": catalog["catalog_version"],
        "catalog_sha256": catalog["catalog_sha256"],
        "dataset_descriptions": dataset_count,
        "column_descriptions": column_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("DATAHUB_GMS_URL", "http://localhost:18081"))
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    result = verify(
        args.server,
        args.catalog,
        token=os.getenv("DATAHUB_GMS_TOKEN"),
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
