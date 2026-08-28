"""v1/v2 Metric Rule read-back과 Dataset-local 실행 projection을 엄격히 결합한다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.adapters.datahub_contract_values import qualified_fields
from app.adapters.datahub_metadata_values import (
    GovernedMetadataError,
    clone_mapping,
    fqn,
    identifier,
    required_text,
    string_set,
)
from app.authorization import role_is_entitled
from app.services.context.values import FILTER_OPERATORS
from src.data.governance_contract import canonical_json, ratio_operand_ids
from src.data.metric_governance import (
    METRIC_RULE_KEYS_V2,
    METRIC_VISIBILITIES,
    QUERY_STRATEGIES,
    RUNTIME_GOVERNANCE_VERSION_V1,
    RUNTIME_GOVERNANCE_VERSION_V2,
    metric_contract_version,
)


_AGGREGATIONS = {
    "sum",
    "count",
    "count_distinct",
    "min",
    "max",
    "average",
    "none",
    "ratio",
}
_REDUCTIONS = {"sum", "min", "max", "average", "scalar", "ratio"}


def parse_release_metric_rules(
    values: object,
    contract_version: str,
) -> tuple[dict[str, Any], ...]:
    """v2 Dataset에 복제된 전체 Rule registry를 형식·참조까지 검증한다."""

    if contract_version == RUNTIME_GOVERNANCE_VERSION_V1:
        if values is not None:
            raise GovernedMetadataError("v1 datasets cannot publish a v2 metric registry")
        return ()
    if contract_version != RUNTIME_GOVERNANCE_VERSION_V2:
        raise GovernedMetadataError("DataHub runtime governance version is unsupported")
    if (
        not isinstance(values, list)
        or not values
        or len(values) > 64
        or any(not isinstance(item, dict) for item in values)
    ):
        raise GovernedMetadataError("DataHub metric rule registry must be bounded")
    try:
        version = metric_contract_version(values)
    except ValueError as error:
        raise GovernedMetadataError("DataHub metric rule versions are invalid") from error
    if version != contract_version:
        raise GovernedMetadataError("DataHub metric rule version differs from dataset")
    rules = [_metric_rule(item) for item in values]
    ids = [item["id"] for item in rules]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise GovernedMetadataError("DataHub metric rule ids must be unique and sorted")
    by_id = {item["id"]: item for item in rules}
    for rule in rules:
        if rule["source"]["kind"] == "ratio":
            _validate_ratio(rule, by_id)
    return tuple(rules)


def parse_runtime_metrics(
    values: object,
    *,
    columns: tuple[dict[str, Any], ...],
    field_terms: Mapping[str, frozenset[str]],
    dataset_terms: frozenset[str],
    parameters: Mapping[str, Any],
    contract_version: str,
    metric_rules: tuple[dict[str, Any], ...],
    asset_fqn: str,
    allowed_roles: frozenset[str],
    grain: Mapping[str, Any],
    synthetic: bool,
    time_rules: Mapping[str, Any],
    join_graph: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Dataset-local executable projection을 full Rule 및 물리 정책과 정확히 대조한다."""

    if not isinstance(values, list) or len(values) > 64:
        raise GovernedMetadataError("DataHub metrics must be a bounded array")
    rules_by_id = {item["id"]: item for item in metric_rules}
    parameter_types = {
        item["name"]: (item["type"], item["scope"])
        for item in parameters["parameters"]
    }
    column_names = {item["name"] for item in columns}
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    required = {
        "id",
        "term_urn",
        "field",
        "aggregation",
        "time_field",
        "result_field",
        "reduction",
        "dimensions",
        "required_filters",
    }
    for raw in values:
        if not isinstance(raw, dict) or set(raw) != required:
            raise GovernedMetadataError("DataHub metric fields are invalid")
        metric_id = identifier(raw["id"], "metric id")
        field = required_text(raw["field"], "metric field")
        time_field = required_text(raw["time_field"], "metric time field")
        term_urn = raw["term_urn"]
        if term_urn is not None:
            term_urn = required_text(term_urn, "metric term urn")
        visible_field_terms = field_terms.get(field, frozenset())
        if (
            metric_id in ids
            or field not in column_names
            or time_field not in column_names
            or raw["aggregation"] not in _AGGREGATIONS - {"ratio"}
            or raw["reduction"] not in _REDUCTIONS - {"ratio"}
        ):
            raise GovernedMetadataError("DataHub metric governance is inconsistent")
        dimensions = qualified_fields(raw["dimensions"], "metric dimensions")
        filters = _filter_contracts(
            raw["required_filters"], column_names, parameter_types
        )
        metric = {
            "id": metric_id,
            "term_urn": term_urn,
            "field": field,
            "aggregation": raw["aggregation"],
            "time_field": time_field,
            "result_field": identifier(raw["result_field"], "metric result field"),
            "reduction": raw["reduction"],
            "dimensions": dimensions,
            "required_filters": filters,
        }
        if contract_version == RUNTIME_GOVERNANCE_VERSION_V1:
            _validate_v1_term(metric, dataset_terms, visible_field_terms)
            metric.update(_legacy_policy())
        else:
            rule = rules_by_id.get(metric_id)
            if rule is None:
                raise GovernedMetadataError("DataHub local metric is absent from v2 registry")
            metric.update(
                _bind_v2_policy(
                    metric,
                    rule,
                    asset_fqn=asset_fqn,
                    dataset_terms=dataset_terms,
                    visible_field_terms=visible_field_terms,
                    allowed_roles=allowed_roles,
                    grain=grain,
                    synthetic=synthetic,
                    time_rules=time_rules,
                    join_graph=join_graph,
                )
            )
        ids.add(metric_id)
        result.append(metric)
    if contract_version == RUNTIME_GOVERNANCE_VERSION_V2:
        expected = {
            item["id"]
            for item in metric_rules
            if item["source"].get("kind") == "column"
            and item["source"]["field"].get("asset_fqn") == asset_fqn
        }
        if ids != expected:
            raise GovernedMetadataError(
                "DataHub local metrics do not cover v2 source rules"
            )
    return tuple(result)


def runtime_metric_permitted(metric: Mapping[str, Any], role: str) -> bool:
    """v2 Metric permission metadata만으로 요청 role과 PII 차단 여부를 결정한다.

    v1은 Metric별 role·PII 계약이 없으므로 읽기 호환성만 유지하고 Production 실행은
    열지 않는다. 신규 v2 release가 활성화되기 전까지 분석은 fail-closed한다.
    """

    if metric.get("governance_version") != RUNTIME_GOVERNANCE_VERSION_V2:
        return False
    roles = metric.get("allowed_roles")
    return (
        isinstance(roles, tuple)
        and role_is_entitled(role, roles)
        and metric.get("contains_pii") is False
    )


def runtime_metric_policy(rule: Mapping[str, Any]) -> dict[str, Any]:
    """검증된 full Rule에서 런타임 집행 필드만 추출하며 v1은 기존 동작을 보존한다."""

    governance = rule.get("governance")
    if not isinstance(governance, Mapping):
        legacy = _legacy_policy()
        legacy.pop("metric_rule")
        legacy["unit"] = str(rule.get("unit") or "")
        return legacy
    permission = governance["permission"]
    join = governance["join"]
    return {
        "unit": str(rule["unit"]),
        "visibility": str(governance["visibility"]),
        "governance_version": RUNTIME_GOVERNANCE_VERSION_V2,
        "allowed_roles": tuple(sorted(map(str, permission["roles"]))),
        "contains_pii": permission["contains_pii"],
        "allowed_join_ids": tuple(sorted(map(str, join["allowed_edge_ids"]))),
        "join_required": join["required"],
        "query_strategies": tuple(sorted(map(str, governance["query_strategies"]))),
    }


def _metric_rule(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != set(METRIC_RULE_KEYS_V2):
        raise GovernedMetadataError("DataHub v2 metric rule fields are invalid")
    rule = clone_mapping(value)
    metric_id = identifier(rule["id"], "metric rule id")
    rule["id"] = metric_id
    identifier(rule["result_field"], "metric result field")
    required_text(rule["unit"], "metric unit")
    if rule["aggregation"] not in _AGGREGATIONS or rule["reduction"] not in _REDUCTIONS:
        raise GovernedMetadataError("DataHub metric operation is unsupported")
    source = rule["source"]
    if not isinstance(source, dict):
        raise GovernedMetadataError("DataHub metric source is invalid")
    if source.get("kind") == "column":
        _column_rule(rule, source)
    elif source.get("kind") == "ratio":
        _ratio_shape(rule, source)
    else:
        raise GovernedMetadataError("DataHub metric source kind is unsupported")
    _governance(rule)
    return rule


def _column_rule(rule: dict[str, Any], source: dict[str, Any]) -> None:
    if set(source) != {"kind", "field"} or rule["aggregation"] == "ratio":
        raise GovernedMetadataError("DataHub column metric source is invalid")
    source_field = _field(source["field"], "metric source field")
    time_field = _field(rule["time_field"], "metric time field")
    if source_field["asset_fqn"] != time_field["asset_fqn"]:
        raise GovernedMetadataError("DataHub metric time field has another source")
    qualified_fields(rule["dimensions"], "metric dimensions")
    raw_filters = rule["required_filters"]
    if not isinstance(raw_filters, list) or len(raw_filters) > 32:
        raise GovernedMetadataError("DataHub metric filters must be bounded")
    for item in raw_filters:
        if not isinstance(item, dict) or set(item) != {"field", "operator", "parameter"}:
            raise GovernedMetadataError("DataHub metric filter is invalid")
        field = _field(item["field"], "metric filter field")
        if field["asset_fqn"] != source_field["asset_fqn"]:
            raise GovernedMetadataError("DataHub metric filter has another source")
        if item["operator"] not in FILTER_OPERATORS:
            raise GovernedMetadataError("DataHub metric filter operator is invalid")
        required_text(item["parameter"], "metric filter parameter")


def _ratio_shape(rule: dict[str, Any], source: dict[str, Any]) -> None:
    required = {
        "kind",
        "numerator_metric_id",
        "denominator_metric_id",
        "zero_policy",
    }
    if (
        set(source) != required
        or ratio_operand_ids(rule) is None
        or source.get("zero_policy") != "null_on_zero_denominator"
        or rule["aggregation"] != "ratio"
        or rule["reduction"] != "ratio"
        or rule["time_field"] is not None
        or rule["dimensions"] != []
        or rule["required_filters"] != []
    ):
        raise GovernedMetadataError("DataHub ratio metric shape is invalid")


def _governance(rule: dict[str, Any]) -> None:
    value = rule["governance"]
    required = {
        "visibility",
        "semantic",
        "grain",
        "time",
        "join",
        "permission",
        "query_strategies",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise GovernedMetadataError("DataHub metric governance fields are invalid")
    if value["visibility"] not in METRIC_VISIBILITIES:
        raise GovernedMetadataError("DataHub metric visibility is invalid")
    semantic = value["semantic"]
    if not isinstance(semantic, dict) or set(semantic) != {"name", "definition", "aliases"}:
        raise GovernedMetadataError("DataHub metric semantics are invalid")
    name = required_text(semantic["name"], "metric semantic name")
    required_text(semantic["definition"], "metric semantic definition")
    aliases = string_set(semantic["aliases"], "metric semantic aliases")
    if not aliases or name not in aliases:
        raise GovernedMetadataError("DataHub metric semantic aliases are incomplete")
    grain = value["grain"]
    if not isinstance(grain, dict) or set(grain) != {"kind", "keys", "dimensions"}:
        raise GovernedMetadataError("DataHub metric grain is invalid")
    required_text(grain["kind"], "metric grain kind")
    if not string_set(grain["keys"], "metric grain keys"):
        raise GovernedMetadataError("DataHub metric grain keys are empty")
    string_set(grain["dimensions"], "metric grain dimensions")
    time = value["time"]
    if not isinstance(time, dict) or set(time) != {"field", "semantics", "timezone", "interval"}:
        raise GovernedMetadataError("DataHub metric time governance is invalid")
    for key in ("field", "semantics", "timezone"):
        required_text(time[key], f"metric time {key}")
    if time["interval"] != "[start,end)":
        raise GovernedMetadataError("DataHub metric interval is not half-open")
    join = value["join"]
    if not isinstance(join, dict) or set(join) != {"required", "allowed_edge_ids"}:
        raise GovernedMetadataError("DataHub metric join governance is invalid")
    edges = string_set(join["allowed_edge_ids"], "metric allowed join ids")
    if not isinstance(join["required"], bool) or (join["required"] and not edges):
        raise GovernedMetadataError("DataHub metric join requirement is inconsistent")
    permission = value["permission"]
    if not isinstance(permission, dict) or set(permission) != {"roles", "contains_pii", "synthetic"}:
        raise GovernedMetadataError("DataHub metric permission is invalid")
    if (
        not string_set(permission["roles"], "metric permission roles")
        or not isinstance(permission["contains_pii"], bool)
        or not isinstance(permission["synthetic"], bool)
    ):
        raise GovernedMetadataError("DataHub metric permission values are invalid")
    strategies = string_set(value["query_strategies"], "metric query strategies")
    if not strategies or not strategies <= QUERY_STRATEGIES:
        raise GovernedMetadataError("DataHub metric query strategy is invalid")
    if rule["source"]["kind"] == "column":
        source_asset = str(rule["source"]["field"]["asset_fqn"])
        dimensions = {
            item["column"]
            for item in rule["dimensions"]
            if item["asset_fqn"] == source_asset
        }
        if (
            time["field"] != rule["time_field"]["column"]
            or set(grain["dimensions"]) != dimensions
        ):
            raise GovernedMetadataError("DataHub metric executable scope differs")


def _validate_ratio(rule: dict[str, Any], rules: Mapping[str, dict[str, Any]]) -> None:
    operands = ratio_operand_ids(rule)
    numerator, denominator = (rules.get(item) for item in (operands or (None, None)))
    if (
        operands is None
        or numerator is None
        or denominator is None
        or numerator["source"]["kind"] != "column"
        or denominator["source"]["kind"] != "column"
        or numerator["source"]["field"]["asset_fqn"]
        != denominator["source"]["field"]["asset_fqn"]
        or any(
            numerator[key] != denominator[key]
            for key in ("time_field", "dimensions", "required_filters")
        )
        or any(
            rule["governance"][key] != numerator["governance"][key]
            or rule["governance"][key] != denominator["governance"][key]
            for key in ("grain", "time", "join", "permission", "query_strategies")
        )
    ):
        raise GovernedMetadataError("DataHub ratio operands have another scope")


def _bind_v2_policy(
    metric: dict[str, Any],
    rule: dict[str, Any],
    **scope: Any,
) -> dict[str, Any]:
    asset_fqn = scope["asset_fqn"]
    executable = {
        "id": metric["id"],
        "source": {
            "kind": "column",
            "field": {"asset_fqn": asset_fqn, "column": metric["field"]},
        },
        "aggregation": metric["aggregation"],
        "result_field": metric["result_field"],
        "unit": rule["unit"],
        "time_field": {"asset_fqn": asset_fqn, "column": metric["time_field"]},
        "reduction": metric["reduction"],
        "dimensions": metric["dimensions"],
        "required_filters": [
            {
                "field": {"asset_fqn": asset_fqn, "column": item["field"]},
                "operator": item["operator"],
                "parameter": item["parameter"],
            }
            for item in metric["required_filters"]
        ],
        "governance": rule["governance"],
    }
    if canonical_json(executable) != canonical_json(rule):
        raise GovernedMetadataError("DataHub local metric differs from its v2 rule")
    governance = rule["governance"]
    permission = governance["permission"]
    join = governance["join"]
    term_urn = metric["term_urn"]
    visibility = governance["visibility"]
    if visibility == "BUSINESS":
        _validate_v1_term(
            metric,
            scope["dataset_terms"],
            scope["visible_field_terms"],
            require_field_term=True,
        )
    elif term_urn is not None:
        raise GovernedMetadataError("DataHub support metric cannot have a Glossary term")
    edge_index = {
        item.get("id"): item
        for item in scope["join_graph"].get("edges", ())
        if isinstance(item, dict)
    }
    if (
        not set(permission["roles"]).issubset(scope["allowed_roles"])
        or permission["synthetic"] is not scope["synthetic"]
        or governance["grain"]["kind"] != scope["grain"]["kind"]
        or set(governance["grain"]["keys"]) != set(scope["grain"]["keys"])
        or governance["time"]["timezone"] != scope["time_rules"]["timezone"]
        or not any(
            item.get("field")
            == {"asset_fqn": asset_fqn, "column": governance["time"]["field"]}
            for item in scope["time_rules"].get("fields", ())
            if isinstance(item, dict)
        )
    ):
        raise GovernedMetadataError("DataHub metric policy exceeds its source asset")
    for edge_id in join["allowed_edge_ids"]:
        edge = edge_index.get(edge_id)
        if edge is None or asset_fqn not in {edge.get("left"), edge.get("right")}:
            raise GovernedMetadataError("DataHub metric join policy is outside its source")
    return {
        **runtime_metric_policy(rule),
        "metric_rule": clone_mapping(rule),
    }


def _validate_v1_term(
    metric: Mapping[str, Any],
    dataset_terms: frozenset[str],
    visible_field_terms: frozenset[str],
    *,
    require_field_term: bool = False,
) -> None:
    term_urn = metric.get("term_urn")
    if (
        not isinstance(term_urn, str)
        or term_urn not in dataset_terms
        or (
            term_urn not in visible_field_terms
            if require_field_term
            else visible_field_terms and term_urn not in visible_field_terms
        )
    ):
        raise GovernedMetadataError("DataHub metric governance is inconsistent")


def _legacy_policy() -> dict[str, Any]:
    return {
        "unit": "",
        "visibility": "BUSINESS",
        "governance_version": RUNTIME_GOVERNANCE_VERSION_V1,
        "allowed_roles": (),
        "contains_pii": False,
        "allowed_join_ids": (),
        "join_required": False,
        "query_strategies": (),
        "metric_rule": None,
    }


def _filter_contracts(values: object, columns: set[str], parameters: Mapping[str, Any]):
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


def _field(value: object, context: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"asset_fqn", "column"}:
        raise GovernedMetadataError(f"DataHub {context} is invalid")
    return {
        "asset_fqn": fqn(value["asset_fqn"]),
        "column": required_text(value["column"], f"{context} column"),
    }
