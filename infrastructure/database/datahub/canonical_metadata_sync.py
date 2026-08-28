"""Canonical metadata를 live DataHub에 checksum-bound 방식으로 동기화한다.

``--check``는 full-read diff만 만들고, ``--apply``는 그 exact check checksum을 다시
검증한 뒤 지원하는 aspect만 멱등 upsert하고 독립 full read-back으로 수렴을 확인한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from time import time_ns
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.datahub_catalog import DataHubCatalogClient  # noqa: E402
from canonical_metadata_manifest import (  # noqa: E402
    REVIEW_REQUIRED,
    CanonicalMetadataManifest,
    load_canonical_metadata_manifest,
)
from export_datahub_metadata_baseline import (  # noqa: E402
    _MAX_ENTITY_COUNT,
    build_datahub_metadata_baseline,
    validate_datahub_metadata_baseline,
)
from http_client import DataHubMetadataAdminClient  # noqa: E402
from native_metric_shadow import native_metric_urn  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import (  # noqa: E402
    canonical_json,
    canonical_sha256,
    metric_asset_fqns,
)


CHECK_SCHEMA_VERSION = "answervice.canonical-metadata-datahub-check.v1"
APPLY_PLAN_SCHEMA_VERSION = "answervice.canonical-metadata-datahub-apply-plan.v1"
APPLY_RECEIPT_SCHEMA_VERSION = "answervice.canonical-metadata-datahub-apply-receipt.v1"


def build_canonical_metadata_check(
    manifest: CanonicalMetadataManifest,
    live_baseline: Mapping[str, Any],
) -> dict[str, Any]:
    """검증된 manifest와 full-read baseline의 관리 범위 diff를 봉인한다."""

    validate_datahub_metadata_baseline(live_baseline)
    document = manifest.as_document()
    entities = {
        str(item["urn"]): item
        for item in _list(live_baseline.get("entities"), "live entities")
    }
    exact_sets = _mapping(live_baseline.get("exact_sets"), "live exact sets")
    datasets = _list(document.get("datasets"), "canonical datasets")
    managed_urns = {str(item["physical_urn"]) for item in datasets}
    live_dataset_urns = set(map(str, exact_sets.get("dataset_urns", [])))
    unmanaged_urns = sorted(live_dataset_urns - managed_urns)
    missing_datasets = sorted(managed_urns - live_dataset_urns)

    blockers: list[dict[str, Any]] = []
    if manifest.review_required:
        blockers.append(
            {
                "code": "MANIFEST_REVIEW_REQUIRED",
                "count": len(manifest.review_required),
                "paths_sha256": canonical_sha256(list(manifest.review_required)),
            }
        )
    source = _mapping(document.get("source"), "canonical source")
    source_baseline_sha256 = str(source.get("datahub_baseline_sha256", ""))
    live_sha256 = str(live_baseline.get("content_sha256", ""))
    # Source baseline은 manifest 작성 근거다. 실제 apply 승인은 현재 full-read checksum을
    # 포함한 check_sha256에 결속한다. 둘의 차이를 blocker로 만들면 첫 부분 적용 뒤 같은
    # manifest 재시도가 불가능하므로, 두 값은 receipt에 함께 보존하고 현재 diff를 판정한다.
    if missing_datasets:
        blockers.append(
            {
                "code": "MANAGED_DATASET_MISSING",
                "count": len(missing_datasets),
                "urns_sha256": canonical_sha256(missing_datasets),
            }
        )

    schema_drift = _schema_drift(datasets, exact_sets, managed_urns)
    if schema_drift:
        blockers.append(
            {
                "code": "MANAGED_SCHEMA_DRIFT",
                "count": len(schema_drift),
                "drift_sha256": canonical_sha256(schema_drift),
            }
        )

    missing_references = _missing_governance_references(document, entities)
    missing_terms, extra_terms = _term_membership(document, entities)
    missing_metrics, extra_metrics = _metric_membership(document, entities)
    missing_entities = sorted(
        {*missing_references, *missing_terms, *missing_metrics}
    )
    if missing_entities:
        blockers.append(
            {
                "code": "MANAGED_ENTITY_MISSING",
                "count": len(missing_entities),
                "urns_sha256": canonical_sha256(missing_entities),
            }
        )

    planned = _planned_changes(
        document,
        entities,
        exact_sets,
        managed_urns - set(missing_datasets),
    )
    content = {
        "schema_version": CHECK_SCHEMA_VERSION,
        "mode": "CHECK",
        "status": "BLOCKED" if blockers else "READY",
        "manifest_sha256": manifest.content_sha256,
        "source_datahub_baseline_sha256": source_baseline_sha256,
        "live_datahub_baseline_sha256": live_sha256,
        "scope": {
            "managed_dataset_count": len(managed_urns),
            "unmanaged_dataset_count": len(unmanaged_urns),
            "unmanaged_dataset_urns_sha256": canonical_sha256(unmanaged_urns),
            "unmanaged_dataset_policy": "OUT_OF_SCOPE_NO_MUTATION",
        },
        "blockers": sorted(blockers, key=lambda item: item["code"]),
        "diff": {
            "missing_managed_dataset_urns": missing_datasets,
            "schema_drift": schema_drift,
            "missing_managed_entity_urns": missing_entities,
            "retirement_candidate_term_urns": extra_terms,
            "retirement_candidate_metric_urns": extra_metrics,
        },
        "planned_changes": planned,
        "planned_change_count": len(planned),
        "mutation_count": 0,
    }
    return {**content, "check_sha256": canonical_sha256(content)}


def build_canonical_metadata_apply_plan(
    manifest: CanonicalMetadataManifest,
    live_baseline: Mapping[str, Any],
    *,
    expected_check_sha256: str,
) -> dict[str, Any]:
    """승인된 exact check를 보존형 Dataset aspect upsert 계획으로 변환한다."""

    check = build_canonical_metadata_check(manifest, live_baseline)
    if (
        not isinstance(expected_check_sha256, str)
        or len(expected_check_sha256) != 64
        or check["check_sha256"] != expected_check_sha256
        or check["status"] != "READY"
    ):
        raise ValueError("canonical metadata apply check is stale or blocked")

    document = manifest.as_document()
    datasets = {
        str(item["physical_urn"]): item
        for item in _list(document.get("datasets"), "canonical datasets")
    }
    entities = {
        str(item["urn"]): item
        for item in _list(live_baseline.get("entities"), "live entities")
    }
    mutations: list[dict[str, Any]] = []
    for raw_change in _list(check.get("planned_changes"), "planned changes"):
        change = _mapping(raw_change, "planned change")
        entity_type = str(change.get("entity_type"))
        urn = str(change.get("urn"))
        aspect = str(change.get("aspect"))
        fields = list(map(str, _list(change.get("fields"), "planned fields")))
        if entity_type != "dataset" or urn not in datasets or urn not in entities:
            raise ValueError("canonical metadata apply contains an unsupported entity")
        live_aspects = _mapping(
            entities[urn].get("aspects"), "live dataset aspects"
        )
        current = deepcopy(
            dict(_mapping(live_aspects.get(aspect, {}), f"live {aspect}"))
        )
        dataset = datasets[urn]
        if aspect == "datasetProperties":
            if not fields or not set(fields) <= {"name", "description"}:
                raise ValueError(
                    "canonical metadata apply contains unsupported Dataset properties"
                )
            desired = deepcopy(current)
            values = {
                "name": dataset.get("business_name"),
                "description": dataset.get("description"),
            }
            for field in fields:
                desired[field] = values[field]
        elif aspect == "editableSchemaMetadata":
            desired = _merge_column_descriptions(current, dataset, fields)
        elif aspect == "upstreamLineage":
            if fields != ["upstreams"]:
                raise ValueError(
                    "canonical metadata apply contains unsupported Dataset lineage"
                )
            desired = _merge_upstream_lineage(
                current,
                _desired_upstream_urns(document, str(dataset["dataset_id"])),
            )
        else:
            raise ValueError("canonical metadata apply contains an unsupported aspect")
        if canonical_sha256(current) == canonical_sha256(desired):
            raise ValueError("canonical metadata apply contains an empty mutation")
        mutations.append(
            {
                "entity_type": entity_type,
                "urn": urn,
                "aspect": aspect,
                "fields": fields,
                "before_sha256": canonical_sha256(current),
                "after_sha256": canonical_sha256(desired),
                "value": desired,
            }
        )

    content = {
        "schema_version": APPLY_PLAN_SCHEMA_VERSION,
        "manifest_sha256": manifest.content_sha256,
        "check_sha256": check["check_sha256"],
        "predecessor_datahub_baseline_sha256": live_baseline["content_sha256"],
        "mutations": mutations,
        "mutation_count": len(mutations),
    }
    if content["mutation_count"] != check["planned_change_count"]:
        raise ValueError("canonical metadata apply plan membership differs")
    return {**content, "plan_sha256": canonical_sha256(content)}


def _merge_column_descriptions(
    current: Mapping[str, Any],
    dataset: Mapping[str, Any],
    fields: Sequence[str],
) -> dict[str, Any]:
    """기존 editable field metadata를 보존하며 승인된 설명 필드만 병합한다."""

    columns = {
        str(item["column_name"]): item
        for item in _list(dataset.get("columns"), "canonical columns")
    }
    requested: dict[str, str] = {}
    for field in fields:
        name, separator, attribute = field.rpartition(".")
        if (
            not separator
            or attribute != "description"
            or name not in columns
            or not isinstance(columns[name].get("description"), str)
        ):
            raise ValueError(
                "canonical metadata apply contains an unsupported Column field"
            )
        requested[name] = str(columns[name]["description"])
    if not requested or len(requested) != len(fields):
        raise ValueError("canonical metadata Column description fields are invalid")

    infos = _list(
        current.get("editableSchemaFieldInfo", []), "editable schema fields"
    )
    merged_infos: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in infos:
        item = deepcopy(dict(_mapping(raw, "editable schema field")))
        name = str(item.get("fieldPath", ""))
        if not name or name in seen:
            raise ValueError("editable schema fields are missing or duplicated")
        seen.add(name)
        if name in requested:
            item["description"] = requested[name]
        merged_infos.append(item)
    for name in sorted(set(requested) - seen):
        merged_infos.append({"fieldPath": name, "description": requested[name]})
    desired = deepcopy(dict(current))
    desired["editableSchemaFieldInfo"] = merged_infos
    return desired


def _merge_upstream_lineage(
    current: Mapping[str, Any], expected_urns: tuple[str, ...]
) -> dict[str, Any]:
    """기존 edge audit는 보존하고 canonical direct upstream membership만 교체한다."""

    existing: dict[str, Mapping[str, Any]] = {}
    for raw in _list(current.get("upstreams", []), "live upstream lineage"):
        edge = _mapping(raw, "live upstream edge")
        urn = str(edge.get("dataset", ""))
        if not urn or urn in existing:
            raise ValueError("live upstream lineage identities are invalid")
        existing[urn] = edge
    desired = deepcopy(dict(current))
    desired["upstreams"] = [
        deepcopy(dict(existing[urn]))
        if urn in existing
        else {"dataset": urn, "type": "TRANSFORMED"}
        for urn in expected_urns
    ]
    return desired


async def apply_canonical_metadata_plan(
    client: Any,
    plan: Mapping[str, Any],
    *,
    actor_urn: str,
    clock_ms: int,
) -> int:
    """검증된 plan의 aspect를 순서대로 upsert하고 실제 mutation 수를 반환한다."""

    content = dict(plan)
    supplied_checksum = content.pop("plan_sha256", None)
    if (
        supplied_checksum != canonical_sha256(content)
        or not actor_urn.startswith("urn:li:corpuser:service_")
        or not isinstance(clock_ms, int)
        or isinstance(clock_ms, bool)
        or clock_ms <= 0
    ):
        raise ValueError("canonical metadata apply plan receipt is invalid")
    mutations = _list(content.get("mutations"), "apply mutations")
    if content.get("mutation_count") != len(mutations):
        raise ValueError("canonical metadata apply mutation count differs")
    for raw in mutations:
        mutation = _mapping(raw, "apply mutation")
        value = _mapping(mutation.get("value"), "apply aspect value")
        await client.upsert_entity(
            str(mutation["entity_type"]),
            str(mutation["urn"]),
            {str(mutation["aspect"]): value},
            {"actor": actor_urn, "time": clock_ms},
        )
    return len(mutations)


def _schema_drift(
    datasets: Sequence[Mapping[str, Any]],
    exact_sets: Mapping[str, Any],
    managed_urns: set[str],
) -> list[dict[str, Any]]:
    desired = {
        (str(dataset["physical_urn"]), str(column["column_name"])): (
            str(column["data_type"]),
            bool(column["nullable"]),
        )
        for dataset in datasets
        for column in _list(dataset.get("columns"), "canonical columns")
    }
    live = {
        (str(row[0]), str(row[1])): (str(row[2]), bool(row[3]))
        for row in _list(exact_sets.get("columns"), "live columns")
        if str(row[0]) in managed_urns
    }
    result: list[dict[str, Any]] = []
    for identity in sorted(set(desired) | set(live)):
        expected, actual = desired.get(identity), live.get(identity)
        if expected == actual:
            continue
        result.append(
            {
                "urn": identity[0],
                "column": identity[1],
                "kind": (
                    "MISSING"
                    if actual is None
                    else "UNEXPECTED"
                    if expected is None
                    else "MISMATCH"
                ),
                "expected": (
                    None
                    if expected is None
                    else {"data_type": expected[0], "nullable": expected[1]}
                ),
                "actual": (
                    None
                    if actual is None
                    else {"data_type": actual[0], "nullable": actual[1]}
                ),
            }
        )
    return result


def _missing_governance_references(
    document: Mapping[str, Any], entities: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    desired = {
        str(item["urn"])
        for key in ("domains", "owner_groups", "lifecycles")
        for item in _list(document.get(key), f"canonical {key}")
    }
    return sorted(desired - set(entities))


def _term_membership(
    document: Mapping[str, Any], entities: Mapping[str, Mapping[str, Any]]
) -> tuple[list[str], list[str]]:
    desired = {
        str(item["urn"])
        for item in _list(document.get("glossary_terms"), "canonical terms")
    }
    live = {
        urn
        for urn, entity in entities.items()
        if entity.get("entity_type") == "glossaryTerm"
    }
    managed_live = {
        urn
        for urn in live
        if _in_canonical_governance_scope(document, entities[urn])
    }
    return sorted(desired - live), sorted(managed_live - desired)


def _metric_membership(
    document: Mapping[str, Any], entities: Mapping[str, Mapping[str, Any]]
) -> tuple[list[str], list[str]]:
    desired = {
        native_metric_urn(document, str(item["metric_id"]))
        for item in _list(document.get("metrics"), "canonical metrics")
        if item.get("visibility") == "BUSINESS"
    }
    live = {
        urn
        for urn, entity in entities.items()
        if entity.get("entity_type") == "metric"
    }
    managed_live = {
        urn
        for urn in live
        if _in_canonical_governance_scope(document, entities[urn])
    }
    return sorted(desired - live), sorted(managed_live - desired)


def _in_canonical_governance_scope(
    document: Mapping[str, Any], entity: Mapping[str, Any]
) -> bool:
    """명시된 owner와 Domain을 모두 가진 live entity만 retirement 범위로 본다."""

    owner_scope = {
        str(item["urn"])
        for item in _list(document.get("owner_groups"), "canonical owner groups")
    }
    domain_scope = {
        str(item["urn"])
        for item in _list(document.get("domains"), "canonical domains")
    }
    aspects = _mapping(entity.get("aspects"), "live governed entity aspects")
    ownership = _mapping(aspects.get("ownership", {}), "live ownership")
    domains = _mapping(aspects.get("domains", {}), "live domains")
    owner_urns = {
        str(item.get("owner"))
        for item in _list(ownership.get("owners", []), "live owners")
        if isinstance(item, Mapping) and item.get("owner")
    }
    domain_urns = {
        str(value) for value in _list(domains.get("domains", []), "live Domain URNs")
    }
    return bool(owner_scope & owner_urns) and bool(domain_scope & domain_urns)


def _planned_changes(
    document: Mapping[str, Any],
    entities: Mapping[str, Mapping[str, Any]],
    exact_sets: Mapping[str, Any],
    present_managed_urns: set[str],
) -> list[dict[str, Any]]:
    changes: dict[tuple[str, str, str], set[str]] = {}

    def add(entity_type: str, urn: str, aspect: str, field: str) -> None:
        changes.setdefault((entity_type, urn, aspect), set()).add(field)

    dataset_by_fqn: dict[str, str] = {}
    desired_field_terms: set[tuple[str, str, str]] = set()
    desired_dataset_terms: set[tuple[str, str]] = set()
    datasets = _list(document.get("datasets"), "canonical datasets")
    for dataset in datasets:
        urn = str(dataset["physical_urn"])
        dataset_by_fqn[str(dataset["fqn"])] = urn
        if urn not in present_managed_urns:
            continue
        aspects = _mapping(entities[urn].get("aspects"), "live dataset aspects")
        properties = _mapping(aspects.get("datasetProperties"), "dataset properties")
        business_name = dataset.get("business_name")
        if business_name != REVIEW_REQUIRED and properties.get("name") != business_name:
            add("dataset", urn, "datasetProperties", "name")
        if properties.get("description") != dataset.get("description"):
            add("dataset", urn, "datasetProperties", "description")

        schema_fields = {
            str(item.get("fieldPath")): item
            for item in _list(
                _mapping(aspects.get("schemaMetadata"), "schema metadata").get("fields"),
                "schema fields",
            )
        }
        editable = {
            str(item.get("fieldPath")): item
            for item in _list(
                _mapping(
                    aspects.get("editableSchemaMetadata", {}),
                    "editable schema metadata",
                ).get("editableSchemaFieldInfo", []),
                "editable schema fields",
            )
        }
        for column in _list(dataset.get("columns"), "canonical columns"):
            name = str(column["column_name"])
            if name not in schema_fields:
                continue
            expected_description = column.get("description")
            actual_description = editable.get(name, {}).get("description")
            if not actual_description:
                actual_description = schema_fields[name].get("description")
            if expected_description is not None and actual_description != expected_description:
                add("dataset", urn, "editableSchemaMetadata", f"{name}.description")
            for term_urn in column.get("term_urns", []):
                desired_field_terms.add((urn, name, str(term_urn)))
                desired_dataset_terms.add((urn, str(term_urn)))

    rules = {
        str(item["metric_id"]): _mapping(item.get("runtime_rule"), "runtime rule")
        for item in _list(document.get("metrics"), "canonical metrics")
    }
    for metric in _list(document.get("metrics"), "canonical metrics"):
        if metric.get("visibility") != "BUSINESS":
            continue
        term_urn = str(metric["term_urn"])
        for fqn in metric_asset_fqns(
            _mapping(metric.get("runtime_rule"), "runtime rule"), rules
        ):
            urn = dataset_by_fqn.get(fqn)
            if urn in present_managed_urns:
                desired_dataset_terms.add((str(urn), term_urn))

    live_field_terms = {
        tuple(map(str, row))
        for row in _list(exact_sets.get("field_term_edges"), "field term edges")
        if str(row[0]) in present_managed_urns
    }
    for urn, column, _term in sorted(desired_field_terms ^ live_field_terms):
        add("dataset", urn, "editableSchemaMetadata", f"{column}.glossaryTerms")
    live_dataset_terms = {
        tuple(map(str, row))
        for row in _list(exact_sets.get("dataset_term_edges"), "dataset term edges")
        if str(row[0]) in present_managed_urns
    }
    for urn, _term in sorted(desired_dataset_terms ^ live_dataset_terms):
        add("dataset", urn, "glossaryTerms", "terms")

    _plan_association_changes(document, exact_sets, present_managed_urns, add)
    _plan_lineage_changes(document, exact_sets, present_managed_urns, add)
    _plan_term_changes(document, entities, add)
    _plan_metric_changes(document, entities, add)
    return [
        {
            "entity_type": entity_type,
            "urn": urn,
            "aspect": aspect,
            "fields": sorted(fields),
        }
        for (entity_type, urn, aspect), fields in sorted(changes.items())
    ]


def _plan_association_changes(
    document: Mapping[str, Any],
    exact_sets: Mapping[str, Any],
    present_urns: set[str],
    add: Any,
) -> None:
    specifications = (
        (
            "dataset_domain_edges",
            "domain_urn",
            "domains",
            lambda item: str(item["domain_urn"]),
        ),
        (
            "dataset_owner_edges",
            "owner_group_urn",
            "ownership",
            lambda item: str(item["owner_group_urn"]),
        ),
        (
            "dataset_lifecycle_edges",
            "lifecycle",
            "status",
            lambda item: str(item["authoring"]["approved_lifecycle_urn"]),
        ),
    )
    datasets = _list(document.get("datasets"), "canonical datasets")
    for exact_name, field, aspect, value in specifications:
        desired = {
            (str(item["physical_urn"]), value(item))
            for item in datasets
            if str(item["physical_urn"]) in present_urns
        }
        live = {
            tuple(map(str, row))
            for row in _list(exact_sets.get(exact_name), exact_name)
            if str(row[0]) in present_urns
        }
        for urn, _reference in sorted(desired ^ live):
            add("dataset", urn, aspect, field)


def _plan_lineage_changes(
    document: Mapping[str, Any],
    exact_sets: Mapping[str, Any],
    present_urns: set[str],
    add: Any,
) -> None:
    datasets = {
        str(item["dataset_id"]): str(item["physical_urn"])
        for item in _list(document.get("datasets"), "canonical datasets")
    }
    controlled_downstreams: set[str] = set()
    desired: set[tuple[str, str]] = set()
    for raw in _list(document.get("quality_policies"), "canonical quality policies"):
        policy = _mapping(raw, "canonical quality policy")
        dataset_id = str(policy["dataset_id"])
        downstream = datasets[dataset_id]
        lineage = policy.get("lineage")
        if not isinstance(lineage, Mapping) or lineage.get("mode") == "APPROVED_EXCEPTION":
            continue
        if downstream not in present_urns:
            continue
        controlled_downstreams.add(downstream)
        for upstream_id in lineage.get("upstream_dataset_ids", []):
            desired.add((datasets[str(upstream_id)], downstream))
    live = {
        tuple(map(str, row))
        for row in _list(
            exact_sets.get("dataset_lineage_edges"), "dataset lineage edges"
        )
        if str(row[1]) in controlled_downstreams
    }
    for _upstream, downstream in sorted(desired ^ live):
        add("dataset", downstream, "upstreamLineage", "upstreams")


def _desired_upstream_urns(
    document: Mapping[str, Any], dataset_id: str
) -> tuple[str, ...]:
    datasets = {
        str(item["dataset_id"]): str(item["physical_urn"])
        for item in _list(document.get("datasets"), "canonical datasets")
    }
    policies = {
        str(item["dataset_id"]): _mapping(item, "canonical quality policy")
        for item in _list(document.get("quality_policies"), "canonical quality policies")
    }
    lineage = _mapping(policies[dataset_id].get("lineage"), "canonical lineage")
    if lineage.get("mode") == "APPROVED_EXCEPTION":
        raise ValueError("approved lineage exception cannot produce a mutation")
    return tuple(
        sorted(datasets[str(item)] for item in lineage.get("upstream_dataset_ids", []))
    )


def _plan_term_changes(
    document: Mapping[str, Any],
    entities: Mapping[str, Mapping[str, Any]],
    add: Any,
) -> None:
    for term in _list(document.get("glossary_terms"), "canonical terms"):
        urn = str(term["urn"])
        entity = entities.get(urn)
        if entity is None:
            continue
        aspects = _mapping(entity.get("aspects"), "live term aspects")
        info = _mapping(aspects.get("glossaryTermInfo"), "term info")
        for field, expected in (
            ("name", term.get("korean_name")),
            ("definition", term.get("definition")),
        ):
            if info.get(field) != expected:
                add("glossaryTerm", urn, "glossaryTermInfo", field)
        aliases = _aliases(
            _mapping(info.get("customProperties", {}), "term custom properties").get(
                "answervice.aliases"
            )
        )
        if aliases != sorted(map(str, term.get("aliases", []))):
            add("glossaryTerm", urn, "glossaryTermInfo", "aliases")


def _plan_metric_changes(
    document: Mapping[str, Any],
    entities: Mapping[str, Mapping[str, Any]],
    add: Any,
) -> None:
    for metric in _list(document.get("metrics"), "canonical metrics"):
        if metric.get("visibility") != "BUSINESS":
            continue
        urn = native_metric_urn(document, str(metric["metric_id"]))
        entity = entities.get(urn)
        if entity is None:
            continue
        info = _mapping(
            _mapping(entity.get("aspects"), "live Metric aspects").get("metricInfo"),
            "Metric info",
        )
        if info.get("name") != metric.get("business_name"):
            add("metric", urn, "metricInfo", "name")


def _aliases(value: object) -> list[str] | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        return None
    return sorted(parsed)


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return value


def _list(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    return value


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--manifest-root", type=Path, default=HERE / "metadata")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--expected-check-sha256")
    return parser.parse_args(argv)


async def _read_live_baseline(
    settings: DataHubConnectionSettings, timeout: float
) -> dict[str, Any]:
    """조회 전용 identity로 독립 full metadata baseline을 만든다."""

    async with DataHubCatalogClient(
        settings.base_url,
        settings.token,
        ca_file=settings.ca_file,
        expected_actor_urn=settings.actor_urn,
        timeout_seconds=timeout,
        page_size=100,
        max_entities=_MAX_ENTITY_COUNT,
    ) as catalog, DataHubMetadataAdminClient(
        settings.base_url,
        token=settings.token,
        ca_file=settings.ca_file,
        timeout_seconds=timeout,
    ) as reader:
        if not await catalog.health():
            raise RuntimeError("DataHub read service identity is unavailable")
        baseline = await build_datahub_metadata_baseline(
            catalog,
            reader,
            actor_urn=settings.actor_urn,
            read_at=datetime.now(timezone.utc),
        )
    return baseline


async def _async_main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    if arguments.timeout <= 0:
        raise ValueError("canonical metadata timeout must be positive")
    if arguments.check and arguments.expected_check_sha256 is not None:
        raise ValueError("check mode does not accept an expected checksum")
    if arguments.apply and not arguments.expected_check_sha256:
        raise ValueError("apply mode requires the checked checksum")

    manifest = load_canonical_metadata_manifest(arguments.manifest_root)
    read_settings = DataHubConnectionSettings.from_env()
    baseline = await _read_live_baseline(read_settings, arguments.timeout)
    check = build_canonical_metadata_check(manifest, baseline)
    if arguments.check:
        print(canonical_json(check))
        return 0 if check["status"] == "READY" else 3

    plan = build_canonical_metadata_apply_plan(
        manifest,
        baseline,
        expected_check_sha256=arguments.expected_check_sha256,
    )
    publish_settings = DataHubConnectionSettings.from_publish_env()
    if (
        publish_settings.base_url != read_settings.base_url
        or publish_settings.ca_file != read_settings.ca_file
        or publish_settings.actor_urn == read_settings.actor_urn
        or publish_settings.token == read_settings.token
    ):
        raise ValueError("DataHub read and publish identity boundaries differ")

    applied_at_ms = time_ns() // 1_000_000
    async with DataHubCatalogClient(
        publish_settings.base_url,
        publish_settings.token,
        ca_file=publish_settings.ca_file,
        expected_actor_urn=publish_settings.actor_urn,
        timeout_seconds=arguments.timeout,
        page_size=100,
        max_entities=_MAX_ENTITY_COUNT,
    ) as publication_identity, DataHubMetadataAdminClient(
        publish_settings.base_url,
        token=publish_settings.token,
        ca_file=publish_settings.ca_file,
        timeout_seconds=arguments.timeout,
    ) as publisher:
        if not await publication_identity.health():
            raise RuntimeError("DataHub publish service identity is unavailable")
        mutation_count = await apply_canonical_metadata_plan(
            publisher,
            plan,
            actor_urn=publish_settings.actor_urn,
            clock_ms=applied_at_ms,
        )

    readback = await _read_live_baseline(read_settings, arguments.timeout)
    convergence = build_canonical_metadata_check(manifest, readback)
    if (
        convergence["status"] != "READY"
        or convergence["planned_change_count"] != 0
    ):
        raise RuntimeError("canonical metadata live read-back did not converge")

    content = {
        "schema_version": APPLY_RECEIPT_SCHEMA_VERSION,
        "status": "APPLIED_AND_VERIFIED",
        "manifest_sha256": manifest.content_sha256,
        "approved_check_sha256": check["check_sha256"],
        "apply_plan_sha256": plan["plan_sha256"],
        "predecessor_datahub_baseline_sha256": baseline["content_sha256"],
        "readback_datahub_baseline_sha256": readback["content_sha256"],
        "readback_check_sha256": convergence["check_sha256"],
        "planned_mutation_count": plan["mutation_count"],
        "mutation_count": mutation_count,
        "readback_planned_change_count": convergence["planned_change_count"],
    }
    deployment_receipt = {
        "read_actor_urn": read_settings.actor_urn,
        "publish_actor_urn": publish_settings.actor_urn,
        "applied_at_epoch_ms": applied_at_ms,
        "mutation_count": mutation_count,
    }
    result = {
        **content,
        "content_sha256": canonical_sha256(content),
        "deployment_receipt": deployment_receipt,
        "deployment_receipt_sha256": canonical_sha256(deployment_receipt),
    }
    print(canonical_json(result))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """명시된 check/apply 모드를 실행하고 비밀 없는 결과만 출력한다."""

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
