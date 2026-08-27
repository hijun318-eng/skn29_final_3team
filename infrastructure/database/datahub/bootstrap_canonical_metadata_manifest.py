"""검증된 두 baseline에서 Git canonical metadata 초안 한 세트를 최초 생성한다."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.runtime_catalog_projection import RuntimeCatalogProjection  # noqa: E402
from canonical_metadata_manifest import (  # noqa: E402
    REVIEW_REQUIRED,
    SCHEMA_VERSION,
    load_canonical_metadata_manifest,
)
from export_datahub_metadata_baseline import (  # noqa: E402
    validate_datahub_metadata_baseline,
)
from export_runtime_catalog_baseline import (  # noqa: E402
    validate_runtime_catalog_baseline,
)
from metadata_classification import classify_column  # noqa: E402
from semantic_authoring import CURRENT_AUTHORING_FOR_RUNTIME  # noqa: E402
from src.data.governance_contract import canonical_json, canonical_sha256  # noqa: E402
from src.data.metric_governance import metric_contract_version  # noqa: E402


_SCOPES = ("pms", "pos", "crm", "banquet", "facility", "serving")
_NOT_APPLICABLE = "NOT_APPLICABLE"
_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TIME_OF_DAY_TYPE = re.compile(
    r"^time(?:\(\d+\))?(?:\s+(?:with|without)\s+time\s+zone)?$",
    re.IGNORECASE,
)


def build_canonical_metadata_draft(
    runtime_baseline: Mapping[str, Any],
    datahub_baseline: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """활성 53/592 의미를 보존하고 미승인 분류는 REVIEW_REQUIRED로 남긴다."""

    validate_runtime_catalog_baseline(runtime_baseline)
    validate_datahub_metadata_baseline(datahub_baseline)
    pointer = _mapping(runtime_baseline.get("active_pointer"), "active pointer")
    active_documents = [
        item
        for item in _list(runtime_baseline.get("runtime_projections"), "runtime projections")
        if isinstance(item, Mapping)
        and item.get("projection_id") == pointer.get("projection_id")
    ]
    if len(active_documents) != 1:
        raise ValueError("active runtime projection does not resolve exactly once")
    projection = RuntimeCatalogProjection.from_document(active_documents[0])
    snapshot = projection.as_document()["snapshot"]
    datasets = _list(snapshot.get("datasets"), "active datasets")
    datahub_entities = {
        str(item["urn"]): item
        for item in _list(datahub_baseline.get("entities"), "DataHub entities")
        if isinstance(item, Mapping) and item.get("entity_type") == "dataset"
    }
    exact_field_terms = _field_term_map(datahub_baseline)
    dataset_id_by_urn = {
        _text(item.get("urn"), "active Dataset URN"): (
            f"{_text(item.get('fqn'), 'active Dataset FQN').split('.')[0]}."
            f"{_text(item.get('fqn'), 'active Dataset FQN').split('.')[-1]}"
        )
        for item in datasets
    }
    upstream_ids_by_urn: dict[str, list[str]] = {}
    for raw_upstream, raw_downstream in _list(
        _mapping(datahub_baseline.get("exact_sets"), "DataHub exact sets").get(
            "dataset_lineage_edges"
        ),
        "DataHub lineage edges",
        empty=True,
    ):
        upstream = dataset_id_by_urn.get(str(raw_upstream))
        downstream = str(raw_downstream)
        if upstream is not None and downstream in dataset_id_by_urn:
            upstream_ids_by_urn.setdefault(downstream, []).append(upstream)

    dataset_files: dict[str, list[dict[str, Any]]] = {
        scope: [] for scope in _SCOPES
    }
    quality_policies: list[dict[str, Any]] = []
    active_field_identities: set[tuple[str, str]] = set()
    for dataset in sorted(datasets, key=lambda item: str(item["urn"])):
        urn = _text(dataset.get("urn"), "active Dataset URN")
        fqn = _text(dataset.get("fqn"), "active Dataset FQN")
        parts = fqn.split(".")
        if len(parts) != 3 or parts[0] not in dataset_files:
            raise ValueError("active Dataset FQN is outside canonical source scopes")
        scope = parts[0]
        entity = _mapping(datahub_entities.get(urn), "active DataHub Dataset")
        aspects = _mapping(entity.get("aspects"), "active Dataset aspects")
        schema = _mapping(aspects.get("schemaMetadata"), "active Dataset schema")
        raw_fields = {
            _text(item.get("fieldPath"), "DataHub field path"): item
            for item in _list(schema.get("fields"), "DataHub schema fields")
            if isinstance(item, Mapping)
        }
        asset = _mapping(dataset.get("catalog_asset"), "runtime catalog asset")
        asset_columns = _list(asset.get("columns"), "runtime asset columns")
        if set(raw_fields) != {
            _text(item.get("name"), "runtime Column name")
            for item in asset_columns
            if isinstance(item, Mapping)
        }:
            raise ValueError("active runtime and raw DataHub field memberships differ")
        grain = deepcopy(_mapping(dataset.get("grain"), "Dataset grain"))
        grain_keys = {
            _text(item, "grain key")
            for item in _list(grain.get("keys"), "Dataset grain keys")
        }
        primary_keys = sorted(
            name for name, item in raw_fields.items() if item.get("isPartOfKey") is True
        )
        event_fields = _event_fields(dataset, fqn, asset_columns)
        event_time = _event_time_contract(event_fields, asset_columns)
        operational = _dataset_operational_contract(
            scope,
            synthetic=bool(asset.get("synthetic")),
        )
        columns = []
        for raw_asset_column in asset_columns:
            column = _mapping(raw_asset_column, "runtime asset Column")
            name = _text(column.get("name"), "runtime Column name")
            raw = _mapping(raw_fields[name], "raw DataHub Column")
            nullable = raw.get("nullable")
            if not isinstance(nullable, bool):
                raise ValueError("raw DataHub Column nullability is invalid")
            raw_key = raw.get("isPartOfKey")
            if not isinstance(raw_key, bool):
                raise ValueError("raw DataHub Column key role is unavailable")
            runtime_role = _text(column.get("role"), "runtime Column role")
            classification = classify_column(name)
            value: dict[str, Any] = {
                "column_name": name,
                "data_type": _text(raw.get("nativeDataType"), "raw Column type"),
                "nullable": nullable,
                "key_role": (
                    "PRIMARY_KEY"
                    if raw_key
                    else "GRAIN_KEY"
                    if name in grain_keys
                    else "NONE"
                ),
                "semantic_role": "timestamp" if runtime_role == "time" else runtime_role,
                "sensitivity": classification.sensitivity,
                "pii_type": classification.pii_type,
                "logical_type": _text(column.get("logical_type"), "logical Column type"),
                "authoring_is_part_of_key": name in grain_keys,
            }
            description = column.get("description")
            if isinstance(description, str) and description.strip():
                value["description"] = _repair_utf8_mojibake(description.strip())
            terms = exact_field_terms.get((urn, name), ())
            if terms:
                value["term_urns"] = list(terms)
            columns.append(value)
            active_field_identities.add((urn, name))

        dataset_id = f"{scope}.{parts[-1]}"
        draft = {
            "dataset_id": dataset_id,
            "physical_urn": urn,
            "fqn": fqn,
            "business_name": REVIEW_REQUIRED,
            "description": _repair_utf8_mojibake(
                _text(dataset.get("description"), "Dataset description")
            ),
            "domain_urn": _text(dataset.get("domain_urn"), "Dataset Domain"),
            "source_system": scope.upper(),
            "grain": grain,
            "primary_key": primary_keys or sorted(grain_keys),
            "event_time": event_time,
            "update_frequency": operational["update_frequency"],
            "freshness_slo": operational["freshness_slo"],
            "data_origin": "SYNTHETIC" if dataset.get("synthetic") is True else REVIEW_REQUIRED,
            "owner_group_urn": _single(
                dataset.get("owner_urns"), "Dataset owner group"
            ),
            "lifecycle": "DRAFT",
            "sensitivity": (
                "RESTRICTED"
                if any(item["sensitivity"] == "RESTRICTED" for item in columns)
                else "INTERNAL"
            ),
            "authoring": {
                "schema_version": _text(asset.get("schema_version"), "schema version"),
                "seed_version": _text(asset.get("seed_version"), "seed version"),
                "synthetic": bool(asset.get("synthetic")),
                "approval_status": _text(asset.get("approval_status"), "approval status"),
                "entitlements": deepcopy(_mapping(asset.get("entitlements"), "entitlements")),
                "approved_lifecycle_urn": _text(
                    asset.get("approved_lifecycle_urn"), "approved lifecycle"
                ),
            },
            "columns": columns,
        }
        dataset_files[scope].append(draft)
        quality_policies.append(
            {
                "dataset_id": dataset_id,
                "schema_fingerprint_sha256": canonical_sha256(
                    [
                        [
                            urn,
                            column["column_name"],
                            column["data_type"],
                            column["nullable"],
                        ]
                        for column in columns
                    ]
                ),
                "freshness": operational["freshness_check"],
                "row_count": "COUNT_GT_ZERO",
                "required_keys": "NOT_NULL:" + ",".join(primary_keys or sorted(grain_keys)),
                "timestamp_validity": (
                    "VALID_DATE_OR_TIMESTAMP:" + ",".join(event_fields)
                    if event_fields
                    else _NOT_APPLICABLE
                    if event_time == _NOT_APPLICABLE
                    else REVIEW_REQUIRED
                ),
                "lineage": (
                    {"mode": "SOURCE_ROOT"}
                    if scope != "serving"
                    else {
                        "mode": "UPSTREAM",
                        "upstream_dataset_ids": sorted(
                            set(upstream_ids_by_urn.get(urn, []))
                        ),
                    }
                    if upstream_ids_by_urn.get(urn)
                    else REVIEW_REQUIRED
                ),
                "status": "DRAFT",
            }
        )

    baseline_active_fields = {
        (str(row[0]), str(row[1]))
        for row in datahub_baseline["exact_sets"]["columns"]
        if str(row[0]) in {str(item["urn"]) for item in datasets}
    }
    if active_field_identities != baseline_active_fields:
        raise ValueError("canonical draft field membership differs from DataHub baseline")

    governance = _mapping(snapshot.get("governance_entities"), "governance entities")
    source = {
        "datahub_baseline_sha256": _text(
            datahub_baseline.get("content_sha256"), "DataHub baseline checksum"
        ),
        "runtime_baseline_sha256": _text(
            runtime_baseline.get("content_sha256"), "runtime baseline checksum"
        ),
        "active_projection_sha256": projection.projection_sha256,
        "active_catalog_release_id": projection.catalog_release_id,
    }
    domains_document = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "domains": deepcopy(_list(governance.get("domains"), "Domains")),
        "owner_groups": deepcopy(_list(governance.get("owners"), "owner groups")),
        "lifecycles": deepcopy(
            _list(governance.get("approved_lifecycles"), "lifecycles")
        ),
    }
    glossary_document = {
        "schema_version": SCHEMA_VERSION,
        "glossary_terms": _glossary_terms(snapshot),
    }
    rules = _metric_rules(datasets)
    runtime_version = metric_contract_version(rules)
    contract_version = CURRENT_AUTHORING_FOR_RUNTIME.get(runtime_version)
    if contract_version is None:
        raise ValueError("active Metric governance cannot compile an authoring contract")
    first = _mapping(datasets[0], "active Dataset")
    semantics_document = {
        "schema_version": SCHEMA_VERSION,
        "authoring": {
            "contract_version": contract_version,
            "catalog_version": projection.catalog_release_id,
            "glossary_version": _shared_term_version(snapshot),
            "policy_version": _text(first.get("policy_version"), "policy version"),
            "schema_context_version": _text(
                first.get("schema_context_version"), "schema context version"
            ),
        },
        "metrics": _metrics(rules, snapshot, governance),
        "dimensions": _shared(datasets, "dimensions"),
        "join_graph": _shared(datasets, "join_graph"),
        "time_rules": _shared(datasets, "time_rules"),
        "parameter_contract": _shared(datasets, "parameter_contract"),
        "query_policy": _shared(datasets, "query_policy"),
    }
    quality_document = {
        "schema_version": SCHEMA_VERSION,
        "quality_policies": sorted(
            quality_policies, key=lambda item: item["dataset_id"]
        ),
    }
    result = {
        "domains.yml": domains_document,
        "glossary.yml": glossary_document,
        "semantics.yml": semantics_document,
        "quality.yml": quality_document,
    }
    result.update(
        {
            f"datasets/{scope}.yml": {
                "schema_version": SCHEMA_VERSION,
                "source_scope": scope,
                "datasets": sorted(
                    dataset_files[scope], key=lambda item: item["dataset_id"]
                ),
            }
            for scope in _SCOPES
        }
    )
    return result


def write_canonical_metadata_draft(
    documents: Mapping[str, Mapping[str, Any]], output_dir: Path
) -> dict[str, Any]:
    """기존 manifest를 덮지 않고 생성한 뒤 공용 loader로 즉시 재검증한다."""

    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    schema_target = root / "schema.json"
    if not schema_target.exists():
        shutil.copyfile(HERE / "metadata" / "schema.json", schema_target)
    dataset_dir = root / "datasets"
    dataset_dir.mkdir(exist_ok=True)
    for relative, document in sorted(documents.items()):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(
                json.loads(canonical_json(document)),
                stream,
                allow_unicode=True,
                sort_keys=False,
                width=120,
            )
    manifest = load_canonical_metadata_manifest(root)
    return {
        "schema_version": "answervice.canonical-metadata-bootstrap-receipt.v1",
        "status": manifest.status,
        "content_sha256": manifest.content_sha256,
        "inventory": manifest.inventory,
        "review_required_count": len(manifest.review_required),
        "mutation_count": 0,
        "output": str(root),
    }


def _field_term_map(baseline: Mapping[str, Any]) -> dict[tuple[str, str], tuple[str, ...]]:
    result: dict[tuple[str, str], list[str]] = {}
    for row in baseline["exact_sets"]["field_term_edges"]:
        result.setdefault((str(row[0]), str(row[1])), []).append(str(row[2]))
    return {key: tuple(sorted(set(values))) for key, values in result.items()}


def _dataset_operational_contract(
    scope: str,
    *,
    synthetic: bool,
) -> dict[str, str]:
    if scope not in _SCOPES:
        raise ValueError("Dataset scope is outside the canonical manifest")
    if not synthetic:
        return {
            "update_frequency": REVIEW_REQUIRED,
            "freshness_slo": REVIEW_REQUIRED,
            "freshness_check": REVIEW_REQUIRED,
        }
    if scope == "serving":
        return {
            "update_frequency": "QUERY_TIME_VIEW",
            "freshness_slo": "UPSTREAM_ACTIVE_DATA_RELEASE_WATERMARK",
            "freshness_check": "UPSTREAM_FRESHNESS_PROPAGATED",
        }
    return {
        "update_frequency": "ON_DATA_RELEASE",
        "freshness_slo": "ACTIVE_DATA_RELEASE_SEED_VERSION_MATCH",
        "freshness_check": "SEED_VERSION_MATCHES_ACTIVE_DATA_RELEASE",
    }


def _event_fields(
    dataset: Mapping[str, Any],
    fqn: str,
    columns: Sequence[Mapping[str, Any]],
) -> list[str]:
    by_name = {
        _text(column.get("name"), "runtime Column name"): column
        for raw in columns
        for column in (_mapping(raw, "runtime asset Column"),)
    }
    metadata = _mapping(dataset.get("time_metadata"), "time metadata")
    fields: set[str] = set()
    for raw in _list(metadata.get("fields"), "time metadata fields", empty=True):
        field = _mapping(raw, "time metadata field")
        reference = _mapping(field.get("field"), "time field reference")
        if reference.get("asset_fqn") == fqn:
            fields.add(_text(reference.get("column"), "event time Column"))

    grain = _mapping(dataset.get("grain"), "Dataset grain")
    for raw_key in _list(grain.get("keys"), "Dataset grain keys"):
        key = _text(raw_key, "Dataset grain key")
        column = by_name.get(key)
        if column is not None and column.get("logical_type") in {"date", "time"}:
            fields.add(key)

    temporal_columns = _temporal_column_names(columns)
    fields.update(temporal_columns)

    for name in fields:
        if name not in temporal_columns:
            raise ValueError("event time Column is absent or non-temporal")
    return sorted(fields)


def _event_time_contract(
    event_fields: Sequence[str],
    columns: Sequence[Mapping[str, Any]],
) -> list[str] | str:
    if event_fields:
        return sorted(set(event_fields))
    if not _temporal_column_names(columns):
        return _NOT_APPLICABLE
    return REVIEW_REQUIRED


def _temporal_column_names(columns: Sequence[Mapping[str, Any]]) -> list[str]:
    result = []
    for raw in columns:
        column = _mapping(raw, "runtime asset Column")
        logical_type = column.get("logical_type")
        if logical_type not in {"date", "time"}:
            continue
        native_type = _text(
            column.get("native_type") or column.get("data_type"),
            "runtime Column native type",
        )
        if logical_type == "time" and _TIME_OF_DAY_TYPE.fullmatch(native_type):
            continue
        result.append(_text(column.get("name"), "runtime Column name"))
    return sorted(result)


def _glossary_terms(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for raw in _list(snapshot.get("terms"), "business terms"):
        term = _mapping(raw, "business term")
        result.append(
            {
                "term_id": _text(term.get("id"), "term ID"),
                "urn": _text(term.get("urn"), "term URN"),
                "korean_name": _text(term.get("label"), "term label"),
                "definition": _text(term.get("definition"), "term definition"),
                "domain_urn": _text(term.get("domain_urn"), "term Domain"),
                "owner_group_urn": _single(term.get("owner_urns"), "term owner"),
                "lifecycle_urn": _text(term.get("lifecycle_urn"), "term lifecycle"),
                "kind": "BUSINESS_METRIC",
                "aliases": sorted(map(str, term.get("aliases", []))),
            }
        )
    for raw in _list(
        snapshot.get("dimension_member_terms"), "dimension member terms", empty=True
    ):
        term = _mapping(raw, "dimension member term")
        result.append(
            {
                "term_id": _text(term.get("id"), "member term ID"),
                "urn": _text(term.get("urn"), "member term URN"),
                "korean_name": _text(term.get("label"), "member term label"),
                "definition": _text(term.get("definition"), "member term definition"),
                "domain_urn": _text(term.get("domain_urn"), "member term Domain"),
                "owner_group_urn": _single(term.get("owner_urns"), "member owner"),
                "lifecycle_urn": _text(term.get("lifecycle_urn"), "member lifecycle"),
                "kind": "DIMENSION_MEMBER",
                "aliases": sorted(map(str, term.get("aliases", []))),
                "dimension_id": _text(term.get("dimension_id"), "dimension ID"),
                "canonical_value": _text(
                    term.get("canonical_value"), "canonical dimension value"
                ),
            }
        )
    return sorted(result, key=lambda item: item["term_id"])


def _metric_rules(datasets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for dataset in datasets:
        for raw in _list(dataset.get("metric_rules"), "Metric rules", empty=True):
            rule = deepcopy(_mapping(raw, "Metric rule"))
            metric_id = _text(rule.get("id"), "Metric ID")
            previous = result.get(metric_id)
            if previous is not None and canonical_json(previous) != canonical_json(rule):
                raise ValueError("active Metric rule differs across Dataset replicas")
            result[metric_id] = rule
    return [result[key] for key in sorted(result)]


def _shared_term_version(snapshot: Mapping[str, Any]) -> str:
    """활성 BUSINESS Glossary가 공유하는 명시적 content version을 보존한다."""

    versions = {
        _text(_mapping(raw, "business term").get("version"), "term version")
        for raw in _list(snapshot.get("terms"), "business terms")
    }
    if len(versions) != 1:
        raise ValueError("active business Glossary terms do not share one version")
    return next(iter(versions))


def _metrics(
    rules: Sequence[Mapping[str, Any]],
    snapshot: Mapping[str, Any],
    governance_entities: Mapping[str, Any],
) -> list[dict[str, Any]]:
    terms = {
        str(item["id"]): item for item in _list(snapshot.get("terms"), "terms")
    }
    owners = _list(governance_entities.get("owners"), "owner groups")
    default_owner = _text(owners[0].get("urn"), "default owner group")
    rules_by_id = {
        _text(rule.get("id"), "Metric ID"): rule for rule in rules
    }
    result = []
    for raw in rules:
        rule = deepcopy(_mapping(raw, "Metric rule"))
        metric_id = _text(rule.get("id"), "Metric ID")
        governance = _mapping(rule.get("governance"), "Metric governance")
        semantic = _mapping(governance.get("semantic"), "Metric semantics")
        time = deepcopy(_mapping(governance.get("time"), "Metric time"))
        visibility = _text(governance.get("visibility"), "Metric visibility")
        term = terms.get(metric_id)
        if visibility == "BUSINESS" and term is None:
            raise ValueError("Business Metric is missing its Glossary Term")
        source = deepcopy(_mapping(rule.get("source"), "Metric formula"))
        zero_policy = (
            _text(source.get("zero_policy"), "ratio zero policy")
            if source.get("kind") == "ratio"
            else "NOT_APPLICABLE"
        )
        result.append(
            {
                "metric_id": metric_id,
                "business_name": _text(
                    term.get("label") if term else semantic.get("name"),
                    "Metric business name",
                ),
                "definition": _text(
                    term.get("definition") if term else semantic.get("definition"),
                    "Metric definition",
                ),
                "visibility": (
                    "BUSINESS" if visibility == "BUSINESS" else "INTERNAL_SUPPORT"
                ),
                "user_selectable": visibility == "BUSINESS",
                "term_urn": str(term["urn"]) if term else None,
                "formula": source,
                "aggregation": _text(rule.get("aggregation"), "Metric aggregation"),
                "unit": _text(rule.get("unit"), "Metric unit"),
                "time_dimension": time,
                "timezone": _text(time.get("timezone"), "Metric timezone"),
                "grain": deepcopy(_mapping(governance.get("grain"), "Metric grain")),
                "allowed_dimensions": deepcopy(
                    _list(rule.get("dimensions"), "Metric dimensions", empty=True)
                ),
                "required_filters": deepcopy(
                    _list(rule.get("required_filters"), "Metric filters", empty=True)
                ),
                "null_policy": "SQL_AGGREGATE_IGNORE_NULLS",
                "zero_division_policy": zero_policy,
                "owner_group_urn": (
                    _single(term.get("owner_urns"), "Metric owner")
                    if term
                    else default_owner
                ),
                "validation_query": _metric_validation_query(rule, rules_by_id),
                "lifecycle": "DRAFT",
                "runtime_rule": rule,
            }
        )
    return result


def _metric_validation_query(
    rule: Mapping[str, Any],
    rules_by_id: Mapping[str, Mapping[str, Any]],
) -> str:
    metric_id = _text(rule.get("id"), "Metric ID")
    source = _mapping(rule.get("source"), "Metric formula")
    kind = _text(source.get("kind"), "Metric formula kind")
    if kind == "column":
        asset, time_column, aggregate = _column_metric_binding(rule)
        return (
            f"SELECT {_sql_literal(metric_id)} AS metric_id, "
            "CASE WHEN COUNT(*) = 0 "
            f"OR COUNT_IF({time_column} IS NULL) > 0 "
            f"OR {aggregate} IS NULL THEN 1 ELSE 0 END AS violation_count "
            f"FROM {asset}"
        )
    if kind != "ratio":
        raise ValueError("Metric validation query formula kind is unsupported")

    numerator_id = _text(source.get("numerator_metric_id"), "numerator Metric")
    denominator_id = _text(
        source.get("denominator_metric_id"), "denominator Metric"
    )
    numerator = _mapping(rules_by_id.get(numerator_id), "numerator Metric rule")
    denominator = _mapping(
        rules_by_id.get(denominator_id), "denominator Metric rule"
    )
    numerator_asset, numerator_time, numerator_aggregate = _column_metric_binding(
        numerator
    )
    denominator_asset, denominator_time, denominator_aggregate = (
        _column_metric_binding(denominator)
    )
    if (numerator_asset, numerator_time) != (denominator_asset, denominator_time):
        raise ValueError("ratio Metric validation inputs do not share one time grain")
    return (
        "WITH metric_inputs AS (SELECT "
        f"{numerator_aggregate} AS numerator_value, "
        f"{denominator_aggregate} AS denominator_value, "
        "COUNT(*) AS row_count, "
        f"COUNT_IF({numerator_time} IS NULL) AS invalid_time_count "
        f"FROM {numerator_asset}) "
        f"SELECT {_sql_literal(metric_id)} AS metric_id, "
        "CASE WHEN row_count = 0 OR invalid_time_count > 0 "
        "OR numerator_value IS NULL OR denominator_value IS NULL "
        "THEN 1 ELSE 0 END AS violation_count FROM metric_inputs"
    )


def _column_metric_binding(rule: Mapping[str, Any]) -> tuple[str, str, str]:
    source = _mapping(rule.get("source"), "Metric formula")
    if source.get("kind") != "column":
        raise ValueError("Metric validation dependency must use a Column formula")
    field = _mapping(source.get("field"), "Metric source field")
    time_field = _mapping(rule.get("time_field"), "Metric time field")
    asset = _text(field.get("asset_fqn"), "Metric source Dataset")
    if time_field.get("asset_fqn") != asset:
        raise ValueError("Metric value and time fields must share one Dataset")
    column = _sql_name(field.get("column"), "Metric source Column")
    time_column = _sql_name(time_field.get("column"), "Metric time Column")
    aggregation = _text(rule.get("aggregation"), "Metric aggregation")
    if aggregation == "sum":
        expression = f"SUM({column})"
    elif aggregation == "count_distinct":
        expression = f"COUNT(DISTINCT {column})"
    else:
        raise ValueError("Metric validation aggregation is unsupported")
    return _sql_fqn(asset), time_column, expression


def _sql_fqn(value: str) -> str:
    parts = value.split(".")
    if len(parts) != 3:
        raise ValueError("Metric source Dataset FQN must contain three parts")
    return ".".join(_sql_name(part, "Metric source Dataset FQN") for part in parts)


def _sql_name(value: object, context: str) -> str:
    name = _text(value, context)
    if not _SQL_IDENTIFIER.fullmatch(name):
        raise ValueError(f"{context} is not a safe SQL identifier")
    return name


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _repair_utf8_mojibake(value: str) -> str:
    """UTF-8 bytes가 단일 바이트 문자로 오해된 경우에만 원문을 복원한다."""

    if sum(character in "Âìëêí" for character in value) < 2:
        return value
    try:
        raw = b"".join(
            bytes((ord(character),))
            if ord(character) <= 255
            else character.encode("cp1252")
            for character in value
        )
        repaired = raw.decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError, ValueError):
        return value
    if not any("가" <= character <= "힣" for character in repaired):
        return value
    return repaired


def _shared(datasets: Sequence[Mapping[str, Any]], name: str) -> Any:
    values = [item.get(name) for item in datasets]
    if not values or any(canonical_json(item) != canonical_json(values[0]) for item in values[1:]):
        raise ValueError(f"active {name} differs across Dataset replicas")
    return deepcopy(values[0])


def _single(value: object, context: str) -> str:
    values = _list(value, context)
    if len(values) != 1:
        raise ValueError(f"{context} must resolve exactly once")
    return _text(values[0], context)


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return value


def _list(value: object, context: str, *, empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (not empty and not value):
        raise ValueError(f"{context} must be {'a' if empty else 'a non-empty'} list")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be non-empty text")
    return value.strip()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("baseline input is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError("baseline input must be an object")
    return value


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-baseline", type=Path, required=True)
    parser.add_argument("--datahub-baseline", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """검증된 두 baseline에서 canonical 초안을 만들고 실패 시 nonzero로 종료한다."""

    try:
        arguments = _arguments(argv)
        documents = build_canonical_metadata_draft(
            _json(arguments.runtime_baseline),
            _json(arguments.datahub_baseline),
        )
        print(
            canonical_json(
                write_canonical_metadata_draft(documents, arguments.output_dir)
            )
        )
        return 0
    except (OSError, RuntimeError, ValueError, yaml.YAMLError) as error:
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
