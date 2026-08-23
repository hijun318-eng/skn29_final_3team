"""DataHub semantic publication의 column·derived ratio metric 계약을 검증한다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from metadata_contract_primitives import (
    SemanticMetadataError,
    array,
    exact_keys,
    identifier,
    mapping,
    text,
    unique_texts,
)
from src.data.governance_contract import RATIO_ZERO_POLICIES
from src.data.metric_governance import (
    METRIC_RULE_KEYS_V1,
    METRIC_RULE_KEYS_V2,
    METRIC_VISIBILITIES,
    QUERY_STRATEGIES,
    RUNTIME_GOVERNANCE_VERSION_V2,
    metric_rule_contract_version,
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
_FILTER_OPERATORS = {"eq", "neq", "gt", "gte", "lt", "lte"}
def validate_metrics(
    value: object,
    assets: Mapping[str, frozenset[str]],
    parameters: Mapping[str, tuple[str, str]],
    asset_domains: Mapping[str, str],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    """Metric 전체를 먼저 구조 검증하고 ratio 참조·domain·계산 범위를 두 번째 단계에서 고정한다."""

    metrics: dict[str, Mapping[str, Any]] = {}
    domains: dict[str, str] = {}
    versions: set[str] = set()
    for index, raw in enumerate(array(value, "metric_rules", non_empty=True, limit=64)):
        metric = mapping(raw, f"metric[{index}]")
        try:
            version = metric_rule_contract_version(metric)
        except ValueError as error:
            raise SemanticMetadataError(str(error)) from error
        versions.add(version)
        exact_keys(
            metric,
            set(METRIC_RULE_KEYS_V2 if version == RUNTIME_GOVERNANCE_VERSION_V2 else METRIC_RULE_KEYS_V1),
            f"metric[{index}]",
        )
        metric_id = identifier(metric["id"], f"metric[{index}].id")
        if metric_id in metrics:
            raise SemanticMetadataError("metric ids must be unique")
        identifier(metric["result_field"], f"metric[{index}].result_field")
        text(metric["unit"], f"metric[{index}].unit")
        if (
            metric["aggregation"] not in _AGGREGATIONS
            or metric["reduction"] not in _REDUCTIONS
        ):
            raise SemanticMetadataError("metric aggregation or reduction is unsupported")
        source = mapping(metric["source"], f"metric[{index}].source")
        kind = source.get("kind")
        if kind == "column":
            source_asset = _validate_column_metric(
                metric,
                source,
                assets,
                parameters,
                f"metric[{index}]",
            )
            domains[metric_id] = asset_domains[source_asset]
        elif kind == "ratio":
            _validate_ratio_shape(metric, source, f"metric[{index}]")
        else:
            raise SemanticMetadataError("only column and governed ratio metrics are supported")
        if version == RUNTIME_GOVERNANCE_VERSION_V2:
            _validate_v2_governance(metric, f"metric[{index}]")
        metrics[metric_id] = metric

    if len(versions) != 1:
        raise SemanticMetadataError(
            "one semantic release cannot mix metric governance versions"
        )

    for metric_id, metric in metrics.items():
        if mapping(metric["source"], f"metric[{metric_id}].source").get("kind") != "ratio":
            continue
        domains[metric_id] = _validate_ratio_references(metric, metrics, domains)
    return metrics, domains


def _validate_v2_governance(metric: Mapping[str, Any], context: str) -> None:
    """v2의 업무 의미·권한·실행 제한 shape를 물리 교차검증 전에 엄격히 확인한다."""

    governance = mapping(metric["governance"], f"{context}.governance")
    exact_keys(
        governance,
        {
            "visibility",
            "semantic",
            "grain",
            "time",
            "join",
            "permission",
            "query_strategies",
        },
        f"{context}.governance",
    )
    if governance["visibility"] not in METRIC_VISIBILITIES:
        raise SemanticMetadataError("metric visibility is unsupported")
    semantic = mapping(governance["semantic"], f"{context}.governance.semantic")
    exact_keys(
        semantic,
        {"name", "definition", "aliases"},
        f"{context}.governance.semantic",
    )
    name = text(semantic["name"], f"{context}.governance.semantic.name")
    aliases = unique_texts(
        semantic["aliases"],
        f"{context}.governance.semantic.aliases",
        non_empty=True,
    )
    text(semantic["definition"], f"{context}.governance.semantic.definition")
    if name not in aliases:
        raise SemanticMetadataError("metric semantic aliases must include its name")

    grain = mapping(governance["grain"], f"{context}.governance.grain")
    exact_keys(grain, {"kind", "keys", "dimensions"}, f"{context}.governance.grain")
    text(grain["kind"], f"{context}.governance.grain.kind")
    unique_texts(grain["keys"], f"{context}.governance.grain.keys", non_empty=True)
    dimensions = unique_texts(
        grain["dimensions"], f"{context}.governance.grain.dimensions"
    )

    time = mapping(governance["time"], f"{context}.governance.time")
    exact_keys(
        time,
        {"field", "semantics", "timezone", "interval"},
        f"{context}.governance.time",
    )
    for key in ("field", "semantics", "timezone"):
        text(time[key], f"{context}.governance.time.{key}")
    if time["interval"] != "[start,end)":
        raise SemanticMetadataError("metric time interval must be half-open")

    join = mapping(governance["join"], f"{context}.governance.join")
    exact_keys(join, {"required", "allowed_edge_ids"}, f"{context}.governance.join")
    edges = unique_texts(
        join["allowed_edge_ids"], f"{context}.governance.join.allowed_edge_ids"
    )
    if not isinstance(join["required"], bool) or (join["required"] and not edges):
        raise SemanticMetadataError("metric join requirement and allowed edges disagree")

    permission = mapping(
        governance["permission"], f"{context}.governance.permission"
    )
    exact_keys(
        permission,
        {"roles", "contains_pii", "synthetic"},
        f"{context}.governance.permission",
    )
    unique_texts(
        permission["roles"], f"{context}.governance.permission.roles", non_empty=True
    )
    if not isinstance(permission["contains_pii"], bool) or not isinstance(
        permission["synthetic"], bool
    ):
        raise SemanticMetadataError("metric permission flags must be boolean")
    strategies = set(
        unique_texts(
            governance["query_strategies"],
            f"{context}.governance.query_strategies",
            non_empty=True,
        )
    )
    if not strategies <= QUERY_STRATEGIES:
        raise SemanticMetadataError("metric query strategy is unsupported")

    if metric["source"].get("kind") == "column":
        time_field = mapping(metric["time_field"], f"{context}.time_field")
        if time["field"] != time_field.get("column"):
            raise SemanticMetadataError("metric time governance differs from its executable field")
        source_asset = str(metric["source"]["field"]["asset_fqn"])
        executable_dimensions = {
            str(value.get("column"))
            for item in array(metric["dimensions"], f"{context}.dimensions")
            for value in (mapping(item, f"{context}.dimension"),)
            if value.get("asset_fqn") == source_asset
        }
        if set(dimensions) != executable_dimensions:
            raise SemanticMetadataError("metric grain dimensions differ from executable dimensions")


def _validate_column_metric(
    metric: Mapping[str, Any],
    source: Mapping[str, Any],
    assets: Mapping[str, frozenset[str]],
    parameters: Mapping[str, tuple[str, str]],
    context: str,
) -> str:
    exact_keys(source, {"kind", "field"}, f"{context}.source")
    if metric["aggregation"] == "ratio" or metric["reduction"] == "ratio":
        raise SemanticMetadataError("column metrics cannot use ratio aggregation or reduction")
    source_asset, _source_column = _qualified(
        source["field"], assets, f"{context}.source.field"
    )
    if metric["time_field"] is None:
        raise SemanticMetadataError("published column metrics require a governed time field")
    time_asset, _time_column = _qualified(
        metric["time_field"], assets, f"{context}.time_field"
    )
    if time_asset != source_asset:
        raise SemanticMetadataError("metric time fields must belong to the source asset")
    for dimension in array(metric["dimensions"], f"{context}.dimensions", limit=64):
        _qualified(dimension, assets, f"{context}.dimension")
    for raw_filter in array(
        metric["required_filters"], f"{context}.required_filters", limit=32
    ):
        item = mapping(raw_filter, f"{context}.filter")
        exact_keys(item, {"field", "operator", "parameter"}, f"{context}.filter")
        filter_asset, _filter_column = _qualified(
            item["field"], assets, f"{context}.filter.field"
        )
        name = text(item["parameter"], f"{context}.filter.parameter")
        if (
            filter_asset != source_asset
            or item["operator"] not in _FILTER_OPERATORS
            or parameters.get(name, (None, None))[1] != "filter"
        ):
            raise SemanticMetadataError(
                "metric filters require declared scalar filter parameters"
            )
    return source_asset


def _validate_ratio_shape(
    metric: Mapping[str, Any], source: Mapping[str, Any], context: str
) -> None:
    exact_keys(
        source,
        {
            "kind",
            "numerator_metric_id",
            "denominator_metric_id",
            "zero_policy",
        },
        f"{context}.source",
    )
    numerator = identifier(
        source["numerator_metric_id"], f"{context}.source.numerator_metric_id"
    )
    denominator = identifier(
        source["denominator_metric_id"], f"{context}.source.denominator_metric_id"
    )
    if (
        numerator == denominator
        or source["zero_policy"] not in RATIO_ZERO_POLICIES
        or metric["aggregation"] != "ratio"
        or metric["reduction"] != "ratio"
        or metric["time_field"] is not None
        or metric["dimensions"] != []
        or metric["required_filters"] != []
    ):
        raise SemanticMetadataError(
            "ratio metrics require distinct operands, ratio semantics, and no physical fields"
        )


def _validate_ratio_references(
    metric: Mapping[str, Any],
    metrics: Mapping[str, Mapping[str, Any]],
    domains: Mapping[str, str],
) -> str:
    source = mapping(metric["source"], "ratio metric source")
    numerator_id = str(source["numerator_metric_id"])
    denominator_id = str(source["denominator_metric_id"])
    numerator = metrics.get(numerator_id)
    denominator = metrics.get(denominator_id)
    if numerator is None or denominator is None:
        raise SemanticMetadataError("ratio operands must reference published metrics")
    numerator_source = mapping(numerator["source"], "ratio numerator source")
    denominator_source = mapping(denominator["source"], "ratio denominator source")
    if numerator_source.get("kind") != "column" or denominator_source.get("kind") != "column":
        raise SemanticMetadataError("ratio operands must be executable column metrics")
    numerator_field = mapping(numerator_source["field"], "ratio numerator field")
    denominator_field = mapping(denominator_source["field"], "ratio denominator field")
    # 현재 SQL contract는 같은 계산 범위만 안전하게 나눌 수 있다. Cross-asset ratio는
    # 별도 grain alignment 계약이 생기기 전까지 fail-closed한다.
    if (
        numerator_field.get("asset_fqn") != denominator_field.get("asset_fqn")
        or numerator["time_field"] != denominator["time_field"]
        or numerator["dimensions"] != denominator["dimensions"]
        or numerator["required_filters"] != denominator["required_filters"]
        or domains.get(numerator_id) != domains.get(denominator_id)
    ):
        raise SemanticMetadataError(
            "ratio operands must share one asset, time field, dimensions, filters, and domain"
        )
    return domains[numerator_id]


def _qualified(
    value: object,
    assets: Mapping[str, frozenset[str]],
    context: str,
) -> tuple[str, str]:
    field = mapping(value, context)
    exact_keys(field, {"asset_fqn", "column"}, context)
    asset, column = str(field["asset_fqn"]), str(field["column"])
    if asset not in assets or column not in assets[asset]:
        raise SemanticMetadataError(f"{context} references an unknown physical column")
    return asset, column
