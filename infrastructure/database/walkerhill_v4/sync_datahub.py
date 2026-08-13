#!/usr/bin/env python3
"""Bind and publish the v4 catalog to exact live DataHub dataset URNs."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CATALOG = ROOT / "output" / "walkerhill_v4_candidate" / "metadata" / "datahub_catalog.json"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
PLATFORMS = {
    "reference": "trino",
    "serving": "trino",
    "pms": "postgres",
    "pos": "mysql",
    "crm": "mssql",
    "facility": "clickhouse",
    "banquet": "postgres",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def actual_name(dataset: dict) -> str:
    domain = dataset["id"].split(".", 1)[0]
    table = dataset["fqn"].rsplit(".", 1)[1]
    if domain in {"reference", "serving"}:
        return f"serving_v4.{dataset['fqn']}"
    if domain == "pms":
        return f"pms_v4.pms_db.walkerhill_v4.{table}"
    if domain == "pos":
        return f"pos_v4.walkerhill_v4.{table}"
    if domain == "crm":
        return f"crm_v4.crm_db.walkerhill_v4.{table}"
    if domain == "facility":
        return f"facility_v4.walkerhill_v4.{table}"
    if domain == "banquet":
        return f"banquet_v4.banquet_db.walkerhill_v4.{table}"
    raise ValueError(f"unsupported domain: {domain}")


def dataset_urn(dataset: dict) -> str:
    domain = dataset["id"].split(".", 1)[0]
    return f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORMS[domain]},{actual_name(dataset)},PROD)"


def headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "X-RestLi-Protocol-Version": "2.0.0"}


def fetch_aspects(server: str, urn: str) -> dict:
    aspect_names = (
        "List(status,schemaMetadata,dataPlatformInstance,upstreamLineage,"
        "editableDatasetProperties,datasetProperties,editableSchemaMetadata,ownership,domains,globalTags)"
    )
    endpoint = f"{server}/entitiesV2/{quote(urn, safe='')}?aspects={aspect_names}"
    with urlopen(Request(endpoint, headers=headers()), timeout=30) as response:
        return json.loads(response.read().decode("utf-8")).get("aspects", {})


def upsert(server: str, entity_type: str, urn: str, aspects: dict) -> None:
    endpoint = f"{server}/openapi/v3/entity/{entity_type}?async=false"
    for name, value in aspects.items():
        proposal = [{"urn": urn, name: {"value": value, "headers": {}}}]
        request = Request(
            endpoint,
            data=json.dumps(proposal, ensure_ascii=False).encode("utf-8"),
            headers=headers(),
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            response.read()


def dataset_description(dataset: dict) -> str:
    return (
        f"{dataset['description']}\n\n"
        f"Grain: {dataset['grain']}\n"
        f"Synthetic: true (실제 Walkerhill 내부 데이터 아님)\n"
        f"Provenance: {dataset['provenance_class']}\n"
        f"Quality status: {dataset['quality_status']}"
    )


def tag_urn(name: str) -> str:
    return f"urn:li:tag:walkerhill_v4_{name.lower()}"


def verify_published_metadata(dataset: dict, aspects: dict) -> None:
    required = {
        "editableDatasetProperties",
        "datasetProperties",
        "editableSchemaMetadata",
        "ownership",
        "domains",
        "globalTags",
    }
    missing = required - set(aspects)
    if missing:
        raise ValueError(f"published aspects are missing for {dataset['fqn']}: {sorted(missing)}")
    if aspects["editableDatasetProperties"]["value"].get("description") != dataset_description(dataset):
        raise ValueError(f"dataset description mismatch after publish: {dataset['fqn']}")
    properties = aspects["datasetProperties"]["value"].get("customProperties", {})
    if properties.get("grain") != dataset["grain"] or properties.get("synthetic") != "true":
        raise ValueError(f"dataset custom properties mismatch after publish: {dataset['fqn']}")
    owners = {item["owner"] for item in aspects["ownership"]["value"].get("owners", [])}
    if f"urn:li:corpGroup:{dataset['owner']}" not in owners:
        raise ValueError(f"dataset owner mismatch after publish: {dataset['fqn']}")
    domains = set(aspects["domains"]["value"].get("domains", []))
    if f"urn:li:domain:walkerhill_v4_{dataset['domain']}" not in domains:
        raise ValueError(f"dataset domain mismatch after publish: {dataset['fqn']}")
    dataset_tags = {
        item["tag"] for item in aspects["globalTags"]["value"].get("tags", [])
    }
    if tag_urn("synthetic") not in dataset_tags:
        raise ValueError(f"synthetic tag mismatch after publish: {dataset['fqn']}")
    actual_fields = {
        item["fieldPath"]: item
        for item in aspects["editableSchemaMetadata"]["value"].get("editableSchemaFieldInfo", [])
    }
    for field in dataset["fields"]:
        actual = actual_fields.get(field["name"], {})
        tags = {item["tag"] for item in actual.get("globalTags", {}).get("tags", [])}
        if actual.get("description") != field["description"] or tag_urn(
            f"sensitivity_{field['sensitivity']}"
        ) not in tags:
            raise ValueError(f"field metadata mismatch after publish: {dataset['fqn']}.{field['name']}")


def connector_lineage(dataset: dict, aspects: dict, catalog: dict) -> dict:
    lineage = copy.deepcopy(aspects.get("upstreamLineage", {}).get("value"))
    if not lineage:
        raise ValueError(f"serving lineage is missing: {dataset['fqn']}")
    replacements = {
        f"urn:li:dataset:(urn:li:dataPlatform:trino,serving_v4.{source['fqn']},PROD)": dataset_urn(source)
        for source in catalog["datasets"]
        if source["id"].split(".", 1)[0] not in {"reference", "serving"}
    }

    def replace(value):
        if isinstance(value, str):
            for old, new in replacements.items():
                value = value.replace(old, new)
            return value
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value

    lineage = replace(lineage)
    raw = json.dumps(lineage, ensure_ascii=False)
    source_domains = {"pms", "pos", "crm", "facility", "banquet"}
    if any(f"urn:li:dataPlatform:trino,serving_v4.{domain}." in raw for domain in source_domains):
        raise ValueError(f"unbound Trino upstream remains: {dataset['fqn']}")
    return lineage


def publish_reference_entities(server: str, catalog: dict) -> None:
    owners = sorted({dataset["owner"] for dataset in catalog["datasets"]})
    domains = sorted({dataset["domain"] for dataset in catalog["datasets"]})
    sensitivities = sorted(
        {field["sensitivity"] for dataset in catalog["datasets"] for field in dataset["fields"]}
    )
    tags = {"synthetic": "실제 Walkerhill 내부 데이터가 아닌 합성 데이터"}
    tags.update({f"sensitivity_{value}": f"컬럼 민감도: {value}" for value in sensitivities})
    for owner in owners:
        upsert(
            server,
            "corpGroup",
            f"urn:li:corpGroup:{owner}",
            {"corpGroupInfo": {"admins": [], "members": [], "groups": [], "displayName": owner}},
        )
    for domain in domains:
        upsert(
            server,
            "domain",
            f"urn:li:domain:walkerhill_v4_{domain}",
            {"domainProperties": {"name": f"Walkerhill v4 - {domain}", "description": "합성 데이터 후보 도메인"}},
        )
    for name, description in tags.items():
        upsert(server, "tag", tag_urn(name), {"tagProperties": {"name": name, "description": description}})


def sync(
    server: str,
    catalog_path: Path,
    publish: bool,
    report_path: Path,
    domains: set[str] | None = None,
) -> dict:
    catalog = load_json(catalog_path)
    selected = [
        dataset
        for dataset in catalog["datasets"]
        if domains is None or dataset["id"].split(".", 1)[0] in domains
    ]
    bindings = []
    field_count = 0
    for dataset in selected:
        urn = dataset_urn(dataset)
        aspects = fetch_aspects(server, urn)
        if "status" not in aspects or "schemaMetadata" not in aspects:
            raise ValueError(f"connector asset is missing: {dataset['fqn']} -> {urn}")
        actual_fields = {
            field["fieldPath"] for field in aspects["schemaMetadata"]["value"].get("fields", [])
        }
        expected_fields = {field["name"] for field in dataset["fields"]}
        if actual_fields != expected_fields:
            raise ValueError(
                f"field binding mismatch: {dataset['fqn']} missing={sorted(expected_fields-actual_fields)} "
                f"extra={sorted(actual_fields-expected_fields)}"
            )
        field_count += len(actual_fields)
        bindings.append({"id": dataset["id"], "fqn": dataset["fqn"], "urn": urn, "fields": len(actual_fields)})

    if publish:
        publish_reference_entities(server, catalog)
        for dataset in selected:
            urn = dataset_urn(dataset)
            live_aspects = fetch_aspects(server, urn)
            custom_properties = {
                key: str(dataset[key]).lower() if isinstance(dataset[key], bool) else str(dataset[key])
                for key in (
                    "grain",
                    "domain",
                    "layer",
                    "provenance_class",
                    "synthetic",
                    "preferred_asset",
                    "deprecated",
                    "time_field",
                    "quality_status",
                    "schema_version",
                )
            }
            field_info = [
                {
                    "fieldPath": field["name"],
                    "description": field["description"],
                    "globalTags": {
                        "tags": [{"tag": tag_urn(f"sensitivity_{field['sensitivity']}")}]
                    },
                }
                for field in dataset["fields"]
            ]
            published_aspects = {
                "editableDatasetProperties": {
                    "name": dataset["business_name"],
                    "description": dataset_description(dataset),
                },
                "datasetProperties": {
                    "name": dataset["business_name"],
                    "qualifiedName": dataset["fqn"],
                    "description": dataset["description"],
                    "customProperties": custom_properties,
                },
                "editableSchemaMetadata": {"editableSchemaFieldInfo": field_info},
                "ownership": {
                    "owners": [
                        {"owner": f"urn:li:corpGroup:{dataset['owner']}", "type": "TECHNICAL_OWNER"}
                    ]
                },
                "domains": {"domains": [f"urn:li:domain:walkerhill_v4_{dataset['domain']}"]},
                "globalTags": {"tags": [{"tag": tag_urn("synthetic")}]},
            }
            if dataset["id"].startswith("serving."):
                published_aspects["upstreamLineage"] = connector_lineage(dataset, live_aspects, catalog)
            upsert(
                server,
                "dataset",
                urn,
                published_aspects,
            )
        for dataset in selected:
            verify_published_metadata(dataset, fetch_aspects(server, dataset_urn(dataset)))

    report = {
        "status": "PUBLISHED_AND_VERIFIED" if publish else "BINDING_VERIFIED",
        "catalog_version": catalog["catalog_version"],
        "dataset_count": len(bindings),
        "field_count": field_count,
        "bindings": bindings,
    }
    serving_lineages = [
        fetch_aspects(server, dataset_urn(dataset)).get("upstreamLineage", {}).get("value", {})
        for dataset in selected
        if dataset["id"].startswith("serving.")
    ]
    if serving_lineages:
        upstreams = {
            upstream["dataset"]
            for lineage in serving_lineages
            for upstream in lineage.get("upstreams", [])
        }
        phantom = sorted(
            urn
            for urn in upstreams
            if "urn:li:dataPlatform:trino,serving_v4." in urn
        )
        report["lineage"] = {
            "serving_view_count": len(serving_lineages),
            "upstream_asset_count": len(upstreams),
            "fine_grained_lineage_count": sum(
                len(lineage.get("fineGrainedLineages", [])) for lineage in serving_lineages
            ),
            "phantom_trino_upstreams": phantom,
            "status": "PASSED" if not phantom else "FAILED",
        }
        if phantom:
            raise ValueError(f"phantom Trino upstream assets remain: {phantom}")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://localhost:18081")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--report", type=Path, default=ROOT / "output" / "walkerhill_v4_runtime" / "datahub_report.json")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--domain", action="append")
    args = parser.parse_args()
    parsed = urlparse(args.server)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOCAL_HOSTS:
        raise ValueError("DataHub sync is restricted to local GMS")
    report = sync(
        args.server.rstrip("/"),
        args.catalog.resolve(),
        args.publish,
        args.report.resolve(),
        set(args.domain) if args.domain else None,
    )
    print(json.dumps({key: report[key] for key in report if key != "bindings"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
