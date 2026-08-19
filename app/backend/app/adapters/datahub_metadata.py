"""DataHub native aspect와 Answervice custom property를 교차 검증해 runtime 도메인 값으로 변환한다."""

from __future__ import annotations

from typing import Any

from app.adapters.datahub_contract_values import (
    dataset_key as _dataset_key,
    grain as _grain,
    governance_urns as _governance_urns,
    governed_properties as _governed_properties,
    join_graph as _join_graph,
    json_array as _json_array,
    json_boolean as _json_boolean,
    json_object as _json_object,
    parameter_contract as _parameter_contract,
    qualified_fields as _qualified_fields,
    query_policy as _query_policy,
    time_rules as _time_rules,
)
from app.adapters.datahub_metadata_types import GlossaryMetricTerm, GovernedDataset
from app.adapters.datahub_metadata_values import (
    GovernedMetadataError,
    checksum,
    dataset_has_runtime_governance,
    fqn,
    identifier,
    native_governance,
    required_text,
    string_set,
    term_urns,
)
from app.services.context.values import FILTER_OPERATORS
from src.data.governance_contract import (
    DATASET_RUNTIME_PROPERTY_KEYS,
    MANIFEST_DATASET_KEYS,
    RUNTIME_GOVERNANCE_VERSION,
    TERM_RUNTIME_PROPERTY_KEYS,
    datahub_schema_sha1,
)


_COLUMN_ROLES = {"identifier", "dimension", "measure", "time", "attribute"}
_AGGREGATIONS = {"sum", "count", "count_distinct", "min", "max", "average", "none"}
_REDUCTIONS = {"sum", "min", "max", "average", "scalar"}


def parse_glossary_term(value: object) -> GlossaryMetricTerm:
    """Glossary Term의 native 승인·소유·domain과 metric rule checksum을 검증해 ``GlossaryMetricTerm``을 만든다."""
    if not isinstance(value, dict) or value.get("exists") is not True:
        raise GovernedMetadataError("DataHub glossary term does not exist")
    owner_urns, domain_urn, lifecycle_urn = native_governance(
        value, "glossary term"
    )
    urn = required_text(value.get("urn"), "glossary term urn")
    info = value.get("glossaryTermInfo")
    if not isinstance(info, dict):
        raise GovernedMetadataError("DataHub glossaryTermInfo is missing")
    properties = _governed_properties(
        info.get("customProperties"), TERM_RUNTIME_PROPERTY_KEYS
    )
    if properties["approval_status"] != "APPROVED":
        raise GovernedMetadataError("DataHub metric glossary term is not approved")
    metric_id = identifier(properties["metric_id"], "metric id")
    label = required_text(info.get("name"), "metric label")
    definition = required_text(info.get("description"), "metric definition")
    version = required_text(properties["glossary_version"], "glossary version")
    if info.get("sourceRef") != version or info.get("termSource") != "INTERNAL":
        raise GovernedMetadataError("DataHub glossary source identity is invalid")
    aliases = tuple(
        required_text(item, "metric alias")
        for item in _json_array(properties["aliases"], "metric aliases")
    )
    if not aliases or len(set(aliases)) != len(aliases) or label not in aliases:
        raise GovernedMetadataError("DataHub metric aliases are incomplete or duplicate")
    metric_rule = _json_object(properties["metric_rule"], "metric rule")
    return GlossaryMetricTerm(
        id=metric_id,
        urn=urn,
        label=label,
        aliases=aliases,
        definition=definition,
        unit=required_text(properties["unit"], "metric unit"),
        version=version,
        checksum=checksum(properties["glossary_sha256"]),
        catalog_checksum=checksum(properties["catalog_sha256"]),
        metric_rule=metric_rule,
        owner_urns=owner_urns,
        domain_urn=domain_urn,
        lifecycle_urn=lifecycle_urn,
    )


def parse_dataset(value: object) -> GovernedDataset:
    """dataset의 native governance·schema·release fingerprint를 custom contract와 대조해 ``GovernedDataset``을 만든다."""
    if not isinstance(value, dict):
        raise GovernedMetadataError("DataHub dataset must be an object")
    owner_urns, domain_urn, lifecycle_urn = native_governance(value, "dataset")
    urn = required_text(value.get("urn"), "dataset urn")
    properties = value.get("properties")
    if not isinstance(properties, dict):
        raise GovernedMetadataError("DataHub dataset properties are missing")
    custom = _governed_properties(
        properties.get("customProperties"),
        DATASET_RUNTIME_PROPERTY_KEYS,
    )
    # custom property만 믿으면 DataHub native 승인 철회나 소유권 변경을 우회할 수 있어 두 표현을 함께 검증한다.
    if custom["contract_version"] != RUNTIME_GOVERNANCE_VERSION:
        raise GovernedMetadataError("DataHub runtime governance version is unsupported")
    if custom["approval_status"] != "APPROVED":
        raise GovernedMetadataError("DataHub runtime governance is not approved")
    asset_fqn = fqn(custom["fqn"])
    if (
        value.get("name") != asset_fqn
        or
        properties.get("name") != asset_fqn
        or properties.get("qualifiedName") != asset_fqn
    ):
        raise GovernedMetadataError("DataHub dataset identity differs from its Trino FQN")
    release_manifest = _json_object(
        custom["release_manifest"], "release manifest"
    )
    typed_columns = _json_array(custom["typed_columns"], "typed columns")
    column_roles = _json_object(custom["column_roles"], "column roles")
    schema_metadata = value.get("schemaMetadata")
    columns, field_terms, schema_hash, trino_schema_columns = _schema_fields(
        schema_metadata,
        typed_columns,
        column_roles,
    )
    dataset_terms = term_urns(value.get("glossaryTerms"))
    parameter_contract = _parameter_contract(
        _json_object(custom["parameter_contract"], "parameter contract")
    )
    dimensions = _dimensions(
        _json_array(custom["dimensions"], "dimensions")
    )
    metrics = _metrics(
        _json_array(custom["metrics"], "metrics"),
        columns,
        field_terms,
        dataset_terms,
        parameter_contract,
    )
    entitlements = _json_object(custom["entitlements"], "entitlements")
    if set(entitlements) != {"roles", "domains"}:
        raise GovernedMetadataError("DataHub entitlement fields are invalid")
    roles = string_set(entitlements["roles"], "allowed roles")
    domains = string_set(entitlements["domains"], "allowed domains")
    if not roles and not domains:
        raise GovernedMetadataError("DataHub entitlement metadata is empty")
    if domains and (
        domain_urn not in domains
        or any(not item.startswith("urn:li:domain:") for item in domains)
    ):
        raise GovernedMetadataError(
            "DataHub entitlement domains differ from the native dataset domain"
        )
    time_rules, time_metadata = _time_rules(
        _json_object(custom["time_rules"], "time rules"),
        parameter_contract,
    )
    manifest_entry = _manifest_dataset_entry(release_manifest, urn)
    if manifest_entry.get("fqn") != asset_fqn:
        raise GovernedMetadataError(
            "DataHub release manifest FQN differs from runtime governance"
        )
    if not owner_urns:
        raise GovernedMetadataError("DataHub dataset must have at least one native owner")
    platform_urn, physical_key = _dataset_key(urn)
    if not isinstance(schema_metadata, dict):
        raise GovernedMetadataError("DataHub schema metadata is missing")
    schema_name = required_text(schema_metadata.get("name"), "schema name")
    schema_metadata_version = schema_metadata.get("version")
    if (
        not isinstance(schema_metadata_version, int)
        or isinstance(schema_metadata_version, bool)
        or schema_metadata_version < 0
    ):
        raise GovernedMetadataError("DataHub schema metadata version is invalid")
    grain = _grain(_json_object(custom["grain"], "grain"), columns)
    governance = _governance_urns(
        _json_object(custom["governance_urns"], "governance URNs")
    )
    matching_owners = owner_urns & set(governance["owners"])
    if (
        not matching_owners
        or domain_urn not in governance["domains"]
        or lifecycle_urn not in governance["approved_lifecycles"]
    ):
        raise GovernedMetadataError(
            "DataHub native governance is outside the published release"
        )
    owner_urn = sorted(matching_owners)[0]
    table_type = required_text(manifest_entry["table_type"], "Trino table type")
    catalog_asset = {
        "urn": urn,
        "fqn": asset_fqn,
        "description": required_text(properties.get("description"), "asset description"),
        "schema_version": required_text(custom["schema_version"], "schema version"),
        "seed_version": required_text(custom["seed_version"], "seed version"),
        "synthetic": _json_boolean(custom["synthetic"], "synthetic flag"),
        "approval_status": custom["approval_status"],
        "entitlements": entitlements,
        "grain": grain,
        "columns": typed_columns,
        "owner_urn": owner_urn,
        "domain_urn": domain_urn,
        "approved_lifecycle_urn": lifecycle_urn,
        "platform_urn": platform_urn,
        "schema_name": schema_name,
        "schema_metadata_version": schema_metadata_version,
        "dataset_key": physical_key,
        "table_type": table_type,
    }
    return GovernedDataset(
        urn=urn,
        fqn=asset_fqn,
        name=asset_fqn,
        description=catalog_asset["description"],
        context_release=required_text(custom["catalog_version"], "catalog version"),
        policy_version=required_text(custom["policy_version"], "policy version"),
        catalog_checksum=checksum(custom["catalog_sha256"]),
        manifest_checksum=checksum(custom["manifest_sha256"]),
        release_manifest=release_manifest,
        semantic_checksum=checksum(manifest_entry["semantic_sha256"]),
        schema_context_version=required_text(
            custom["schema_context_version"], "schema context version"
        ),
        governance_urns=governance,
        catalog_asset=catalog_asset,
        schema_hash=schema_hash,
        table_type=table_type,
        trino_schema_checksum=checksum(manifest_entry["trino_schema_sha256"]),
        trino_schema_columns=trino_schema_columns,
        schema_version=catalog_asset["schema_version"],
        seed_version=catalog_asset["seed_version"],
        synthetic=catalog_asset["synthetic"],
        allowed_roles=frozenset(roles),
        allowed_domains=frozenset(domains),
        grain=grain,
        columns=columns,
        field_terms=field_terms,
        dataset_terms=dataset_terms,
        metrics=metrics,
        dimensions=dimensions,
        join_graph=_join_graph(_json_object(custom["join_graph"], "join graph")),
        time_metadata=time_metadata,
        time_rules=time_rules,
        parameter_contract=parameter_contract,
        query_policy=_query_policy(
            _json_object(custom["query_policy"], "query policy")
        ),
        owner_urns=owner_urns,
        domain_urn=domain_urn,
        lifecycle_urn=lifecycle_urn,
    )


def _schema_fields(value, typed_columns, column_roles):
    if not isinstance(value, dict) or not isinstance(value.get("fields"), list):
        raise GovernedMetadataError("DataHub schema field metadata is missing")
    expected = {}
    for item in typed_columns:
        required = {
            "name", "native_type", "logical_type", "nullable",
            "is_part_of_key", "role", "description", "ordinal_position"
        }
        if not isinstance(item, dict) or set(item) != required:
            raise GovernedMetadataError("DataHub typed column fields are invalid")
        name = required_text(item["name"], "column name")
        if (
            name in expected
            or not isinstance(item["nullable"], bool)
            or not isinstance(item["is_part_of_key"], bool)
            or item["role"] not in _COLUMN_ROLES
            or column_roles.get(name) != item["role"]
        ):
            raise GovernedMetadataError("DataHub typed column governance is invalid")
        expected[name] = item
    if not expected or set(column_roles) != set(expected):
        raise GovernedMetadataError("DataHub column roles differ from typed columns")
    columns = []
    trino_columns = []
    associations = {}
    for field in value["fields"]:
        if not isinstance(field, dict):
            raise GovernedMetadataError("DataHub schema field is invalid")
        name = required_text(field.get("fieldPath"), "schema field path")
        governed = expected.get(name)
        if governed is None or name in associations:
            raise GovernedMetadataError("DataHub schema fields differ from typed columns")
        if (
            field.get("nativeDataType") != governed["native_type"]
            or field.get("nullable") is not governed["nullable"]
            or field.get("isPartOfKey") is not governed["is_part_of_key"]
            or field.get("description") != governed["description"]
        ):
            raise GovernedMetadataError("DataHub native and governed column metadata differ")
        associations[name] = term_urns(field.get("glossaryTerms"))
        columns.append(
            {
                "name": name,
                "native_type": governed["native_type"],
                "nullable": governed["nullable"],
                "role": governed["role"],
            }
        )
        ordinal = governed["ordinal_position"]
        if (
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or ordinal != len(trino_columns) + 1
        ):
            raise GovernedMetadataError("DataHub column ordinal positions are invalid")
        trino_columns.append(
            {
                "ordinal_position": ordinal,
                "name": name,
                "native_type": governed["native_type"],
                "nullable": governed["nullable"],
            }
        )
    if set(associations) != set(expected):
        raise GovernedMetadataError("DataHub schema field set is incomplete")
    schema_hash = required_text(value.get("hash"), "schema metadata hash")
    expected_hash = datahub_schema_sha1({"columns": typed_columns})
    if schema_hash != expected_hash:
        raise GovernedMetadataError(
            "DataHub schema hash differs from governed typed columns"
        )
    return tuple(columns), associations, schema_hash, tuple(trino_columns)


def _manifest_dataset_entry(manifest, urn):
    values = manifest.get("datasets")
    matches = [
        item
        for item in values
        if isinstance(item, dict) and item.get("urn") == urn
    ] if isinstance(values, list) else []
    if len(matches) != 1 or set(matches[0]) != MANIFEST_DATASET_KEYS:
        raise GovernedMetadataError(
            "DataHub release manifest lacks the dataset fingerprint"
        )
    return matches[0]


def _metrics(values, columns, field_terms, dataset_terms, parameters):
    if len(values) > 64:
        raise GovernedMetadataError("DataHub metrics must be a bounded array")
    column_names = {item["name"] for item in columns}
    parameter_types = {
        item["name"]: (item["type"], item["scope"])
        for item in parameters["parameters"]
    }
    metrics = []
    ids = set()
    required = {
        "id", "term_urn", "field", "aggregation", "time_field", "result_field",
        "reduction", "dimensions", "required_filters",
    }
    for raw in values:
        if not isinstance(raw, dict) or set(raw) != required:
            raise GovernedMetadataError("DataHub metric fields are invalid")
        metric_id = identifier(raw["id"], "metric id")
        term_urn = required_text(raw["term_urn"], "metric term urn")
        field = required_text(raw["field"], "metric field")
        time_field = required_text(raw["time_field"], "metric time field")
        visible_field_terms = field_terms.get(field, frozenset())
        if (
            metric_id in ids
            or field not in column_names
            or time_field not in column_names
            or raw["aggregation"] not in _AGGREGATIONS
            or raw["reduction"] not in _REDUCTIONS
            or term_urn not in dataset_terms
            # WHY: DataHub v1.7은 editableSchemaMetadata에 저장된 연결을
            # schemaMetadata.fields.glossaryTerms로 투영하지 않는다. dataset-level
            # association과 checksum-bound metrics는 항상 검증하고, field projection이
            # 실제로 보일 때만 동일 term인지 추가로 대조한다.
            or (visible_field_terms and term_urn not in visible_field_terms)
        ):
            raise GovernedMetadataError("DataHub metric governance is inconsistent")
        ids.add(metric_id)
        metrics.append(
            {
                "id": metric_id,
                "term_urn": term_urn,
                "field": field,
                "aggregation": raw["aggregation"],
                "time_field": time_field,
                "result_field": identifier(raw["result_field"], "metric result field"),
                "reduction": raw["reduction"],
                "dimensions": _qualified_fields(raw["dimensions"], "metric dimensions"),
                "required_filters": _filter_contracts(
                    raw["required_filters"], column_names, parameter_types
                ),
            }
        )
    return tuple(metrics)


def _filter_contracts(values, columns, parameters):
    if not isinstance(values, list) or len(values) > 32:
        raise GovernedMetadataError("DataHub required filters must be bounded")
    result = []
    for item in values:
        if not isinstance(item, dict) or set(item) != {"field", "operator", "parameter"}:
            raise GovernedMetadataError("DataHub required filter fields are invalid")
        name = required_text(item["parameter"], "filter parameter")
        if (
            item["field"] not in columns
            or item["operator"] not in FILTER_OPERATORS
            or parameters.get(name, (None, None))[1] != "filter"
        ):
            raise GovernedMetadataError("DataHub required filter governance is invalid")
        result.append(dict(item))
    return result


def _dimensions(values):
    if len(values) > 64:
        raise GovernedMetadataError("DataHub dimensions must be bounded")
    result = []
    ids = set()
    for item in values:
        required = {"id", "aliases", "definition", "asset_fqn", "column"}
        if not isinstance(item, dict) or set(item) != required:
            raise GovernedMetadataError("DataHub dimension fields are invalid")
        dimension_id = identifier(item["id"], "dimension id")
        raw_aliases = item["aliases"]
        aliases = string_set(raw_aliases, "dimension aliases")
        if (
            dimension_id in ids
            or not aliases
            or not isinstance(raw_aliases, list)
            or len(raw_aliases) != len(aliases)
        ):
            raise GovernedMetadataError("DataHub dimensions are duplicate or incomplete")
        ids.add(dimension_id)
        result.append(
            {
                "id": dimension_id,
                "aliases": list(raw_aliases),
                "definition": required_text(item["definition"], "dimension definition"),
                "asset_fqn": fqn(item["asset_fqn"]),
                "column": required_text(item["column"], "dimension column"),
            }
        )
    return tuple(result)


__all__ = [
    "GlossaryMetricTerm",
    "GovernedDataset",
    "GovernedMetadataError",
    "dataset_has_runtime_governance",
    "parse_dataset",
    "parse_glossary_term",
]
