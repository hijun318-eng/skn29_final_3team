"""schema에 종속되지 않는 DataHub semantic publication bundle을 검증하고 렌더링한다."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from typing import Any

from metadata_contract_primitives import (
    SemanticMetadataError,
    array as _list,
    exact_keys as _exact_keys,
    fqn as _fqn,
    identifier as _identifier,
    mapping as _mapping,
    text as _text,
    unique_texts as _unique_texts,
    urn as _urn,
)
from metric_contract import validate_metrics
from metric_governance_contract import (
    validate_metric_terms,
    validate_v2_metric_release,
)

from src.data.governance_contract import (
    RUNTIME_GOVERNANCE_VERSION as CONTRACT_VERSION,
    SEMANTIC_RELEASE_KEYS,
    validate_governance_reference_coverage,
)
from src.data.entitlement_roles import validate_entitlement_roles


PROPERTY_PREFIX = "answervice."
_COLUMN_ROLES = {"identifier", "dimension", "measure", "time", "attribute"}
_GRAIN_KINDS = {"row", "event", "periodic", "aggregate"}
_JOIN_KINDS = {"inner", "left", "right", "full"}
_CARDINALITIES = {"one_to_one", "many_to_one", "one_to_many", "many_to_many"}
_PARAMETER_TYPES = {"string", "boolean", "number", "date", "timestamp"}
_PARAMETER_SCOPES = {"time", "filter", "limit"}
_TIME_BUCKETS = {"none", "day", "week", "month", "quarter", "year"}
_TIMEZONE_MODES = {"preserve", "context"}
_DATASET_ORIGINS = {"DEV", "TEST", "QA", "UAT", "EI", "PRE", "STG", "NON_PROD", "PROD", "CORP", "RVW", "PRD", "TST", "SIT", "SBX", "SANDBOX", "CERT"}
_LOGICAL_TYPES = {"boolean", "fixed", "string", "bytes", "number", "date", "time", "enum", "null", "map", "array", "union", "record"}
_ROOT_KEYS = SEMANTIC_RELEASE_KEYS


def load_bundle(path: Any) -> dict[str, Any]:
    """publication bundle 하나를 읽고 전체 검증을 마친 뒤에만 값을 반환한다."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SemanticMetadataError("semantic publication bundle is unreadable") from error
    if not isinstance(value, dict):
        raise SemanticMetadataError("semantic publication bundle must be an object")
    validate_bundle(value)
    return value


def validate_bundle(bundle: Mapping[str, Any]) -> None:
    """모든 semantic rule이 선언된 asset과 field로 해석되지 않으면 fail-closed한다."""

    _exact_keys(bundle, _ROOT_KEYS, "publication bundle")
    _text(bundle["catalog_version"], "catalog_version")
    _text(bundle["policy_version"], "policy_version")
    _reject_runtime_values(bundle)
    governance = _validate_governance_entities(bundle["governance_entities"])
    assets = _validate_schema_context(bundle["schema_context"], governance)
    asset_domains = {
        asset["fqn"]: asset["domain_urn"]
        for asset in bundle["schema_context"]["assets"]
    }
    parameters = _validate_parameters(bundle["parameter_contract"])
    metrics, metric_domains = validate_metrics(
        bundle["metric_rules"], assets, parameters, asset_domains
    )
    validate_metric_terms(
        bundle["metric_terms"], metrics, metric_domains, governance
    )
    _validate_dimensions(
        bundle["dimensions"],
        assets,
        governance,
        {str(item["urn"]) for item in bundle["metric_terms"]},
    )
    _validate_joins(bundle["join_graph"], assets)
    _validate_time_rules(bundle["time_rules"], assets, parameters)
    _validate_query_policy(bundle["query_policy"], assets)
    validate_v2_metric_release(bundle, metrics)
    try:
        validate_governance_reference_coverage(bundle)
    except ValueError as error:
        raise SemanticMetadataError(str(error)) from error


def _validate_governance_entities(
    value: object,
) -> dict[str, frozenset[str]]:
    governance = _mapping(value, "governance_entities")
    kinds = {
        "owners": ("urn:li:corpGroup:", False),
        "domains": ("urn:li:domain:", False),
        "approved_lifecycles": ("urn:li:lifecycleStageType:", True),
    }
    _exact_keys(governance, kinds, "governance_entities")
    result: dict[str, frozenset[str]] = {}
    for kind, (prefix, approved) in kinds.items():
        urns: set[str] = set()
        for index, raw in enumerate(
            _list(governance[kind], f"governance_entities.{kind}", non_empty=True)
        ):
            entity = _mapping(raw, f"governance_entities.{kind}[{index}]")
            _exact_keys(entity, {"urn", "name", "description"}, f"{kind}[{index}]")
            urn = _urn(entity["urn"], prefix, f"{kind}[{index}].urn")
            name = _text(entity["name"], f"{kind}[{index}].name")
            _text(entity["description"], f"{kind}[{index}].description")
            if urn in urns or (approved and name != "APPROVED"):
                raise SemanticMetadataError("governance entity identities must be unique and approved")
            urns.add(urn)
        result[kind] = frozenset(urns)
    return result


def _validate_schema_context(
    value: object,
    governance: Mapping[str, frozenset[str]],
) -> dict[str, frozenset[str]]:
    context = _mapping(value, "schema_context")
    _exact_keys(context, {"version", "assets"}, "schema_context")
    _text(context["version"], "schema_context.version")
    assets = _list(
        context["assets"], "schema_context.assets", non_empty=True, limit=1_000
    )
    columns_by_fqn: dict[str, frozenset[str]] = {}
    urns: set[str] = set()
    for index, raw in enumerate(assets):
        asset = _mapping(raw, f"asset[{index}]")
        _exact_keys(
            asset,
            {
                "urn", "fqn", "description", "schema_version", "seed_version",
                "synthetic", "approval_status", "entitlements", "grain", "columns",
                "owner_urn", "domain_urn", "approved_lifecycle_urn",
                "platform_urn", "schema_name", "schema_metadata_version",
                "datahub_schema_hash", "dataset_key",
                "table_type",
            },
            f"asset[{index}]",
        )
        urn = _text(asset["urn"], f"asset[{index}].urn")
        fqn = _fqn(asset["fqn"], f"asset[{index}].fqn")
        _text(asset["description"], f"asset[{index}].description")
        _text(asset["schema_version"], f"asset[{index}].schema_version")
        _text(asset["seed_version"], f"asset[{index}].seed_version")
        platform_urn = _urn(
            asset["platform_urn"],
            "urn:li:dataPlatform:",
            f"asset[{index}].platform_urn",
        )
        dataset_key = _mapping(asset["dataset_key"], f"asset[{index}].dataset_key")
        _exact_keys(dataset_key, {"platform", "name", "origin"}, "dataset_key")
        if (
            dataset_key["platform"] != platform_urn
            or dataset_key["origin"] not in _DATASET_ORIGINS
            or not _text(dataset_key["name"], f"asset[{index}].dataset_key.name")
            or urn
            != f"urn:li:dataset:({platform_urn},{dataset_key['name']},{dataset_key['origin']})"
        ):
            raise SemanticMetadataError("dataset_key must exactly identify its dataset URN")
        _text(asset["schema_name"], f"asset[{index}].schema_name")
        _text(
            asset["datahub_schema_hash"],
            f"asset[{index}].datahub_schema_hash",
        )
        _text(asset["table_type"], f"asset[{index}].table_type")
        if (
            not isinstance(asset["schema_metadata_version"], int)
            or isinstance(asset["schema_metadata_version"], bool)
            or asset["schema_metadata_version"] < 0
        ):
            raise SemanticMetadataError("schema_metadata_version must be a non-negative integer")
        _urn(asset["owner_urn"], "urn:li:corpGroup:", f"asset[{index}].owner_urn")
        _urn(asset["domain_urn"], "urn:li:domain:", f"asset[{index}].domain_urn")
        _urn(
            asset["approved_lifecycle_urn"],
            "urn:li:lifecycleStageType:",
            f"asset[{index}].approved_lifecycle_urn",
        )
        if (
            asset["owner_urn"] not in governance["owners"]
            or asset["domain_urn"] not in governance["domains"]
            or asset["approved_lifecycle_urn"] not in governance["approved_lifecycles"]
        ):
            raise SemanticMetadataError("asset native governance references are undeclared")
        if asset["approval_status"] != "APPROVED" or not isinstance(
            asset["synthetic"], bool
        ):
            raise SemanticMetadataError(
                "assets must be approved and declare exact synthetic provenance"
            )
        entitlements = _mapping(asset["entitlements"], f"{fqn}.entitlements")
        _exact_keys(entitlements, {"roles", "domains"}, f"{fqn}.entitlements")
        roles = _unique_texts(entitlements["roles"], f"{fqn}.entitlements.roles")
        try:
            validate_entitlement_roles(roles)
        except ValueError as error:
            raise SemanticMetadataError(
                f"{fqn} entitlement role is unsupported"
            ) from error
        domains = _unique_texts(entitlements["domains"], f"{fqn}.entitlements.domains")
        if not roles and not domains:
            raise SemanticMetadataError(f"{fqn} entitlements cannot be empty")
        for domain in domains:
            _urn(domain, "urn:li:domain:", f"{fqn}.entitlements.domains")
        if domains and asset["domain_urn"] not in domains:
            raise SemanticMetadataError(
                f"{fqn} entitlement domains must include its native domain"
            )
        if (
            not urn.startswith("urn:li:dataset:")
            or f"({platform_urn}," not in urn
            or fqn.count(".") < 2
            or urn in urns
            or fqn in columns_by_fqn
        ):
            raise SemanticMetadataError("asset URNs and FQNs must be unique physical dataset identifiers")
        urns.add(urn)
        columns = _validate_columns(asset["columns"], fqn)
        grain = _mapping(asset["grain"], f"{fqn}.grain")
        _exact_keys(grain, {"kind", "keys"}, f"{fqn}.grain")
        keys = _unique_texts(grain["keys"], f"{fqn}.grain.keys", non_empty=True)
        if grain.get("kind") not in _GRAIN_KINDS or not set(keys) <= columns:
            raise SemanticMetadataError(f"{fqn} grain is invalid or references unknown columns")
        key_columns = {
            column["name"] for column in asset["columns"] if column["is_part_of_key"]
        }
        if not key_columns <= set(keys):
            raise SemanticMetadataError(f"{fqn} grain removes a physical schema key")
        columns_by_fqn[fqn] = columns
    return columns_by_fqn


def _validate_columns(value: object, fqn: str) -> frozenset[str]:
    columns = _list(value, f"{fqn}.columns", non_empty=True)
    names: list[str] = []
    for index, raw in enumerate(columns):
        column = _mapping(raw, f"{fqn}.columns[{index}]")
        _exact_keys(
            column,
            {
                "name", "native_type", "logical_type", "nullable", "is_part_of_key",
                "role", "description", "ordinal_position",
            },
            f"{fqn}.columns[{index}]",
        )
        names.append(_text(column["name"], f"{fqn}.columns[{index}].name"))
        _text(column["native_type"], f"{fqn}.{names[-1]}.native_type")
        _text(column["description"], f"{fqn}.{names[-1]}.description")
        if (
            column["logical_type"] not in _LOGICAL_TYPES
            or
            not isinstance(column["ordinal_position"], int)
            or isinstance(column["ordinal_position"], bool)
            or column["ordinal_position"] < 1
            or
            not isinstance(column["nullable"], bool)
            or not isinstance(column["is_part_of_key"], bool)
            or column["role"] not in _COLUMN_ROLES
        ):
            raise SemanticMetadataError(f"{fqn}.{names[-1]} has invalid type metadata")
    if len(names) != len(set(names)):
        raise SemanticMetadataError(f"{fqn} column names must be unique")
    ordinals = [column["ordinal_position"] for column in columns]
    if ordinals != list(range(1, len(columns) + 1)):
        raise SemanticMetadataError(f"{fqn} columns must follow exact ordinal order")
    return frozenset(names)


def _validate_parameters(value: object) -> dict[str, tuple[str, str]]:
    contract = _mapping(value, "parameter_contract")
    _exact_keys(contract, {"style", "parameters"}, "parameter_contract")
    if contract["style"] != "named":
        raise SemanticMetadataError("parameter_contract.style must be named")
    result: dict[str, tuple[str, str]] = {}
    for index, raw in enumerate(
        _list(contract["parameters"], "parameters", non_empty=True, limit=128)
    ):
        item = _mapping(raw, f"parameter[{index}]")
        _exact_keys(item, {"name", "type", "scope"}, f"parameter[{index}]")
        name = _identifier(item["name"], f"parameter[{index}].name")
        if name in result or item["type"] not in _PARAMETER_TYPES or item["scope"] not in _PARAMETER_SCOPES:
            raise SemanticMetadataError("parameter definitions must be unique and typed")
        result[name] = (item["type"], item["scope"])
    return result


def _validate_dimensions(
    value: object,
    assets: Mapping[str, frozenset[str]],
    governance: Mapping[str, frozenset[str]],
    metric_term_urns: set[str],
) -> None:
    ids: set[str] = set()
    member_urns = set(metric_term_urns)
    for index, raw in enumerate(_list(value, "dimensions", limit=64)):
        item = _mapping(raw, f"dimension[{index}]")
        base_keys = {"id", "aliases", "definition", "asset_fqn", "column"}
        if set(item) not in {frozenset(base_keys), frozenset(base_keys | {"members"})}:
            raise SemanticMetadataError(
                f"dimension[{index}] keys differ from the canonical contract"
            )
        identifier = _identifier(item["id"], f"dimension[{index}].id")
        _unique_texts(item["aliases"], f"dimension[{index}].aliases", non_empty=True)
        _text(item["definition"], f"dimension[{index}].definition")
        _qualified({"asset_fqn": item["asset_fqn"], "column": item["column"]}, assets, f"dimension[{index}]")
        if identifier in ids:
            raise SemanticMetadataError("dimension ids must be unique")
        ids.add(identifier)
        if "members" in item:
            _validate_dimension_members(
                item["members"],
                identifier,
                governance,
                member_urns,
            )


def _validate_dimension_members(
    value: object,
    dimension_id: str,
    governance: Mapping[str, frozenset[str]],
    observed_urns: set[str],
) -> None:
    """한 저카디널리티 Dimension의 승인 member와 Glossary identity를 검증한다."""

    member_ids: set[str] = set()
    normalized_names: set[str] = set()
    required = {
        "id",
        "urn",
        "name",
        "definition",
        "aliases",
        "canonical_value",
        "version",
        "approval_status",
        "owner_urn",
        "domain_urn",
        "approved_lifecycle_urn",
    }
    for index, raw in enumerate(
        _list(value, f"{dimension_id}.members", non_empty=True, limit=64)
    ):
        context = f"{dimension_id}.members[{index}]"
        member = _mapping(raw, context)
        _exact_keys(member, required, context)
        member_id = _identifier(member["id"], f"{context}.id")
        term_urn = _urn(
            member["urn"], "urn:li:glossaryTerm:", f"{context}.urn"
        )
        name = _text(member["name"], f"{context}.name")
        canonical_value = _text(
            member["canonical_value"], f"{context}.canonical_value"
        )
        aliases = _unique_texts(
            member["aliases"], f"{context}.aliases", non_empty=True, limit=32
        )
        _text(member["definition"], f"{context}.definition")
        _text(member["version"], f"{context}.version")
        owner = _urn(member["owner_urn"], "urn:li:corpGroup:", f"{context}.owner")
        domain = _urn(member["domain_urn"], "urn:li:domain:", f"{context}.domain")
        lifecycle = _urn(
            member["approved_lifecycle_urn"],
            "urn:li:lifecycleStageType:",
            f"{context}.lifecycle",
        )
        normalized_aliases = {
            unicodedata.normalize("NFKC", alias).casefold() for alias in aliases
        }
        if (
            member_id in member_ids
            or term_urn in observed_urns
            or member["approval_status"] != "APPROVED"
            or owner not in governance["owners"]
            or domain not in governance["domains"]
            or lifecycle not in governance["approved_lifecycles"]
            or unicodedata.normalize("NFKC", name).casefold() not in normalized_aliases
            or unicodedata.normalize("NFKC", canonical_value).casefold()
            not in normalized_aliases
            or normalized_aliases & normalized_names
        ):
            raise SemanticMetadataError(
                "dimension members must be approved, unique, and governance-bound"
            )
        member_ids.add(member_id)
        observed_urns.add(term_urn)
        normalized_names.update(normalized_aliases)


def _validate_joins(value: object, assets: Mapping[str, frozenset[str]]) -> None:
    graph = _mapping(value, "join_graph")
    _exact_keys(graph, {"edges"}, "join_graph")
    ids: set[str] = set()
    for index, raw in enumerate(_list(graph["edges"], "join_graph.edges")):
        edge = _mapping(raw, f"join[{index}]")
        required = {"id", "left", "right", "kind", "cardinality", "equality_conditions", "temporal_conditions", "preaggregation"}
        _exact_keys(edge, required, f"join[{index}]")
        edge_id = _identifier(edge["id"], f"join[{index}].id")
        left, right = str(edge["left"]), str(edge["right"])
        if (
            edge_id in ids
            or left == right
            or left not in assets
            or right not in assets
            or edge["kind"] not in _JOIN_KINDS
            or edge["cardinality"] not in _CARDINALITIES
        ):
            raise SemanticMetadataError("join endpoints, kind, cardinality, and id must be governed")
        ids.add(edge_id)
        conditions = _list(edge["equality_conditions"], f"join[{index}].equality_conditions", non_empty=True)
        for condition in conditions:
            item = _mapping(condition, f"join[{index}].equality")
            _exact_keys(item, {"left_column", "right_column"}, f"join[{index}].equality")
            if item["left_column"] not in assets[left] or item["right_column"] not in assets[right]:
                raise SemanticMetadataError("join equality condition references an unknown column")
        for condition in _list(edge["temporal_conditions"], f"join[{index}].temporal_conditions"):
            item = _mapping(condition, f"join[{index}].temporal")
            required_temporal = {"event_field", "validity_asset_fqn", "valid_from_column", "valid_to_column", "end_exclusive"}
            _exact_keys(item, required_temporal, f"join[{index}].temporal")
            _qualified(item["event_field"], assets, f"join[{index}].temporal.event_field")
            validity = str(item["validity_asset_fqn"])
            if validity not in assets or item["valid_from_column"] not in assets[validity] or item["valid_to_column"] not in assets[validity] or item["end_exclusive"] is not True:
                raise SemanticMetadataError("temporal joins require a governed half-open validity interval")
        preaggregation = _mapping(edge["preaggregation"], f"join[{index}].preaggregation")
        _exact_keys(preaggregation, {"required", "grain", "keys"}, f"join[{index}].preaggregation")
        if not isinstance(preaggregation["required"], bool):
            raise SemanticMetadataError("preaggregation.required must be boolean")
        preaggregation_assets: set[str] = set()
        for name in ("grain", "keys"):
            fields = _list(preaggregation[name], f"join[{index}].preaggregation.{name}", non_empty=True)
            for field in fields:
                asset_fqn, _column = _qualified(
                    field,
                    assets,
                    f"join[{index}].preaggregation.{name}",
                )
                preaggregation_assets.add(asset_fqn)
        if len(preaggregation_assets) != 1:
            raise SemanticMetadataError(
                "join preaggregation fields must target exactly one endpoint"
            )
        many_endpoint = {
            "many_to_one": left,
            "one_to_many": right,
        }.get(str(edge["cardinality"]))
        if (
            preaggregation["required"] is True
            and many_endpoint is not None
            and preaggregation_assets != {many_endpoint}
        ):
            raise SemanticMetadataError(
                "required join preaggregation must target the many endpoint"
            )


def _validate_time_rules(value: object, assets: Mapping[str, frozenset[str]], parameters: Mapping[str, tuple[str, str]]) -> None:
    rules = _mapping(value, "time_rules")
    required = {"timezone", "calendar_id", "interval", "start_parameter", "end_parameter", "fields"}
    _exact_keys(rules, required, "time_rules")
    _text(rules["timezone"], "time_rules.timezone")
    _text(rules["calendar_id"], "time_rules.calendar_id")
    if rules["interval"] != "[start,end)":
        raise SemanticMetadataError("time_rules.interval must be [start,end)")
    start, end = str(rules["start_parameter"]), str(rules["end_parameter"])
    if start == end or any(parameters.get(name, (None, None))[1] != "time" for name in (start, end)):
        raise SemanticMetadataError("time boundaries require two declared time parameters")
    for index, raw in enumerate(_list(rules["fields"], "time_rules.fields", non_empty=True)):
        item = _mapping(raw, f"time_rules.fields[{index}]")
        _exact_keys(item, {"field", "native_type", "bucket", "timezone_mode"}, f"time_rules.fields[{index}]")
        _qualified(item["field"], assets, f"time_rules.fields[{index}].field")
        _text(item["native_type"], f"time_rules.fields[{index}].native_type")
        if item["bucket"] not in _TIME_BUCKETS or item["timezone_mode"] not in _TIMEZONE_MODES:
            raise SemanticMetadataError("time field bucket or timezone mode is unsupported")


def _validate_query_policy(
    value: object,
    assets: Mapping[str, frozenset[str]],
) -> None:
    policy = _mapping(value, "query_policy")
    required = {"dialect", "statement_type", "read_only", "require_limit", "max_limit", "allowed_functions", "allowed_catalogs"}
    _exact_keys(policy, required, "query_policy")
    catalogs = {fqn.split(".", 1)[0] for fqn in assets}
    if policy["dialect"] != "trino" or policy["statement_type"] != "select" or policy["read_only"] is not True or policy["require_limit"] is not True:
        raise SemanticMetadataError("query_policy must require read-only limited Trino SELECT")
    if not isinstance(policy["max_limit"], int) or isinstance(policy["max_limit"], bool) or policy["max_limit"] < 1:
        raise SemanticMetadataError("query_policy.max_limit must be positive")
    _unique_texts(policy["allowed_functions"], "query_policy.allowed_functions")
    if set(_unique_texts(policy["allowed_catalogs"], "query_policy.allowed_catalogs", non_empty=True)) != catalogs:
        raise SemanticMetadataError("query_policy.allowed_catalogs must exactly match schema assets")


def validate_metric_query_policy(bundle: Mapping[str, Any]) -> None:
    """새 authoring 후보의 함수 허용 범위가 Metric 계산식을 완전히 포함하는지 검사한다.

    과거 live release readback에는 소급하지 않는다. 따라서 모순된 predecessor를 읽어
    고친 successor를 만들 수는 있지만, 새 후보가 같은 모순을 반복해 발행되지는 않는다.
    """
    policy = _mapping(bundle.get("query_policy"), "query_policy")
    metrics = [
        _mapping(item, "metric rule")
        for item in _list(bundle.get("metric_rules"), "metric_rules", non_empty=True)
    ]
    allowed_functions = {
        item.casefold()
        for item in _unique_texts(
            policy.get("allowed_functions"), "query_policy.allowed_functions"
        )
    }
    aggregation_functions = {
        "sum": "sum",
        "count": "count",
        "count_distinct": "count",
        "min": "min",
        "max": "max",
        "average": "avg",
    }
    required_functions = {
        function
        for metric in metrics
        for function in (aggregation_functions.get(str(metric["aggregation"])),)
        if function is not None
    }
    if any(
        _mapping(metric["source"], "metric source").get("kind") == "ratio"
        for metric in metrics
    ):
        required_functions.add("nullif")
    if not required_functions <= allowed_functions:
        raise SemanticMetadataError(
            "query_policy.allowed_functions does not cover governed Metric calculations"
        )


def _qualified(value: object, assets: Mapping[str, frozenset[str]], context: str) -> tuple[str, str]:
    field = _mapping(value, context)
    _exact_keys(field, {"asset_fqn", "column"}, context)
    asset, column = str(field["asset_fqn"]), str(field["column"])
    if asset not in assets or column not in assets[asset]:
        raise SemanticMetadataError(f"{context} references an unknown physical column")
    return asset, column


def _reject_runtime_values(value: object, path: str = "bundle") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in {"value", "sql", "question", "normalized_question"}:
                raise SemanticMetadataError(f"{path}.{key} is not publication metadata")
            _reject_runtime_values(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_runtime_values(item, f"{path}[{index}]")
