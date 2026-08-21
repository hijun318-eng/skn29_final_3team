"""런타임 스키마/지표/조인/시간/파라미터/쿼리 정책 계약 조립 모듈.

[핵심 목적]
DataHub 등 메타데이터 플랫폼에서 동적으로 조회된 자산 스키마, 지표 계산 규칙, 조인 그래프,
시간 조건 규칙, 파라미터 바인딩 계약 및 읽기 전용 쿼리 정책(Query Policy)을 엄격히 검증하고
단일 직렬화 가능한 `runtime_contracts` 딕셔너리로 합성합니다.

[보안 및 일관성 원칙]
1. 단일 공통 정책 강제: 요청에 포함된 모든 자산이 동일한 `query_policy`와 `time_metadata`를 공유해야 하며, 상충 시 즉각 거부합니다.
2. 스키마 변경(Drift) 방지: 컨텍스트 생성 도중 스키마 컬럼이나 지표 필터 정의가 변경되면 불일치를 감지하고 차단합니다.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.context.builder import (
    ContextBuildError,
    ContextBuildErrorCode,
    ContextParameterBinding,
)
from app.services.context.values import RATIO_ZERO_POLICIES
from app.services.context.contract import GovernedJoin

# 허용된 컬럼 역할, Grain 종류 및 집계 함수 화이트리스트
_COLUMN_ROLES = {"identifier", "dimension", "measure", "time", "attribute"}
_GRAIN_KINDS = {"row", "event", "periodic", "aggregate"}
_AGGREGATIONS = {"sum", "count", "count_distinct", "min", "max", "average", "none", "ratio", "exists"}


def schema_columns(schema: object) -> tuple[dict[str, Any], ...]:
    """런타임 스키마의 컬럼 메타데이터 배열을 엄격히 검증하여 불변 튜플로 반환합니다.

    Args:
        schema: 'columns' 키를 포함하는 스키마 딕셔너리

    Returns:
        검증된 컬럼 메타데이터 튜플 (name, native_type, nullable, role)

    Raises:
        ContextBuildError: 필수 필드 누락, 지원되지 않는 role, 중복 컬럼명 등
    """
    if not isinstance(schema, dict) or not isinstance(schema.get("columns"), list):
        raise _invalid("런타임 스키마는 반드시 columns 목록을 포함해야 합니다.")
    columns: list[dict[str, Any]] = []
    for value in schema["columns"]:
        if not isinstance(value, dict) or set(value) != {
            "name",
            "native_type",
            "nullable",
            "role",
        }:
            raise _invalid("런타임 컬럼은 name, native_type, nullable, role 필드를 모두 포함해야 합니다.")
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
            raise _invalid("런타임 컬럼 메타데이터 값이 유효하지 않습니다.")
        columns.append(column)
    if not columns or len({item["name"] for item in columns}) != len(columns):
        raise _invalid("런타임 스키마 컬럼 목록은 비어있지 않고 고유해야 합니다.")
    return tuple(columns)


def build_runtime_contracts(
    package: Any,
    assets: list[dict[str, object]],
    schemas: dict[str, dict[str, Any]],
    context: Any,
) -> tuple[dict[str, Any], tuple[GovernedJoin, ...]]:
    """동적 자산 메타데이터를 ContextPackage와 대조하여 SQL 생성/가드 검증용 runtime 계약을 조립합니다.

    Args:
        package: ContextPackage 인스턴스
        assets: DataHub에서 조회된 원시 자산 메타데이터 목록
        schemas: 데이터셋 URN별 스키마 딕셔너리
        context: RequestContext 인스턴스

    Returns:
        tuple[조립된 runtime_contracts 딕셔너리, typed GovernedJoin 튜플]
    """
    raw_by_fqn = {str(item["fqn"]): item for item in assets}
    approved = {item.fqn: frozenset(item.columns) for item in package.assets}
    if set(raw_by_fqn) != set(approved):
        raise _invalid("런타임 자산 목록과 ContextPackage 자산 목록이 일치하지 않습니다.")
    schema_assets = []
    for asset in package.assets:
        raw = raw_by_fqn[asset.fqn]
        columns = schema_columns(schemas[asset.urn])
        if {item["name"] for item in columns} != set(asset.columns):
            raise _invalid("컨텍스트 빌드 중 런타임 스키마 컬럼이 변경되었습니다.")
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
        raise _invalid("런타임 자산 grain 정의가 누락되었거나 유효하지 않습니다.")
    keys = value["keys"]
    if (
        str(value["kind"]) not in _GRAIN_KINDS
        or not isinstance(keys, list)
        or not keys
        or len(set(map(str, keys))) != len(keys)
        or not set(map(str, keys)).issubset(columns)
    ):
        raise _invalid("런타임 자산 grain 키가 승인된 컬럼 범위를 벗어납니다.")
    return {"kind": str(value["kind"]), "keys": list(map(str, keys))}


def _metric_rules(
    package: Any,
    raw_by_fqn: dict[str, dict[str, object]],
    approved: dict[str, frozenset[str]],
) -> list[dict[str, Any]]:
    rules = []
    for metric in package.metrics:
        if metric.aggregation.lower() == "ratio":
            rules.append(_ratio_metric_rule(metric))
            continue
        raw_metrics = raw_by_fqn[metric.asset_fqn].get("metrics")
        candidates = [
            item
            for item in raw_metrics
            if isinstance(item, dict) and item.get("id") == metric.id
        ] if isinstance(raw_metrics, (list, tuple)) else []
        if len(candidates) != 1:
            raise _invalid("해결된 지표가 런타임 자산 메타데이터에 존재하지 않습니다.")
        raw = candidates[0]
        dimensions = raw.get("dimensions")
        if not isinstance(dimensions, list):
            raise _invalid("런타임 지표 차원 목록이 누락되었습니다.")
        qualified_dimensions = [
            _qualified(item, approved) for item in dimensions
        ]
        aggregation = str(metric.aggregation)
        if aggregation not in _AGGREGATIONS or not metric.unit:
            raise _invalid("런타임 지표 집계 함수 또는 단위 정의가 올바르지 않습니다.")
        raw_filters = raw.get("required_filters")
        if not isinstance(raw_filters, list):
            raise _invalid("런타임 지표 필수 필터 정의가 누락되었습니다.")
        if {
            _raw_filter_key(item)
            for item in raw_filters
            if isinstance(item, dict)
        } != {
            _filter_key(item) for item in metric.required_filters
        }:
            raise _invalid("컨텍스트 빌드 중 지표 필수 필터 정의가 변경되었습니다.")
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


def _ratio_metric_rule(metric: Any) -> dict[str, Any]:
    """ratio 지표의 런타임 규칙 딕셔너리를 구성합니다."""
    if metric.zero_policy not in RATIO_ZERO_POLICIES:
        raise _invalid("Ratio 지표의 zero_policy가 거버넌스 승인 범위를 벗어납니다.")
    return {
        "id": metric.id,
        "source": {
            "kind": "ratio",
            "numerator_metric_id": metric.numerator_metric_id,
            "denominator_metric_id": metric.denominator_metric_id,
            "zero_policy": metric.zero_policy,
        },
        "aggregation": "ratio",
        "result_field": metric.result_field,
        "unit": metric.unit,
        "time_field": None,
        "dimensions": [],
        "required_filters": [],
    }


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
            raise _invalid("런타임 join_graph가 누락되었거나 형식이 올바르지 않습니다.")
        for raw in graph["edges"]:
            join = GovernedJoin.from_mapping(raw, approved_assets=approved)
            previous = values.get(join.id)
            if previous is not None and previous != join:
                raise _invalid("런타임 join_graph에 상충되는 엣지 정의가 포함되어 있습니다.")
            values[join.id] = join
    joins = tuple(values[name] for name in sorted(values))
    if {item.id for item in joins} != set(package.approved_join_ids):
        raise _invalid("승인된 조인 ID 목록과 런타임 join_graph 엣지 목록이 일치하지 않습니다.")
    return joins


_TIME_METADATA_KEYS = {"calendar_id", "start_parameter", "end_parameter", "fields"}
_TIME_METADATA_KEYS_WITH_COMPARISON = _TIME_METADATA_KEYS | {"comparison_window"}
_SNAPSHOT_TIME_METADATA_KEYS = {
    "calendar_id",
    "mode",
    "selection",
    "as_of_parameter",
    "fields",
}


def _comparison_window(
    metadata: dict[str, Any],
    start_parameter: str,
    end_parameter: str,
) -> dict[str, str] | None:
    if "comparison_window" not in metadata:
        return None
    value = metadata["comparison_window"]
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or set(value) != {"start_parameter", "end_parameter"}
        or not str(value.get("start_parameter"))
        or not str(value.get("end_parameter"))
    ):
        raise _invalid("런타임 비교 윈도우 메타데이터가 유효하지 않습니다.")
    comparison_start = str(value["start_parameter"])
    comparison_end = str(value["end_parameter"])
    if len({start_parameter, end_parameter, comparison_start, comparison_end}) != 4:
        raise _invalid("비교 윈도우 파라미터는 기본 분석 윈도우 파라미터와 명확히 구분되어야 합니다.")
    return {"start_parameter": comparison_start, "end_parameter": comparison_end}


def _time_rules(
    package: Any,
    assets: list[dict[str, object]],
    context: Any,
    approved: dict[str, frozenset[str]],
) -> dict[str, Any]:
    metadata = _common_contract(assets, "time_metadata")
    mode = str(metadata.get("mode") or "range")
    valid_shape = (
        mode == "range"
        and set(metadata) in (_TIME_METADATA_KEYS, _TIME_METADATA_KEYS_WITH_COMPARISON)
    ) or (
        mode == "latest_snapshot"
        and set(metadata) == _SNAPSHOT_TIME_METADATA_KEYS
        and metadata.get("selection") == "max_source_value_lt_as_of"
        and bool(str(metadata.get("as_of_parameter") or ""))
    )
    if not valid_shape or not isinstance(metadata["fields"], list):
        raise _invalid("런타임 time_metadata 가 누락되었거나 유효하지 않습니다.")
    comparison_window = (
        _comparison_window(
            metadata, str(metadata["start_parameter"]), str(metadata["end_parameter"])
        )
        if mode == "range"
        else None
    )
    fields = []
    for item in metadata["fields"]:
        if not isinstance(item, dict) or set(item) != {
            "field",
            "native_type",
            "bucket",
            "timezone_mode",
        }:
            raise _invalid("런타임 시간 필드 메타데이터가 올바르지 않습니다.")
        field_target = item.get("field")
        if isinstance(field_target, dict) and str(field_target.get("asset_fqn")) in approved:
            fields.append({**item, "field": _qualified(item["field"], approved)})
    required = {
        (metric.asset_fqn, metric.time_field)
        for metric in package.metrics
        if metric.aggregation.lower() != "ratio"
    }
    actual = {(item["field"]["asset_fqn"], item["field"]["column"]) for item in fields}
    if not required.issubset(actual):
        raise _invalid("지표 시간 필드가 런타임 시간 메타데이터에 정의되어 있지 않습니다.")
    common = {
        "timezone": context.timezone,
        "calendar_id": str(metadata["calendar_id"]),
        "fields": fields,
    }
    if mode == "latest_snapshot":
        return {
            **common,
            "mode": mode,
            "selection": "max_source_value_lt_as_of",
            "as_of_parameter": str(metadata["as_of_parameter"]),
        }
    return {
        **common,
        "interval": "[start,end)",
        "start_parameter": str(metadata["start_parameter"]),
        "end_parameter": str(metadata["end_parameter"]),
        "comparison_window": comparison_window,
    }


def _parameter_contract(
    package: Any,
    assets: list[dict[str, object]],
) -> dict[str, Any]:
    mode = time_selection_mode(assets)
    if mode == "latest_snapshot":
        time_names = {snapshot_parameter_name(assets)}
    else:
        start_name, end_name = time_parameter_names(assets)
        time_names = {start_name, end_name}
        comparison_names = comparison_time_parameter_names(assets)
        if comparison_names is not None:
            time_names |= set(comparison_names)
    filter_names = {item.name for item in filter_parameter_bindings(assets)}
    parameters = []
    for item in package.parameter_bindings:
        scope = "time" if item.name in time_names else "filter" if item.name in filter_names else None
        if scope is None:
            raise _invalid("런타임 파라미터 스코프가 거버넌스 승인 범위를 벗어납니다.")
        parameters.append({"name": item.name, "type": item.value_type, "scope": scope})
    return {"style": "named", "parameters": parameters}


def _filter_key(item: Any) -> tuple[str, str, str, object]:
    return item.field, item.operator, item.value_type, item.value


def _raw_filter_key(item: dict[str, Any]) -> tuple[str, str, str, object]:
    required = {"field", "operator", "value_type", "value", "parameter"}
    if set(item) != required or not isinstance(item.get("parameter"), str) or not item["parameter"]:
        raise _invalid("런타임 필수 필터 파라미터 계약이 유효하지 않습니다.")
    return str(item["field"]), str(item["operator"]), str(item["value_type"]), item["value"]


def _model_filter(
    item: object,
    asset_fqn: str,
    approved: dict[str, frozenset[str]],
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise _invalid("런타임 필수 필터 형식이 올바르지 않습니다.")
    _raw_filter_key(item)
    if str(item["field"]) not in approved[asset_fqn]:
        raise _invalid("런타임 필수 필터 컬럼이 승인된 schema_context 범위 밖입니다.")
    return {
        "field": {"asset_fqn": asset_fqn, "column": str(item["field"])},
        "operator": str(item["operator"]),
        "parameter": str(item["parameter"]),
    }


def time_parameter_names(assets: list[dict[str, object]]) -> tuple[str, str]:
    """모든 런타임 자산이 공유하는 시간 메타데이터로부터 시작/종료 파라미터 이름을 추출합니다."""
    metadata = _common_contract(assets, "time_metadata")
    if str(metadata.get("mode") or "range") != "range":
        raise _invalid("최신 스냅샷 계약에는 기간 경계 파라미터가 없습니다.")
    start = str(metadata.get("start_parameter") or "")
    end = str(metadata.get("end_parameter") or "")
    if not start or not end or start == end:
        raise _invalid("런타임 시간 파라미터 이름이 유효하지 않습니다.")
    return start, end


def comparison_time_parameter_names(
    assets: list[dict[str, object]],
) -> tuple[str, str] | None:
    """비교 윈도우의 시작/종료 파라미터 이름을 추출합니다 (없으면 None)."""
    metadata = _common_contract(assets, "time_metadata")
    if str(metadata.get("mode") or "range") != "range":
        return None
    start, end = str(metadata.get("start_parameter") or ""), str(metadata.get("end_parameter") or "")
    comparison = _comparison_window(metadata, start, end)
    if comparison is None:
        return None
    return comparison["start_parameter"], comparison["end_parameter"]


def time_selection_mode(assets: list[dict[str, object]]) -> str:
    """선택 자산들이 공유하는 명시적 시간 선택 mode를 반환한다."""

    metadata = _common_contract(assets, "time_metadata")
    mode = str(metadata.get("mode") or "range")
    if mode not in {"range", "latest_snapshot"}:
        raise _invalid("런타임 시간 선택 mode가 지원 범위를 벗어납니다.")
    return mode


def snapshot_parameter_name(assets: list[dict[str, object]]) -> str:
    """최신 스냅샷의 서버 소유 기준일 파라미터 이름을 반환한다."""

    metadata = _common_contract(assets, "time_metadata")
    name = str(metadata.get("as_of_parameter") or "")
    if (
        str(metadata.get("mode") or "range") != "latest_snapshot"
        or metadata.get("selection") != "max_source_value_lt_as_of"
        or not name
    ):
        raise _invalid("런타임 최신 스냅샷 기준일 계약이 유효하지 않습니다.")
    return name


def filter_parameter_bindings(
    assets: list[dict[str, object]],
) -> tuple[ContextParameterBinding, ...]:
    """자산 및 지표 메타데이터로부터 필수 필터 파라미터 바인딩 목록을 추출합니다."""
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
                raise _invalid("런타임 필수 필터 목록은 배열이어야 합니다.")
            for item in collection:
                if not isinstance(item, dict):
                    raise _invalid("런타임 필수 필터 형식이 올바르지 않습니다.")
                _raw_filter_key(item)
                binding = ContextParameterBinding(
                    str(item["parameter"]),
                    str(item["value_type"]),
                    item["value"],
                )
                previous = values.get(binding.name)
                if previous is not None and previous != binding:
                    raise _invalid("런타임 필터 파라미터 정의 간에 충돌이 발생했습니다.")
                values[binding.name] = binding
    return tuple(values[name] for name in sorted(values))


def _qualified(value: object, approved: dict[str, frozenset[str]]) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"asset_fqn", "column"}:
        raise _invalid("런타임 수식 필드 형식이 올바르지 않습니다.")
    asset, column = str(value["asset_fqn"]), str(value["column"])
    if asset not in approved or column not in approved[asset]:
        raise _invalid("수식 필드가 승인된 schema_context 범위 밖입니다.")
    return {"asset_fqn": asset, "column": column}


def _common_contract(assets: list[dict[str, object]], name: str) -> dict[str, Any]:
    values = [item.get(name) for item in assets if item.get(name) is not None]
    if not values:
        raise _invalid(f"런타임 {name} 계약이 누락되었습니다.")
    canonical = {json.dumps(item, sort_keys=True, separators=(",", ":")) for item in values}
    if len(canonical) != 1 or len(values) != len(assets) or not isinstance(values[0], dict):
        raise _invalid(f"런타임 자산들이 동일한 {name} 계약을 공유하지 않습니다.")
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
        raise _invalid("런타임 query_policy 가 schema_context 에 부합하지 않습니다.")


def _invalid(message: str) -> ContextBuildError:
    return ContextBuildError(ContextBuildErrorCode.INVALID_METADATA, message)
