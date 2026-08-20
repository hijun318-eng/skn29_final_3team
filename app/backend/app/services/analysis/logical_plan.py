"""구조화 요청과 런타임 메타데이터를 버전형 논리 분석 계획으로 컴파일한다.

이 모듈의 권위 입력은 질문 원문이 아니라 ``RuntimeContextPackage``의 지표·스키마·
조인·시간·권한 계약과 Node 1이 검증을 마친 구조화 슬롯이다. 결과 계획은 SQL을 직접
포함하지 않으며, Node 2와 SQL Guard가 동일한 연산·grain·JOIN 결정을 공유하게 한다.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from app.services.context.fanout_policy import (
    AssetGrainEvidence,
    FanoutPlan,
    GrainSafetyEvidence,
    RelatedSideUse,
    decide_fanout_plan,
)
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V2


ANALYSIS_PLAN_VERSION = "ANSWERVICE-ANALYSIS-PLAN-v1"
MAX_ANALYSIS_METRICS = 4


class AnalysisOperation(str, Enum):
    """질문 문구와 분리해 실행기가 지원하는 범용 분석 연산을 식별한다."""

    AGGREGATE = "aggregate"
    BREAKDOWN = "breakdown"
    TIME_TREND = "time_trend"
    TOP_N = "top_n"
    BOTTOM_N = "bottom_n"
    PERIOD_COMPARISON = "period_comparison"


class AnalysisTimeMode(str, Enum):
    """기간 필터와 최신 스냅샷 선택을 서로 다른 실행 의미로 구분한다."""

    RANGE = "range"
    LATEST_SNAPSHOT = "latest_snapshot"


class AnalysisPlanErrorCode(str, Enum):
    """논리 계획 컴파일 실패를 사용자 입력과 거버넌스 결함으로 구분한다."""

    INVALID_OPERATION = "INVALID_OPERATION"
    METRIC_SCOPE_MISMATCH = "METRIC_SCOPE_MISMATCH"
    DIMENSION_NOT_BOUND = "DIMENSION_NOT_BOUND"
    TIME_MODE_NOT_GOVERNED = "TIME_MODE_NOT_GOVERNED"
    PERIOD_CONTRACT_MISMATCH = "PERIOD_CONTRACT_MISMATCH"
    JOIN_PERMISSION_DENIED = "JOIN_PERMISSION_DENIED"
    JOIN_PATH_UNAVAILABLE = "JOIN_PATH_UNAVAILABLE"
    FANOUT_UNSAFE = "FANOUT_UNSAFE"
    INVALID_RUNTIME_CONTRACT = "INVALID_RUNTIME_CONTRACT"


class AnalysisPlanError(ValueError):
    """런타임 증거만으로 안전한 논리 분석 계획을 만들 수 없음을 나타낸다."""

    def __init__(self, code: AnalysisPlanErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, order=True)
class PlannedField:
    """분석 계획에서 사용하는 asset 한정 물리 필드다."""

    asset_fqn: str
    column: str

    @property
    def qualified(self) -> str:
        """팬아웃·SQL Guard가 공유하는 완전 수식 필드 이름을 반환한다."""

        return f"{self.asset_fqn}.{self.column}"

    def as_dict(self) -> dict[str, str]:
        """모델 입력과 감사 로그에 사용할 직렬화 형태를 반환한다."""

        return {"asset_fqn": self.asset_fqn, "column": self.column}


@dataclass(frozen=True)
class PlannedJoin:
    """한 governed JOIN edge에 대해 결정된 팬아웃 처리 방식과 근거다."""

    join_id: str
    plan: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        """SQL 생성기가 소비할 안정적인 JOIN 계획 형태를 반환한다."""

        return {"join_id": self.join_id, "plan": self.plan, "reason": self.reason}


@dataclass(frozen=True)
class AnalysisPlan:
    """SQL 생성 전 서버가 확정하는 불변·체크섬 결합 논리 분석 계획이다."""

    version: str
    operation: AnalysisOperation
    output_metric_ids: tuple[str, ...]
    dependency_metric_ids: tuple[str, ...]
    dimension_fields: tuple[PlannedField, ...]
    filter_fields: tuple[PlannedField, ...]
    time_mode: AnalysisTimeMode
    time_fields: tuple[PlannedField, ...]
    time_bucket: str
    period_parameters: tuple[tuple[str, str], ...]
    result_limit: int | None
    query_strategy: str
    joins: tuple[PlannedJoin, ...]
    context_package_hash: str
    checksum: str

    def as_dict(self) -> dict[str, Any]:
        """체크섬을 포함한 전송·캐시용 계획 payload를 반환한다."""

        return {
            **self._identity_payload(),
            "checksum": self.checksum,
        }

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "operation": self.operation.value,
            "output_metric_ids": list(self.output_metric_ids),
            "dependency_metric_ids": list(self.dependency_metric_ids),
            "dimension_fields": [item.as_dict() for item in self.dimension_fields],
            "filter_fields": [item.as_dict() for item in self.filter_fields],
            "time_mode": self.time_mode.value,
            "time_fields": [item.as_dict() for item in self.time_fields],
            "time_bucket": self.time_bucket,
            "period_parameters": [
                {"start_parameter": start, "end_parameter": end}
                for start, end in self.period_parameters
            ],
            "result_limit": self.result_limit,
            "query_strategy": self.query_strategy,
            "joins": [item.as_dict() for item in self.joins],
            "context_package_hash": self.context_package_hash,
        }


def build_analysis_plan(
    structured_request: Mapping[str, object],
    package: object,
) -> AnalysisPlan:
    """검증된 슬롯과 runtime context만으로 범용 논리 분석 계획을 만든다.

    지표는 최대 네 개로 제한하고, 차원은 선택 지표가 선언한 물리 binding의 교집합만
    허용한다. 여러 asset이 필요하면 승인 graph의 최단 경로와 metric JOIN 권한을 확인한
    뒤 각 edge의 팬아웃 물리 계획을 결정한다.
    """

    contracts = _runtime_contracts(package)
    schemas = _schemas(contracts)
    rules = _metric_rules(contracts)
    package_metrics = {
        str(item.id): item for item in tuple(getattr(package, "metrics", ()))
    }
    output_metric_ids = _output_metric_ids(structured_request, package_metrics)
    dependency_metric_ids = _metric_dependencies(output_metric_ids, rules)
    if not set(dependency_metric_ids).issubset(package_metrics):
        raise _error(
            AnalysisPlanErrorCode.METRIC_SCOPE_MISMATCH,
            "분석 지표의 계산 의존성이 Runtime Context에 모두 포함되어 있지 않습니다.",
        )

    dimensions = _requested_fields(
        structured_request.get("dimension_fields"),
        schemas,
        "dimension_fields",
    )
    filters = _requested_fields(
        structured_request.get("filter_fields"),
        schemas,
        "filter_fields",
    )
    allowed_dimensions = _shared_dimensions(output_metric_ids, rules)
    if any(item.qualified not in allowed_dimensions for item in dimensions):
        raise _error(
            AnalysisPlanErrorCode.DIMENSION_NOT_BOUND,
            "요청 차원이 선택 지표의 source asset에 승인된 물리 필드로 binding되지 않았습니다.",
        )

    operation = _operation(structured_request, dimensions, output_metric_ids, rules)
    result_limit = _result_limit(operation, structured_request, contracts)
    time_mode, time_fields, time_bucket, periods = _time_contract(
        operation,
        structured_request,
        output_metric_ids,
        rules,
        contracts,
        package,
    )
    _validate_operation_shape(operation, dimensions)

    measure_assets = frozenset(
        asset
        for metric_id in output_metric_ids
        for asset in _metric_source_assets(metric_id, rules, frozenset())
    )
    target_assets = measure_assets | frozenset(
        item.asset_fqn for item in (*dimensions, *filters)
    )
    planned_joins = _plan_joins(
        target_assets=target_assets,
        measure_assets=measure_assets,
        dimension_assets=frozenset(item.asset_fqn for item in dimensions),
        output_metric_ids=output_metric_ids,
        package_metrics=package_metrics,
        schemas=schemas,
        graph=tuple(getattr(package, "join_graph", ())),
    )

    values = {
        "version": ANALYSIS_PLAN_VERSION,
        "operation": operation.value,
        "output_metric_ids": list(output_metric_ids),
        "dependency_metric_ids": list(dependency_metric_ids),
        "dimension_fields": [item.as_dict() for item in dimensions],
        "filter_fields": [item.as_dict() for item in filters],
        "time_mode": time_mode.value,
        "time_fields": [item.as_dict() for item in time_fields],
        "time_bucket": time_bucket,
        "period_parameters": [
            {"start_parameter": start, "end_parameter": end}
            for start, end in periods
        ],
        "result_limit": result_limit,
        "query_strategy": str(getattr(package, "query_strategy", "")),
        "joins": [item.as_dict() for item in planned_joins],
        "context_package_hash": str(getattr(package, "package_hash", "")),
    }
    checksum = _checksum(values)
    return AnalysisPlan(
        version=ANALYSIS_PLAN_VERSION,
        operation=operation,
        output_metric_ids=output_metric_ids,
        dependency_metric_ids=dependency_metric_ids,
        dimension_fields=dimensions,
        filter_fields=filters,
        time_mode=time_mode,
        time_fields=time_fields,
        time_bucket=time_bucket,
        period_parameters=periods,
        result_limit=result_limit,
        query_strategy=values["query_strategy"],
        joins=planned_joins,
        context_package_hash=values["context_package_hash"],
        checksum=checksum,
    )


def validate_analysis_plan_payload(value: object, package: object) -> AnalysisPlan:
    """캐시나 단계 사이에서 전달된 계획이 현재 Context와 동일한지 재컴파일해 검증한다."""

    if not isinstance(value, Mapping):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "서버 소유 AnalysisPlan payload가 누락되었습니다.",
        )
    required = {
        "version",
        "operation",
        "output_metric_ids",
        "dependency_metric_ids",
        "dimension_fields",
        "filter_fields",
        "time_mode",
        "time_fields",
        "time_bucket",
        "period_parameters",
        "result_limit",
        "query_strategy",
        "joins",
        "context_package_hash",
        "checksum",
    }
    if set(value) != required or value.get("version") != ANALYSIS_PLAN_VERSION:
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan version 또는 필드 계약이 일치하지 않습니다.",
        )
    identity = {name: value[name] for name in required - {"checksum"}}
    if (
        value.get("context_package_hash") != getattr(package, "package_hash", None)
        or value.get("checksum") != _checksum(identity)
    ):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan checksum이 현재 Runtime Context와 일치하지 않습니다.",
        )
    try:
        operation = AnalysisOperation(str(value["operation"]))
        time_mode = AnalysisTimeMode(str(value["time_mode"]))
        dimensions = tuple(_field_from_payload(item) for item in value["dimension_fields"])
        filters = tuple(_field_from_payload(item) for item in value["filter_fields"])
        time_fields = tuple(_field_from_payload(item) for item in value["time_fields"])
        joins = tuple(
            PlannedJoin(
                join_id=str(item["join_id"]),
                plan=str(item["plan"]),
                reason=str(item["reason"]),
            )
            for item in value["joins"]
            if isinstance(item, Mapping) and set(item) == {"join_id", "plan", "reason"}
        )
        periods = tuple(
            (str(item["start_parameter"]), str(item["end_parameter"]))
            for item in value["period_parameters"]
            if isinstance(item, Mapping)
            and set(item) == {"start_parameter", "end_parameter"}
        )
        output_ids = tuple(map(str, value["output_metric_ids"]))
        dependency_ids = tuple(map(str, value["dependency_metric_ids"]))
    except (KeyError, TypeError, ValueError) as error:
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan payload 값을 typed 계약으로 해석할 수 없습니다.",
        ) from error
    if (
        len(dimensions) != len(value["dimension_fields"])
        or len(filters) != len(value["filter_fields"])
        or len(time_fields) != len(value["time_fields"])
        or len(joins) != len(value["joins"])
        or len(periods) != len(value["period_parameters"])
    ):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan 배열에 유효하지 않은 항목이 포함되어 있습니다.",
        )
    result_limit = value["result_limit"]
    if result_limit is not None and (
        not isinstance(result_limit, int)
        or isinstance(result_limit, bool)
        or result_limit < 1
    ):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan result_limit이 유효하지 않습니다.",
        )
    contracts = _runtime_contracts(package)
    schemas = _schemas(contracts)
    rules = _metric_rules(contracts)
    package_metrics = {
        str(item.id): item for item in tuple(getattr(package, "metrics", ()))
    }
    if (
        not output_ids
        or len(output_ids) > MAX_ANALYSIS_METRICS
        or len(output_ids) != len(set(output_ids))
        or not set(output_ids).issubset(package_metrics)
        or any(
            str(getattr(package_metrics[item], "visibility", "BUSINESS"))
            != "BUSINESS"
            for item in output_ids
        )
        or dependency_ids != _metric_dependencies(output_ids, rules)
    ):
        raise _error(
            AnalysisPlanErrorCode.METRIC_SCOPE_MISMATCH,
            "AnalysisPlan 출력·의존 Metric이 현재 Runtime Context와 일치하지 않습니다.",
        )
    if (
        tuple(sorted(dimensions))
        != _requested_fields(value["dimension_fields"], schemas, "dimension_fields")
        or tuple(sorted(filters))
        != _requested_fields(value["filter_fields"], schemas, "filter_fields")
        or tuple(sorted(time_fields))
        != _requested_fields(value["time_fields"], schemas, "time_fields")
        or any(
            item.qualified not in _shared_dimensions(output_ids, rules)
            for item in dimensions
        )
    ):
        raise _error(
            AnalysisPlanErrorCode.DIMENSION_NOT_BOUND,
            "AnalysisPlan 필드 binding이 현재 Runtime Context와 일치하지 않습니다.",
        )
    expected_time_fields = tuple(
        sorted(
            {
                item
                for metric_id in output_ids
                for item in _metric_time_fields(metric_id, rules, frozenset())
            }
        )
    )
    if time_mode is not AnalysisTimeMode.RANGE or tuple(sorted(time_fields)) != expected_time_fields:
        raise _error(
            AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
            "AnalysisPlan time field 또는 mode가 현재 Runtime Context와 일치하지 않습니다.",
        )
    _validate_operation_shape(operation, dimensions)
    if (operation in {AnalysisOperation.TOP_N, AnalysisOperation.BOTTOM_N}) != (
        result_limit is not None
    ):
        raise _error(
            AnalysisPlanErrorCode.INVALID_OPERATION,
            "AnalysisPlan 순위 연산과 result_limit이 일치하지 않습니다.",
        )
    query_policy = contracts.get("query_policy")
    if result_limit is not None and (
        not isinstance(query_policy, Mapping)
        or not isinstance(query_policy.get("max_limit"), int)
        or result_limit > min(100, int(query_policy["max_limit"]))
    ):
        raise _error(
            AnalysisPlanErrorCode.INVALID_OPERATION,
            "AnalysisPlan result_limit이 현재 query policy 범위를 벗어났습니다.",
        )
    time_rules = contracts["time_rules"]
    if not isinstance(time_rules, Mapping):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan time_rules가 유효하지 않습니다.",
        )
    declared_buckets = {
        _field_from_payload(item["field"]): str(item.get("bucket") or "none")
        for item in time_rules.get("fields", ())
        if isinstance(item, Mapping) and "field" in item
    }
    time_buckets = {declared_buckets.get(item) for item in time_fields}
    expected_bucket = (
        next(iter(time_buckets))
        if operation is AnalysisOperation.TIME_TREND and len(time_buckets) == 1
        else "none"
    )
    if None in time_buckets or str(value["time_bucket"]) != expected_bucket:
        raise _error(
            AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
            "AnalysisPlan time bucket이 현재 Runtime Context와 일치하지 않습니다.",
        )
    expected_periods = [
        (
            str(time_rules.get("start_parameter") or ""),
            str(time_rules.get("end_parameter") or ""),
        )
    ]
    comparison = time_rules.get("comparison_window")
    if operation is AnalysisOperation.PERIOD_COMPARISON:
        if not isinstance(comparison, Mapping):
            raise _error(
                AnalysisPlanErrorCode.PERIOD_CONTRACT_MISMATCH,
                "AnalysisPlan 비교 기간 계약이 Runtime Context에 없습니다.",
            )
        expected_periods.append(
            (
                str(comparison.get("start_parameter") or ""),
                str(comparison.get("end_parameter") or ""),
            )
        )
    if periods != tuple(expected_periods):
        raise _error(
            AnalysisPlanErrorCode.PERIOD_CONTRACT_MISMATCH,
            "AnalysisPlan 기간 파라미터가 현재 Runtime Context와 일치하지 않습니다.",
        )
    if str(value["query_strategy"]) != str(getattr(package, "query_strategy", "")):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan query strategy가 현재 Runtime Context와 일치하지 않습니다.",
        )
    governed_join_ids = {str(item.id) for item in tuple(getattr(package, "join_graph", ()))}
    planned_join_ids = [item.join_id for item in joins]
    if (
        len(planned_join_ids) != len(set(planned_join_ids))
        or not set(planned_join_ids).issubset(governed_join_ids)
        or any(item.plan not in {member.value for member in FanoutPlan} for item in joins)
    ):
        raise _error(
            AnalysisPlanErrorCode.JOIN_PATH_UNAVAILABLE,
            "AnalysisPlan JOIN 결정이 현재 Runtime Context graph 범위를 벗어났습니다.",
        )
    return AnalysisPlan(
        version=ANALYSIS_PLAN_VERSION,
        operation=operation,
        output_metric_ids=output_ids,
        dependency_metric_ids=dependency_ids,
        dimension_fields=dimensions,
        filter_fields=filters,
        time_mode=time_mode,
        time_fields=time_fields,
        time_bucket=str(value["time_bucket"]),
        period_parameters=periods,
        result_limit=result_limit,
        query_strategy=str(value["query_strategy"]),
        joins=joins,
        context_package_hash=str(value["context_package_hash"]),
        checksum=str(value["checksum"]),
    )


def _runtime_contracts(package: object) -> Mapping[str, Any]:
    contracts = getattr(package, "runtime_contracts", None)
    required = {
        "schema_context",
        "metric_rules",
        "join_graph",
        "time_rules",
        "parameter_contract",
        "query_policy",
    }
    if not isinstance(contracts, Mapping) or set(contracts) != required:
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan에는 여섯 개의 검증된 Runtime Context 계약이 필요합니다.",
        )
    return contracts


def _schemas(contracts: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    context = contracts.get("schema_context")
    assets = context.get("assets") if isinstance(context, Mapping) else None
    if not isinstance(assets, list) or not assets:
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan schema_context.assets가 비어 있거나 유효하지 않습니다.",
        )
    result: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if not isinstance(asset, Mapping):
            raise _error(
                AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                "AnalysisPlan asset schema 항목이 유효하지 않습니다.",
            )
        fqn = str(asset.get("fqn") or "")
        grain = asset.get("grain")
        columns = asset.get("columns")
        if (
            not fqn
            or fqn in result
            or not isinstance(grain, Mapping)
            or not isinstance(grain.get("keys"), list)
            or not isinstance(columns, list)
        ):
            raise _error(
                AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                "AnalysisPlan asset의 FQN·grain·columns 계약이 유효하지 않습니다.",
            )
        names = {
            str(column.get("name"))
            for column in columns
            if isinstance(column, Mapping) and column.get("name")
        }
        grain_keys = tuple(map(str, grain["keys"]))
        if len(names) != len(columns) or not grain_keys or not set(grain_keys) <= names:
            raise _error(
                AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                "AnalysisPlan asset grain이 실제 schema 범위를 벗어났습니다.",
            )
        result[fqn] = {"fields": names, "grain_keys": grain_keys}
    return result


def _metric_rules(contracts: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = contracts.get("metric_rules")
    if not isinstance(raw, list) or not raw:
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan metric_rules가 비어 있거나 유효하지 않습니다.",
        )
    rules = {
        str(item.get("id")): item
        for item in raw
        if isinstance(item, Mapping) and item.get("id")
    }
    if len(rules) != len(raw):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan metric ID는 비어 있지 않고 고유해야 합니다.",
        )
    return rules


def _output_metric_ids(
    request: Mapping[str, object],
    package_metrics: Mapping[str, object],
) -> tuple[str, ...]:
    raw_many = request.get("selected_metric_ids")
    if raw_many is not None:
        if not isinstance(raw_many, (list, tuple)):
            raise _error(
                AnalysisPlanErrorCode.METRIC_SCOPE_MISMATCH,
                "selected_metric_ids는 배열이어야 합니다.",
            )
        values = tuple(map(str, raw_many))
    else:
        selected = request.get("selected_metric_id")
        values = (str(selected),) if isinstance(selected, str) and selected else ()
    if not values:
        business = tuple(
            metric_id
            for metric_id, metric in package_metrics.items()
            if str(getattr(metric, "visibility", "BUSINESS")) == "BUSINESS"
        )
        values = business if len(business) == 1 else ()
    if (
        not values
        or len(values) > MAX_ANALYSIS_METRICS
        or len(values) != len(set(values))
        or not set(values).issubset(package_metrics)
        or any(
            str(getattr(package_metrics[item], "visibility", "BUSINESS")) != "BUSINESS"
            for item in values
        )
    ):
        raise _error(
            AnalysisPlanErrorCode.METRIC_SCOPE_MISMATCH,
            "분석 출력 지표는 권한이 확인된 BUSINESS 지표 1~4개여야 합니다.",
        )
    return values


def _metric_dependencies(
    output_ids: tuple[str, ...],
    rules: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    resolved: set[str] = set()

    def visit(metric_id: str, visiting: frozenset[str]) -> None:
        if metric_id in visiting or metric_id not in rules:
            raise _error(
                AnalysisPlanErrorCode.METRIC_SCOPE_MISMATCH,
                "지표 계산 의존성이 누락되었거나 순환합니다.",
            )
        if metric_id in resolved:
            return
        source = rules[metric_id].get("source")
        if not isinstance(source, Mapping):
            raise _error(
                AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                "지표 source 계약이 유효하지 않습니다.",
            )
        if source.get("kind") == "ratio":
            for name in ("numerator_metric_id", "denominator_metric_id"):
                operand = source.get(name)
                if not isinstance(operand, str) or not operand:
                    raise _error(
                        AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                        "Ratio 지표 operand 계약이 유효하지 않습니다.",
                    )
                visit(operand, visiting | {metric_id})
        elif source.get("kind") != "column":
            raise _error(
                AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                "지원되지 않는 지표 source kind입니다.",
            )
        resolved.add(metric_id)

    for output_id in output_ids:
        visit(output_id, frozenset())
    return tuple(sorted(resolved))


def _requested_fields(
    value: object,
    schemas: Mapping[str, Mapping[str, Any]],
    name: str,
) -> tuple[PlannedField, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            f"{name}는 구조화된 필드 배열이어야 합니다.",
        )
    fields = tuple(_field_from_payload(item) for item in value)
    if len(fields) != len(set(fields)):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            f"{name}에는 중복 필드를 포함할 수 없습니다.",
        )
    for item in fields:
        schema = schemas.get(item.asset_fqn)
        if schema is None or item.column not in schema["fields"]:
            raise _error(
                AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                f"{name}가 승인된 asset schema 범위를 벗어났습니다.",
            )
    return tuple(sorted(fields))


def _field_from_payload(value: object) -> PlannedField:
    if not isinstance(value, Mapping) or set(value) != {"asset_fqn", "column"}:
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "계획 필드는 asset_fqn과 column만 포함해야 합니다.",
        )
    asset_fqn = str(value["asset_fqn"])
    column = str(value["column"])
    if not asset_fqn or not column:
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "계획 필드의 asset_fqn과 column은 비어 있을 수 없습니다.",
        )
    return PlannedField(asset_fqn, column)


def _operation(
    request: Mapping[str, object],
    dimensions: tuple[PlannedField, ...],
    output_ids: tuple[str, ...],
    rules: Mapping[str, Mapping[str, Any]],
) -> AnalysisOperation:
    relationship = str(request.get("period_relationship") or "single")
    explicit = request.get("analysis_operation")
    if explicit is not None:
        try:
            operation = AnalysisOperation(str(explicit))
        except ValueError as error:
            raise _error(
                AnalysisPlanErrorCode.INVALID_OPERATION,
                "요청한 분석 연산이 현재 version 계약에 없습니다.",
            ) from error
    elif relationship == "comparison":
        operation = AnalysisOperation.PERIOD_COMPARISON
    else:
        intents = {
            str(item)
            for item in request.get("intent_candidates", ())
            if isinstance(item, str)
        }
        specific = intents & {
            AnalysisOperation.BREAKDOWN.value,
            AnalysisOperation.TIME_TREND.value,
            AnalysisOperation.TOP_N.value,
            AnalysisOperation.BOTTOM_N.value,
        }
        if len(specific) > 1:
            raise _error(
                AnalysisPlanErrorCode.INVALID_OPERATION,
                "서로 다른 분석 연산 후보를 하나의 계획으로 확정할 수 없습니다.",
            )
        if specific:
            operation = AnalysisOperation(next(iter(specific)))
        elif dimensions:
            time_fields = {
                item.qualified
                for metric_id in output_ids
                for item in _metric_time_fields(metric_id, rules, frozenset())
            }
            operation = (
                AnalysisOperation.TIME_TREND
                if {item.qualified for item in dimensions} <= time_fields
                else AnalysisOperation.BREAKDOWN
            )
        else:
            operation = AnalysisOperation.AGGREGATE
    if relationship == "comparison" and operation is not AnalysisOperation.PERIOD_COMPARISON:
        raise _error(
            AnalysisPlanErrorCode.INVALID_OPERATION,
            "두 기간 요청은 period_comparison 연산으로만 실행할 수 있습니다.",
        )
    return operation


def _validate_operation_shape(
    operation: AnalysisOperation,
    dimensions: tuple[PlannedField, ...],
) -> None:
    if operation is AnalysisOperation.AGGREGATE and dimensions:
        raise _error(
            AnalysisPlanErrorCode.INVALID_OPERATION,
            "aggregate 연산은 차원 GROUP BY를 포함할 수 없습니다.",
        )
    if operation in {
        AnalysisOperation.BREAKDOWN,
        AnalysisOperation.TOP_N,
        AnalysisOperation.BOTTOM_N,
    } and not dimensions:
        raise _error(
            AnalysisPlanErrorCode.DIMENSION_NOT_BOUND,
            "차원 분해·순위 연산에는 승인된 차원 binding이 필요합니다.",
        )


def _result_limit(
    operation: AnalysisOperation,
    request: Mapping[str, object],
    contracts: Mapping[str, Any],
) -> int | None:
    if operation not in {AnalysisOperation.TOP_N, AnalysisOperation.BOTTOM_N}:
        return None
    value = request.get("result_limit")
    policy = contracts.get("query_policy")
    max_limit = policy.get("max_limit") if isinstance(policy, Mapping) else None
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > 100
        or not isinstance(max_limit, int)
        or value > max_limit
    ):
        raise _error(
            AnalysisPlanErrorCode.INVALID_OPERATION,
            "top_n·bottom_n의 result_limit은 정책 범위 안의 1~100이어야 합니다.",
        )
    return value


def _shared_dimensions(
    metric_ids: tuple[str, ...],
    rules: Mapping[str, Mapping[str, Any]],
) -> frozenset[str]:
    dimensions = [
        _metric_dimensions(metric_id, rules, frozenset()) for metric_id in metric_ids
    ]
    return frozenset.intersection(*dimensions) if dimensions else frozenset()


def _metric_dimensions(
    metric_id: str,
    rules: Mapping[str, Mapping[str, Any]],
    visiting: frozenset[str],
) -> frozenset[str]:
    if metric_id in visiting or metric_id not in rules:
        raise _error(
            AnalysisPlanErrorCode.METRIC_SCOPE_MISMATCH,
            "지표 차원 의존성을 해석할 수 없습니다.",
        )
    rule = rules[metric_id]
    source = rule.get("source")
    if not isinstance(source, Mapping):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "지표 source 계약이 유효하지 않습니다.",
        )
    if source.get("kind") == "ratio":
        values = [
            _metric_dimensions(str(source[name]), rules, visiting | {metric_id})
            for name in ("numerator_metric_id", "denominator_metric_id")
        ]
        return frozenset.intersection(*values)
    raw = rule.get("dimensions")
    if not isinstance(raw, list):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "지표 dimension binding 목록이 유효하지 않습니다.",
        )
    return frozenset(_field_from_payload(item).qualified for item in raw)


def _metric_time_fields(
    metric_id: str,
    rules: Mapping[str, Mapping[str, Any]],
    visiting: frozenset[str],
) -> frozenset[PlannedField]:
    if metric_id in visiting or metric_id not in rules:
        raise _error(
            AnalysisPlanErrorCode.METRIC_SCOPE_MISMATCH,
            "지표 시간 의존성을 해석할 수 없습니다.",
        )
    source = rules[metric_id].get("source")
    if not isinstance(source, Mapping):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "지표 source 계약이 유효하지 않습니다.",
        )
    if source.get("kind") == "ratio":
        return frozenset(
            item
            for name in ("numerator_metric_id", "denominator_metric_id")
            for item in _metric_time_fields(
                str(source[name]), rules, visiting | {metric_id}
            )
        )
    time_field = rules[metric_id].get("time_field")
    return frozenset({_field_from_payload(time_field)})


def _time_contract(
    operation: AnalysisOperation,
    request: Mapping[str, object],
    output_ids: tuple[str, ...],
    rules: Mapping[str, Mapping[str, Any]],
    contracts: Mapping[str, Any],
    package: object,
) -> tuple[
    AnalysisTimeMode,
    tuple[PlannedField, ...],
    str,
    tuple[tuple[str, str], ...],
]:
    requested_mode = str(request.get("time_mode") or AnalysisTimeMode.RANGE.value)
    try:
        mode = AnalysisTimeMode(requested_mode)
    except ValueError as error:
        raise _error(
            AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
            "요청한 time mode가 현재 AnalysisPlan version에 없습니다.",
        ) from error
    # 현재 runtime v2는 모든 지표에 반개방 기간 파라미터를 요구한다. latest snapshot은
    # 후보 계약에만 존재하며 명시적 runtime sidecar가 발행되기 전에는 추정해 열지 않는다.
    if mode is AnalysisTimeMode.LATEST_SNAPSHOT:
        raise _error(
            AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
            "최신 스냅샷 선택 규칙이 활성 Runtime Context에 아직 발행되지 않았습니다.",
        )
    fields = tuple(
        sorted(
            {
                item
                for metric_id in output_ids
                for item in _metric_time_fields(metric_id, rules, frozenset())
            }
        )
    )
    time_rules = contracts.get("time_rules")
    if not isinstance(time_rules, Mapping):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "Runtime time_rules가 유효하지 않습니다.",
        )
    declared = {
        _field_from_payload(item["field"]): str(item.get("bucket") or "none")
        for item in time_rules.get("fields", ())
        if isinstance(item, Mapping) and "field" in item
    }
    if not fields or any(item not in declared for item in fields):
        raise _error(
            AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
            "선택 지표의 time field가 Runtime time_rules에 완전히 선언되지 않았습니다.",
        )
    buckets = {declared[item] for item in fields}
    if operation is AnalysisOperation.TIME_TREND and len(buckets) != 1:
        raise _error(
            AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
            "추이 지표들의 승인 time bucket이 서로 달라 하나의 계획으로 합칠 수 없습니다.",
        )
    bucket = next(iter(buckets)) if operation is AnalysisOperation.TIME_TREND else "none"
    start = str(time_rules.get("start_parameter") or "")
    end = str(time_rules.get("end_parameter") or "")
    periods: list[tuple[str, str]] = [(start, end)]
    if operation is AnalysisOperation.PERIOD_COMPARISON:
        comparison = time_rules.get("comparison_window")
        if not isinstance(comparison, Mapping):
            raise _error(
                AnalysisPlanErrorCode.PERIOD_CONTRACT_MISMATCH,
                "기간 비교 요청에 승인된 comparison window가 없습니다.",
            )
        periods.append(
            (
                str(comparison.get("start_parameter") or ""),
                str(comparison.get("end_parameter") or ""),
            )
        )
    bound_names = {
        str(item.name) for item in tuple(getattr(package, "parameter_bindings", ()))
    }
    if any(not a or not b or a == b or {a, b} - bound_names for a, b in periods):
        raise _error(
            AnalysisPlanErrorCode.PERIOD_CONTRACT_MISMATCH,
            "AnalysisPlan 기간 파라미터가 서버 소유 binding과 일치하지 않습니다.",
        )
    return mode, fields, bucket, tuple(periods)


def _metric_source_assets(
    metric_id: str,
    rules: Mapping[str, Mapping[str, Any]],
    visiting: frozenset[str],
) -> frozenset[str]:
    if metric_id in visiting or metric_id not in rules:
        raise _error(
            AnalysisPlanErrorCode.METRIC_SCOPE_MISMATCH,
            "지표 source asset 의존성을 해석할 수 없습니다.",
        )
    source = rules[metric_id].get("source")
    if not isinstance(source, Mapping):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "지표 source 계약이 유효하지 않습니다.",
        )
    if source.get("kind") == "column":
        field = _field_from_payload(source.get("field"))
        return frozenset({field.asset_fqn})
    if source.get("kind") == "ratio":
        return frozenset(
            asset
            for name in ("numerator_metric_id", "denominator_metric_id")
            for asset in _metric_source_assets(
                str(source[name]), rules, visiting | {metric_id}
            )
        )
    raise _error(
        AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
        "지원되지 않는 지표 source kind입니다.",
    )


def _plan_joins(
    *,
    target_assets: frozenset[str],
    measure_assets: frozenset[str],
    dimension_assets: frozenset[str],
    output_metric_ids: tuple[str, ...],
    package_metrics: Mapping[str, object],
    schemas: Mapping[str, Mapping[str, Any]],
    graph: tuple[object, ...],
) -> tuple[PlannedJoin, ...]:
    if len(target_assets) <= 1:
        return ()
    selected = _minimal_join_tree(target_assets, graph)
    selected_ids = {str(item.id) for item in selected}
    for metric_id in output_metric_ids:
        metric = package_metrics[metric_id]
        if (
            str(getattr(metric, "governance_version", ""))
            == RUNTIME_GOVERNANCE_VERSION_V2
            and not selected_ids <= set(getattr(metric, "allowed_join_ids", ()))
        ):
            raise _error(
                AnalysisPlanErrorCode.JOIN_PERMISSION_DENIED,
                "선택 지표가 필요한 JOIN edge 전체에 대한 실행 권한을 갖고 있지 않습니다.",
            )
    result: list[PlannedJoin] = []
    for edge in selected:
        endpoints = frozenset({str(edge.left), str(edge.right)})
        left_component, right_component = _edge_components(edge, selected)
        evidence_measure_sides = frozenset(
            endpoint
            for endpoint, component in (
                (str(edge.left), left_component),
                (str(edge.right), right_component),
            )
            if component & measure_assets
        )
        if not evidence_measure_sides:
            raise _error(
                AnalysisPlanErrorCode.FANOUT_UNSAFE,
                "JOIN edge 어느 쪽에도 지표 grain의 출처를 증명할 수 없습니다.",
            )
        if evidence_measure_sides == endpoints:
            related_use = RelatedSideUse.SECOND_MEASURE
            common = tuple(edge.equality_conditions)
        else:
            non_measure_component = (
                right_component
                if str(edge.left) in evidence_measure_sides
                else left_component
            )
            related_use = (
                RelatedSideUse.DIMENSION_BREAKDOWN
                if non_measure_component & dimension_assets
                else RelatedSideUse.FILTER_ONLY
            )
            common = ()
        asset_evidence = tuple(
            AssetGrainEvidence(
                asset_fqn=endpoint,
                available_fields=frozenset(
                    f"{endpoint}.{field}" for field in schemas[endpoint]["fields"]
                ),
                unique_key_sets=(
                    tuple(
                        f"{endpoint}.{field}"
                        for field in schemas[endpoint]["grain_keys"]
                    ),
                ),
            )
            for endpoint in sorted(endpoints)
        )
        decision = decide_fanout_plan(
            edge,
            GrainSafetyEvidence(
                measure_assets=evidence_measure_sides,
                related_side_use=related_use,
                assets=asset_evidence,
                common_grain_bindings=common,
            ),
        )
        if decision.plan is FanoutPlan.REJECT:
            raise _error(
                AnalysisPlanErrorCode.FANOUT_UNSAFE,
                f"JOIN {edge.id!r}의 팬아웃 안전성을 증명하지 못했습니다: {decision.reason.value}",
            )
        result.append(
            PlannedJoin(
                join_id=decision.join_id,
                plan=decision.plan.value,
                reason=decision.reason.value,
            )
        )
    return tuple(sorted(result, key=lambda item: item.join_id))


def _minimal_join_tree(
    targets: frozenset[str],
    graph: tuple[object, ...],
) -> tuple[object, ...]:
    by_node: dict[str, list[object]] = {}
    for edge in graph:
        left, right = str(edge.left), str(edge.right)
        by_node.setdefault(left, []).append(edge)
        by_node.setdefault(right, []).append(edge)
    anchor = min(targets)
    selected: dict[str, object] = {}
    for target in sorted(targets - {anchor}):
        pending: deque[tuple[str, tuple[object, ...]]] = deque([(anchor, ())])
        visited = {anchor}
        path: tuple[object, ...] | None = None
        while pending:
            node, edges = pending.popleft()
            if node == target:
                path = edges
                break
            for edge in sorted(by_node.get(node, ()), key=lambda item: str(item.id)):
                neighbor = str(edge.right) if str(edge.left) == node else str(edge.left)
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                pending.append((neighbor, (*edges, edge)))
        if path is None:
            raise _error(
                AnalysisPlanErrorCode.JOIN_PATH_UNAVAILABLE,
                "분석에 필요한 asset들이 승인된 JOIN graph로 연결되지 않습니다.",
            )
        selected.update({str(edge.id): edge for edge in path})
    return tuple(selected[key] for key in sorted(selected))


def _edge_components(
    removed: object,
    selected: tuple[object, ...],
) -> tuple[frozenset[str], frozenset[str]]:
    adjacency: dict[str, set[str]] = {}
    for edge in selected:
        if str(edge.id) == str(removed.id):
            continue
        left, right = str(edge.left), str(edge.right)
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)

    def walk(start: str) -> frozenset[str]:
        pending = [start]
        visited: set[str] = set()
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            pending.extend(adjacency.get(node, ()))
        return frozenset(visited)

    return walk(str(removed.left)), walk(str(removed.right))


def _checksum(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _error(code: AnalysisPlanErrorCode, message: str) -> AnalysisPlanError:
    return AnalysisPlanError(code, message)
