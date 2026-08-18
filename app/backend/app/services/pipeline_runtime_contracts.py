"""runtime discovery metadata만으로 schema·metric·join·time·parameter·query policy 계약을 만들고 불완전하거나 asset별로 다른 정의는 INVALID_METADATA로 거부한다."""

from __future__ import annotations

import json
from typing import Any

from app.services.context_builder import (
    ContextBuildError,
    ContextBuildErrorCode,
    ContextParameterBinding,
)
from app.services.pipeline_context_contract import GovernedJoin


_COLUMN_ROLES = {"identifier", "dimension", "measure", "time", "attribute"}
_GRAIN_KINDS = {"row", "event", "periodic", "aggregate"}
_AGGREGATIONS = {"sum", "count", "count_distinct", "min", "max", "average", "none"}


def schema_columns(schema: object) -> tuple[dict[str, Any], ...]:
    """Trino/DataHub runtime schema의 컬럼 배열을 엄격한 typed tuple로 검증한다.

    각 항목은 허용된 네 필드와 column role만 가져야 하며 이름은 비어 있지 않고 서로
    유일해야 한다. 누락·추가 필드·타입 불일치는 ``ContextBuildError(INVALID_METADATA)``다.
    """
    if not isinstance(schema, dict) or not isinstance(schema.get("columns"), list):
        raise _invalid("Runtime schema must contain columns.")
    columns: list[dict[str, Any]] = []
    for value in schema["columns"]:
        if not isinstance(value, dict) or set(value) != {
            "name",
            "native_type",
            "nullable",
            "role",
        }:
            raise _invalid("Runtime columns require name, native_type, nullable, and role.")
        column = {
            "name": str(value["name"]),
            "native_type": str(value["native_type"]),
            "nullable": value["nullable"],
            "role": str(value["role"]),
        }
        if (
            not column["name"]
            or not column["native_type"]
            or not isinstance(column["nullable"], bool)
            or column["role"] not in _COLUMN_ROLES
        ):
            raise _invalid("Runtime column metadata is invalid.")
        columns.append(column)
    if not columns or len({item["name"] for item in columns}) != len(columns):
        raise _invalid("Runtime schema columns must be non-empty and unique.")
    return tuple(columns)


def build_runtime_contracts(
    package: Any,
    assets: list[dict[str, object]],
    schemas: dict[str, dict[str, Any]],
    context: Any,
) -> tuple[dict[str, Any], tuple[GovernedJoin, ...]]:
    """동적 asset metadata를 package와 대조해 SQL 생성·검증용 runtime 계약을 조립한다.

    schema column drift, asset별 grain·metric·join·time·query policy 불일치와 잘못된 parameter
    참조는 ``ContextBuildError(INVALID_METADATA)``로 거부한다. 반환값은 직렬화 가능한 계약
    사전과 SQL lineage에 재사용할 typed ``GovernedJoin`` tuple이다.
    """
    raw_by_fqn = {str(item["fqn"]): item for item in assets}
    approved = {item.fqn: frozenset(item.columns) for item in package.assets}
    if set(raw_by_fqn) != set(approved):
        raise _invalid("Runtime assets and ContextPackage assets differ.")
    schema_assets = []
    for asset in package.assets:
        raw = raw_by_fqn[asset.fqn]
        columns = schema_columns(schemas[asset.urn])
        if {item["name"] for item in columns} != set(asset.columns):
            raise _invalid("Runtime schema columns changed during Context construction.")
        grain = _grain(raw.get("grain"), approved[asset.fqn])
        schema_assets.append(
            {
                "urn": asset.urn,
                "fqn": asset.fqn,
                "grain": grain,
                "columns": [dict(item) for item in columns],
            }
        )
    metric_rules = _metric_rules(package, raw_by_fqn, approved)
    joins = _joins(package, assets, approved)
    time_rules = _time_rules(package, assets, context, approved)
    query_policy = _common_contract(assets, "query_policy")
    _validate_query_policy(query_policy, approved)
    parameter_contract = _parameter_contract(package, assets)
    return (
        {
            "schema_context": {
                "version": package.context_release,
                "assets": schema_assets,
            },
            "metric_rules": metric_rules,
            "join_graph": {"edges": [item.as_dict() for item in joins]},
            "time_rules": time_rules,
            "parameter_contract": parameter_contract,
            "query_policy": query_policy,
        },
        joins,
    )


def _grain(value: object, columns: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"kind", "keys"}:
        raise _invalid("Runtime asset grain is missing or invalid.")
    keys = value["keys"]
    if (
        str(value["kind"]) not in _GRAIN_KINDS
        or not isinstance(keys, list)
        or not keys
        or len(set(map(str, keys))) != len(keys)
        or not set(map(str, keys)).issubset(columns)
    ):
        raise _invalid("Runtime asset grain references invalid keys.")
    return {"kind": str(value["kind"]), "keys": list(map(str, keys))}


def _metric_rules(
    package: Any,
    raw_by_fqn: dict[str, dict[str, object]],
    approved: dict[str, frozenset[str]],
) -> list[dict[str, Any]]:
    rules = []
    for metric in package.metrics:
        raw_metrics = raw_by_fqn[metric.asset_fqn].get("metrics")
        candidates = [
            item
            for item in raw_metrics
            if isinstance(item, dict) and item.get("id") == metric.id
        ] if isinstance(raw_metrics, (list, tuple)) else []
        if len(candidates) != 1:
            raise _invalid("Resolved metric is missing from runtime discovery metadata.")
        raw = candidates[0]
        dimensions = raw.get("dimensions")
        if not isinstance(dimensions, list):
            raise _invalid("Runtime metric dimensions are missing.")
        qualified_dimensions = [
            _qualified(item, approved) for item in dimensions
        ]
        aggregation = str(metric.aggregation)
        if aggregation not in _AGGREGATIONS or not metric.unit:
            raise _invalid("Runtime metric aggregation or unit is invalid.")
        raw_filters = raw.get("required_filters")
        if not isinstance(raw_filters, list):
            raise _invalid("Runtime metric required_filters are missing.")
        if {
            _raw_filter_key(item)
            for item in raw_filters
            if isinstance(item, dict)
        } != {
            _filter_key(item) for item in metric.required_filters
        }:
            raise _invalid("Runtime metric filters changed during Context construction.")
        rules.append(
            {
                "id": metric.id,
                "source": {
                    "kind": "column",
                    "field": {
                        "asset_fqn": metric.asset_fqn,
                        "column": metric.field,
                    },
                },
                "aggregation": aggregation,
                "result_field": metric.result_field,
                "unit": metric.unit,
                "time_field": {
                    "asset_fqn": metric.asset_fqn,
                    "column": metric.time_field,
                },
                "dimensions": qualified_dimensions,
                "required_filters": [
                    _model_filter(item, metric.asset_fqn, approved)
                    for item in raw_filters
                ],
            }
        )
    return rules


def _joins(
    package: Any,
    assets: list[dict[str, object]],
    approved: dict[str, frozenset[str]],
) -> tuple[GovernedJoin, ...]:
    values: dict[str, GovernedJoin] = {}
    for asset in assets:
        graph = asset.get("join_graph")
        if graph is None and not package.approved_join_ids:
            continue
        if not isinstance(graph, dict) or set(graph) != {"edges"} or not isinstance(graph["edges"], list):
            raise _invalid("Runtime join_graph is missing or invalid.")
        for raw in graph["edges"]:
            join = GovernedJoin.from_mapping(raw, approved_assets=approved)
            previous = values.get(join.id)
            if previous is not None and previous != join:
                raise _invalid("Runtime join_graph contains conflicting edges.")
            values[join.id] = join
    joins = tuple(values[name] for name in sorted(values))
    if {item.id for item in joins} != set(package.approved_join_ids):
        raise _invalid("Approved join IDs and runtime join_graph differ.")
    return joins


def _time_rules(
    package: Any,
    assets: list[dict[str, object]],
    context: Any,
    approved: dict[str, frozenset[str]],
) -> dict[str, Any]:
    metadata = _common_contract(assets, "time_metadata")
    if set(metadata) != {
        "calendar_id",
        "start_parameter",
        "end_parameter",
        "fields",
    } or not isinstance(metadata["fields"], list):
        raise _invalid("Runtime time metadata is missing or invalid.")
    fields = []
    for item in metadata["fields"]:
        if not isinstance(item, dict) or set(item) != {
            "field",
            "native_type",
            "bucket",
            "timezone_mode",
        }:
            raise _invalid("Runtime time field metadata is invalid.")
        field_target = item.get("field")
        if isinstance(field_target, dict) and str(field_target.get("asset_fqn")) in approved:
            fields.append({**item, "field": _qualified(item["field"], approved)})
    required = {
        (metric.asset_fqn, metric.time_field)
        for metric in package.metrics
    }
    actual = {(item["field"]["asset_fqn"], item["field"]["column"]) for item in fields}
    if not required.issubset(actual):
        raise _invalid("Metric time fields are absent from runtime time metadata.")
    return {
        "timezone": context.timezone,
        "calendar_id": str(metadata["calendar_id"]),
        "interval": "[start,end)",
        "start_parameter": str(metadata["start_parameter"]),
        "end_parameter": str(metadata["end_parameter"]),
        "fields": fields,
    }


def _parameter_contract(
    package: Any,
    assets: list[dict[str, object]],
) -> dict[str, Any]:
    start_name, end_name = time_parameter_names(assets)
    time_names = {start_name, end_name}
    filter_names = {item.name for item in filter_parameter_bindings(assets)}
    parameters = []
    for item in package.parameter_bindings:
        scope = "time" if item.name in time_names else "filter" if item.name in filter_names else None
        if scope is None:
            raise _invalid("Runtime parameter scope is not governed.")
        parameters.append({"name": item.name, "type": item.value_type, "scope": scope})
    return {"style": "named", "parameters": parameters}


def _filter_key(item: Any) -> tuple[str, str, str, object]:
    return item.field, item.operator, item.value_type, item.value


def _raw_filter_key(item: dict[str, Any]) -> tuple[str, str, str, object]:
    required = {"field", "operator", "value_type", "value", "parameter"}
    if set(item) != required or not isinstance(item.get("parameter"), str) or not item["parameter"]:
        raise _invalid("Runtime required filter parameter contract is invalid.")
    return str(item["field"]), str(item["operator"]), str(item["value_type"]), item["value"]


def _model_filter(
    item: object,
    asset_fqn: str,
    approved: dict[str, frozenset[str]],
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise _invalid("Runtime required filter is invalid.")
    _raw_filter_key(item)
    if str(item["field"]) not in approved[asset_fqn]:
        raise _invalid("Runtime required filter is outside schema_context.")
    return {
        "field": {"asset_fqn": asset_fqn, "column": str(item["field"])},
        "operator": str(item["operator"]),
        "parameter": str(item["parameter"]),
    }


def time_parameter_names(assets: list[dict[str, object]]) -> tuple[str, str]:
    """모든 runtime asset이 공유하는 시간 계약에서 시작·종료 parameter 이름을 읽는다.

    asset별 metadata가 다르면 공통 계약 검증이 실패하고, 이름 누락이나 동일 이름 사용은
    ``ContextBuildError(INVALID_METADATA)``로 거부해 기간 바인딩이 뒤바뀌는 것을 막는다.
    """
    metadata = _common_contract(assets, "time_metadata")
    start = str(metadata.get("start_parameter") or "")
    end = str(metadata.get("end_parameter") or "")
    if not start or not end or start == end:
        raise _invalid("Runtime time parameter names are invalid.")
    return start, end


def filter_parameter_bindings(
    assets: list[dict[str, object]],
) -> tuple[ContextParameterBinding, ...]:
    """파라미터 bindings 입력에서 계약 조건을 만족하는 항목만 결정론적으로 추출한다."""
    values: dict[str, ContextParameterBinding] = {}
    for asset in assets:
        collections = [asset.get("required_filters", ())]
        metrics = asset.get("metrics", ())
        if isinstance(metrics, (list, tuple)):
            collections.extend(
                item.get("required_filters", ())
                for item in metrics
                if isinstance(item, dict)
            )
        for collection in collections:
            if not isinstance(collection, (list, tuple)):
                raise _invalid("Runtime required filters must be arrays.")
            for item in collection:
                if not isinstance(item, dict):
                    raise _invalid("Runtime required filter is invalid.")
                _raw_filter_key(item)
                binding = ContextParameterBinding(
                    str(item["parameter"]),
                    str(item["value_type"]),
                    item["value"],
                )
                previous = values.get(binding.name)
                if previous is not None and previous != binding:
                    raise _invalid("Runtime filter parameter definitions conflict.")
                values[binding.name] = binding
    return tuple(values[name] for name in sorted(values))


def _qualified(value: object, approved: dict[str, frozenset[str]]) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"asset_fqn", "column"}:
        raise _invalid("Runtime qualified field is invalid.")
    asset, column = str(value["asset_fqn"]), str(value["column"])
    if asset not in approved or column not in approved[asset]:
        raise _invalid("Runtime qualified field is outside schema_context.")
    return {"asset_fqn": asset, "column": column}


def _common_contract(assets: list[dict[str, object]], name: str) -> dict[str, Any]:
    values = [item.get(name) for item in assets if item.get(name) is not None]
    if not values:
        raise _invalid(f"Runtime {name} contract is missing.")
    canonical = {json.dumps(item, sort_keys=True, separators=(",", ":")) for item in values}
    if len(canonical) != 1 or len(values) != len(assets) or not isinstance(values[0], dict):
        raise _invalid(f"Runtime assets do not share one {name} contract.")
    return json.loads(next(iter(canonical)))


def _validate_query_policy(
    value: dict[str, Any],
    approved: dict[str, frozenset[str]],
) -> None:
    required = {
        "dialect",
        "statement_type",
        "read_only",
        "require_limit",
        "max_limit",
        "allowed_functions",
        "allowed_catalogs",
    }
    catalogs = {name.split(".", 1)[0] for name in approved}
    allowed = set(map(str, value.get("allowed_catalogs", ())))
    if (
        set(value) != required
        or value["dialect"] != "trino"
        or value["statement_type"] != "select"
        or value["read_only"] is not True
        or value["require_limit"] is not True
        or not isinstance(value["max_limit"], int)
        or value["max_limit"] < 1
        or not isinstance(value["allowed_functions"], list)
        or not catalogs.issubset(allowed)
    ):
        raise _invalid("Runtime query_policy is invalid for schema_context.")


def _invalid(message: str) -> ContextBuildError:
    return ContextBuildError(ContextBuildErrorCode.INVALID_METADATA, message)
