"""DataHub native aspect와 Answervice custom property를 교차 검증해 runtime 도메인 값으로 변환한다."""

from __future__ import annotations

from typing import Any
import unicodedata

from app.adapters.datahub_contract_values import (
    dataset_governed_properties as _dataset_governed_properties,
    dataset_key as _dataset_key,
    grain as _grain,
    governance_urns as _governance_urns,
    governed_properties as _governed_properties,
    join_graph as _join_graph,
    json_array as _json_array,
    json_boolean as _json_boolean,
    json_object as _json_object,
    parameter_contract as _parameter_contract,
    query_policy as _query_policy,
    time_rules as _time_rules,
)
from app.adapters.datahub_metric_governance import (
    parse_release_metric_rules,
    parse_runtime_metrics,
)
from app.adapters.datahub_metadata_types import (
    GlossaryDimensionMemberTerm,
    GlossaryMetricTerm,
    GovernedDataset,
)
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
from src.data.governance_contract import (
    DIMENSION_MEMBER_TERM_RUNTIME_PROPERTY_KEYS,
    MANIFEST_DATASET_KEYS,
    TERM_RUNTIME_PROPERTY_KEYS,
    datahub_schema_readback_sha1,
)
from src.data.entitlement_roles import validate_entitlement_roles


_COLUMN_ROLES = {"identifier", "dimension", "measure", "time", "attribute"}


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


def parse_dimension_member_term(value: object) -> GlossaryDimensionMemberTerm:
    """Glossary Term을 승인 Dimension Member의 불변 runtime identity로 검증한다."""

    if not isinstance(value, dict) or value.get("exists") is not True:
        raise GovernedMetadataError("DataHub dimension member term does not exist")
    owner_urns, domain_urn, lifecycle_urn = native_governance(
        value, "dimension member term"
    )
    urn = required_text(value.get("urn"), "dimension member term urn")
    info = value.get("glossaryTermInfo")
    if not isinstance(info, dict):
        raise GovernedMetadataError("DataHub dimension member info is missing")
    properties = _governed_properties(
        info.get("customProperties"),
        DIMENSION_MEMBER_TERM_RUNTIME_PROPERTY_KEYS,
    )
    if (
        properties["term_kind"] != "DIMENSION_MEMBER"
        or properties["approval_status"] != "APPROVED"
    ):
        raise GovernedMetadataError("DataHub dimension member is not approved")
    label = required_text(info.get("name"), "dimension member label")
    canonical_value = required_text(
        properties["canonical_value"], "dimension member canonical value"
    )
    version = required_text(
        properties["glossary_version"], "dimension member glossary version"
    )
    if info.get("sourceRef") != version or info.get("termSource") != "INTERNAL":
        raise GovernedMetadataError(
            "DataHub dimension member source identity is invalid"
        )
    aliases = tuple(
        required_text(item, "dimension member alias")
        for item in _json_array(properties["aliases"], "dimension member aliases")
    )
    normalized = {
        unicodedata.normalize("NFKC", item).casefold() for item in aliases
    }
    if (
        not aliases
        or len(aliases) != len(normalized)
        or unicodedata.normalize("NFKC", label).casefold() not in normalized
        or unicodedata.normalize("NFKC", canonical_value).casefold() not in normalized
    ):
        raise GovernedMetadataError(
            "DataHub dimension member aliases are incomplete or duplicate"
        )
    return GlossaryDimensionMemberTerm(
        id=identifier(properties["member_id"], "dimension member id"),
        dimension_id=identifier(properties["dimension_id"], "dimension id"),
        urn=urn,
        label=label,
        aliases=aliases,
        definition=required_text(info.get("description"), "dimension member definition"),
        canonical_value=canonical_value,
        version=version,
        checksum=checksum(properties["glossary_sha256"]),
        catalog_checksum=checksum(properties["catalog_sha256"]),
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
    custom = _dataset_governed_properties(properties.get("customProperties"))
    # custom property만 믿으면 DataHub native 승인 철회나 소유권 변경을 우회할 수 있어 두 표현을 함께 검증한다.
    if custom["approval_status"] != "APPROVED":
        raise GovernedMetadataError("DataHub runtime governance is not approved")
    asset_fqn = fqn(custom["fqn"])
    display_name = required_text(value.get("name"), "dataset name")
    property_name = required_text(
        properties.get("name"), "dataset property name"
    )
    # DataHub ``name``은 업무 표시명이고 ``qualifiedName``과 governed FQN이
    # 실행 식별자다. 표시명을 FQN으로 강제하면 canonical business_name 게시가
    # 정상적으로 끝난 직후 runtime parity가 전체 Dataset을 거부하게 된다.
    if (
        display_name != property_name
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
        value.get("editableSchemaMetadata"),
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
    entitlements = _json_object(custom["entitlements"], "entitlements")
    if set(entitlements) != {"roles", "domains"}:
        raise GovernedMetadataError("DataHub entitlement fields are invalid")
    roles = string_set(entitlements["roles"], "allowed roles")
    try:
        validate_entitlement_roles(roles)
    except ValueError as error:
        raise GovernedMetadataError(
            "DataHub entitlement metadata contains an unsupported role"
        ) from error
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
    physical_keys = {
        item["name"] for item in typed_columns if item["is_part_of_key"]
    }
    if not physical_keys <= set(grain["keys"]):
        raise GovernedMetadataError("DataHub grain removes a physical schema key")
    synthetic = _json_boolean(custom["synthetic"], "synthetic flag")
    join_graph = _join_graph(_json_object(custom["join_graph"], "join graph"))
    metric_rules = parse_release_metric_rules(
        _json_array(custom["metric_rules"], "metric rules")
        if "metric_rules" in custom
        else None,
        custom["contract_version"],
    )
    metrics = parse_runtime_metrics(
        _json_array(custom["metrics"], "metrics"),
        columns=columns,
        field_terms=field_terms,
        dataset_terms=dataset_terms,
        parameters=parameter_contract,
        contract_version=custom["contract_version"],
        metric_rules=metric_rules,
        asset_fqn=asset_fqn,
        allowed_roles=frozenset(roles),
        grain=grain,
        synthetic=synthetic,
        time_rules=time_rules,
        join_graph=join_graph,
    )
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
        "synthetic": synthetic,
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
        "datahub_schema_hash": schema_hash,
        "dataset_key": physical_key,
        "table_type": table_type,
    }
    return GovernedDataset(
        contract_version=custom["contract_version"],
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
        metric_rules=metric_rules,
        dimensions=dimensions,
        join_graph=join_graph,
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


def _schema_fields(value, editable_value, typed_columns, column_roles):
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
    datahub_columns = []
    associations = {}
    _editable_descriptions, editable_associations = _editable_fields(
        editable_value,
        set(expected),
    )
    for field in value["fields"]:
        if not isinstance(field, dict):
            raise GovernedMetadataError("DataHub schema field is invalid")
        name = required_text(field.get("fieldPath"), "schema field path")
        governed = expected.get(name)
        if governed is None or name in associations:
            raise GovernedMetadataError("DataHub schema fields differ from typed columns")
        if (
            not isinstance(field.get("nativeDataType"), str)
            or not field["nativeDataType"].strip()
            or field.get("nullable") is not governed["nullable"]
            or field.get("isPartOfKey") is not governed["is_part_of_key"]
        ):
            raise GovernedMetadataError("DataHub native and governed column metadata differ")
        # editable/native description은 DataHub 업무 문서이고 typed_columns는
        # immutable 실행 receipt다. 설명 개선이 실행 schema drift로 오인되지 않게
        # 분리하되 type·nullable·key와 아래 Glossary association은 계속 대조한다.
        schema_associations = term_urns(field.get("glossaryTerms"))
        if name in editable_associations:
            editable_terms = editable_associations[name]
            if schema_associations and schema_associations != editable_terms:
                raise GovernedMetadataError(
                    "DataHub schema and editable field glossary terms differ"
                )
            associations[name] = editable_terms
        else:
            associations[name] = schema_associations
        datahub_columns.append(
            {
                "ordinal_position": len(datahub_columns) + 1,
                "name": name,
                "native_type": field["nativeDataType"].strip(),
                "nullable": field["nullable"],
            }
        )
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
    schema_hash = datahub_schema_readback_sha1(datahub_columns)
    return tuple(columns), associations, schema_hash, tuple(trino_columns)


def _editable_fields(value, native_names):
    if value is None:
        return {}, {}
    if not isinstance(value, dict):
        raise GovernedMetadataError("DataHub editable schema metadata is invalid")
    fields = value.get("editableSchemaFieldInfo") or []
    if not isinstance(fields, list):
        raise GovernedMetadataError("DataHub editable schema fields are invalid")
    descriptions = {}
    associations = {}
    for field in fields:
        if not isinstance(field, dict):
            raise GovernedMetadataError("DataHub editable schema field is invalid")
        name = required_text(field.get("fieldPath"), "editable schema field path")
        description = field.get("description")
        if (
            name in descriptions
            or name not in native_names
            or (description is not None and not isinstance(description, str))
        ):
            raise GovernedMetadataError(
                "DataHub editable schema field identity is invalid"
            )
        descriptions[name] = (
            description.strip() if isinstance(description, str) else None
        )
        associations[name] = term_urns(field.get("glossaryTerms"))
    return descriptions, associations


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


def _dimensions(values):
    if len(values) > 64:
        raise GovernedMetadataError("DataHub dimensions must be bounded")
    result = []
    ids = set()
    for item in values:
        required = {"id", "aliases", "definition", "asset_fqn", "column"}
        if not isinstance(item, dict) or set(item) not in {
            frozenset(required),
            frozenset(required | {"members"}),
        }:
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
        dimension = {
                "id": dimension_id,
                "aliases": list(raw_aliases),
                "definition": required_text(item["definition"], "dimension definition"),
                "asset_fqn": fqn(item["asset_fqn"]),
                "column": required_text(item["column"], "dimension column"),
            }
        if "members" in item:
            dimension["members"] = _dimension_members(
                item["members"],
                dimension_id,
            )
        result.append(dimension)
    return tuple(result)


def _dimension_members(value: object, dimension_id: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > 64:
        raise GovernedMetadataError("DataHub dimension members must be bounded")
    required = {
        "id", "urn", "name", "definition", "aliases", "canonical_value",
        "version", "approval_status", "owner_urn", "domain_urn",
        "approved_lifecycle_urn",
    }
    result = []
    ids: set[str] = set()
    urns: set[str] = set()
    normalized_aliases: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != required:
            raise GovernedMetadataError("DataHub dimension member fields are invalid")
        member_id = identifier(raw["id"], "dimension member id")
        urn = required_text(raw["urn"], "dimension member urn")
        aliases = raw["aliases"]
        alias_set = string_set(aliases, "dimension member aliases")
        normalized = {
            unicodedata.normalize("NFKC", alias).casefold() for alias in alias_set
        }
        if (
            member_id in ids
            or urn in urns
            or not urn.startswith("urn:li:glossaryTerm:")
            or not alias_set
            or len(normalized) != len(alias_set)
            or normalized & normalized_aliases
            or raw["approval_status"] != "APPROVED"
            or unicodedata.normalize("NFKC", str(raw["name"])).casefold()
            not in normalized
            or unicodedata.normalize(
                "NFKC", str(raw["canonical_value"])
            ).casefold()
            not in normalized
        ):
            raise GovernedMetadataError(
                "DataHub dimension members are duplicate or incomplete"
            )
        for field in (
            "name", "definition", "canonical_value", "version", "owner_urn",
            "domain_urn", "approved_lifecycle_urn",
        ):
            required_text(raw[field], f"dimension member {field}")
        ids.add(member_id)
        urns.add(urn)
        normalized_aliases.update(normalized)
        result.append(dict(raw))
    return result


__all__ = [
    "GlossaryMetricTerm",
    "GlossaryDimensionMemberTerm",
    "GovernedDataset",
    "GovernedMetadataError",
    "dataset_has_runtime_governance",
    "parse_dataset",
    "parse_dimension_member_term",
    "parse_glossary_term",
]
