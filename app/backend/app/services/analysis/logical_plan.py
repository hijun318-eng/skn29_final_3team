"""구조화 요청과 런타임 메타데이터를 버전형 논리 분석 계획으로 컴파일한다.

이 모듈의 권위 입력은 질문 원문이 아니라 ``RuntimeContextPackage``의 지표·스키마·
조인·시간·권한 계약과 Node 1이 검증을 마친 구조화 슬롯이다. 결과 계획은 SQL을 직접
포함하지 않으며, Node 2와 SQL Guard가 동일한 연산·grain·JOIN 결정을 공유하게 한다.
"""

from __future__ import annotations

import hashlib
import json
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


ANALYSIS_PLAN_VERSION = "ANSWERVICE-ANALYSIS-PLAN-v4"
ANALYSIS_PLAN_FIELDS = frozenset(
    {
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
        "snapshot_parameter",
        "result_limit",
        "query_strategy",
        "joins",
        "context_package_hash",
        "checksum",
    }
)
ANALYSIS_TIME_BUCKETS = frozenset({"day", "week", "month", "quarter", "year"})
_SAFE_TIME_ROLLUPS = {
    "day": ANALYSIS_TIME_BUCKETS,
    "week": frozenset({"week"}),
    "month": frozenset({"month", "quarter", "year"}),
    "quarter": frozenset({"quarter", "year"}),
    "year": frozenset({"year"}),
}
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


ACTIVE_ANALYSIS_TIME_MODES = frozenset(
    {AnalysisTimeMode.RANGE, AnalysisTimeMode.LATEST_SNAPSHOT}
)
PERIOD_COMPARISON_UNSUPPORTED_AGGREGATIONS = frozenset({"exists"})


def active_analysis_capabilities() -> dict[str, object]:
    """현재 Backend와 SQL Guard가 실제로 구현한 분석 capability를 반환한다.

    카탈로그가 선언한 희망 기능과 실행 코드가 지원하는 기능을 같은 것으로 간주하지 않도록
    enum·최대 지표 수·시간 mode·기간 비교 제한을 기계 판독 가능한 계약으로 공개한다.
    """

    return {
        "version": ANALYSIS_PLAN_VERSION,
        "max_metrics_per_plan": MAX_ANALYSIS_METRICS,
        "operations": sorted(item.value for item in AnalysisOperation),
        "time_modes": sorted(item.value for item in ACTIVE_ANALYSIS_TIME_MODES),
        "period_comparison_unsupported_aggregations": sorted(
            PERIOD_COMPARISON_UNSUPPORTED_AGGREGATIONS
        ),
        "ranking_tie_breaker": "all_dimensions_ascending",
    }


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


@dataclass(frozen=True, order=True)
class PlannedFilter:
    """값을 노출하지 않고 서버 소유 파라미터에 결속한 필터 predicate다."""

    asset_fqn: str
    column: str
    operator: str
    parameter: str

    @property
    def qualified(self) -> str:
        """필터가 참조하는 완전 수식 필드 이름을 반환한다."""

        return f"{self.asset_fqn}.{self.column}"

    def as_dict(self) -> dict[str, str]:
        """원시 값 없이 검증 가능한 필터 계획을 직렬화한다."""

        return {
            "asset_fqn": self.asset_fqn,
            "column": self.column,
            "operator": self.operator,
            "parameter": self.parameter,
        }


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
    filter_fields: tuple[PlannedFilter, ...]
    time_mode: AnalysisTimeMode
    time_fields: tuple[PlannedField, ...]
    time_bucket: str
    period_parameters: tuple[tuple[str, str], ...]
    snapshot_parameter: str | None
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
            "snapshot_parameter": self.snapshot_parameter,
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
    filters = _requested_filter_fields(
        structured_request.get("filter_fields"),
        schemas,
        contracts,
    )
    dimensions = _without_constant_aggregate_dimensions(
        dimensions,
        structured_request,
    )
    allowed_dimensions = _shared_dimensions(output_metric_ids, rules)
    if any(item.qualified not in allowed_dimensions for item in dimensions):
        raise _error(
            AnalysisPlanErrorCode.DIMENSION_NOT_BOUND,
            "요청 차원이 선택 지표의 source asset에 승인된 물리 필드로 binding되지 않았습니다.",
        )

    operation = _operation(structured_request, dimensions, output_metric_ids, rules)
    result_limit = _result_limit(operation, structured_request, contracts)
    time_mode, time_fields, time_bucket, periods, snapshot_parameter = _time_contract(
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
        "snapshot_parameter": snapshot_parameter,
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
        snapshot_parameter=snapshot_parameter,
        result_limit=result_limit,
        query_strategy=values["query_strategy"],
        joins=planned_joins,
        context_package_hash=values["context_package_hash"],
        checksum=checksum,
    )


def validate_analysis_plan_structure(value: object) -> None:
    """Runtime package와 무관한 sealed AnalysisPlan의 중첩 형태·조합을 검증한다."""

    if (
        not isinstance(value, Mapping)
        or set(value) != ANALYSIS_PLAN_FIELDS
        or value.get("version") != ANALYSIS_PLAN_VERSION
    ):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan version 또는 필드 계약이 일치하지 않습니다.",
        )
    identity = {
        name: value[name] for name in ANALYSIS_PLAN_FIELDS - {"checksum"}
    }
    if value.get("checksum") != _checksum(identity):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan checksum이 sealed payload와 일치하지 않습니다.",
        )
    try:
        operation = AnalysisOperation(str(value["operation"]))
        time_mode = AnalysisTimeMode(str(value["time_mode"]))
        array_fields = (
            "output_metric_ids",
            "dependency_metric_ids",
            "dimension_fields",
            "filter_fields",
            "time_fields",
            "period_parameters",
            "joins",
        )
        if any(not isinstance(value[name], list) for name in array_fields):
            raise TypeError("AnalysisPlan array field must be a list")
        dimensions = tuple(_field_from_payload(item) for item in value["dimension_fields"])
        filters = tuple(_filter_from_payload(item) for item in value["filter_fields"])
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
        snapshot_parameter = value["snapshot_parameter"]
    except (KeyError, TypeError, ValueError) as error:
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan payload 값을 typed 계약으로 해석할 수 없습니다.",
        ) from error
    raw_field_items = (
        *value["dimension_fields"],
        *value["time_fields"],
        *value["filter_fields"],
    )
    if (
        any(
            not isinstance(item, Mapping)
            or not all(isinstance(item.get(key), str) for key in ("asset_fqn", "column"))
            or len(str(item["asset_fqn"]).split(".")) != 3
            or any(not part for part in str(item["asset_fqn"]).split("."))
            for item in raw_field_items
        )
        or any(not isinstance(item, str) or not item for item in value["output_metric_ids"])
        or any(not isinstance(item, str) or not item for item in value["dependency_metric_ids"])
        or len(dimensions) != len(value["dimension_fields"])
        or len(filters) != len(value["filter_fields"])
        or len(time_fields) != len(value["time_fields"])
        or len(joins) != len(value["joins"])
        or len(periods) != len(value["period_parameters"])
        or (
            snapshot_parameter is not None
            and not _valid_parameter_name(snapshot_parameter)
        )
    ):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan 배열에 유효하지 않은 항목이 포함되어 있습니다.",
        )
    if (
        not output_ids
        or len(output_ids) > MAX_ANALYSIS_METRICS
        or len(output_ids) != len(set(output_ids))
        or not dependency_ids
        or len(dependency_ids) != len(set(dependency_ids))
        or not set(output_ids).issubset(dependency_ids)
        or not time_fields
        or len(dimensions) != len(set(dimensions))
        or len(filters) != len(set(filters))
        or len(time_fields) != len(set(time_fields))
    ):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan metric·field 항목은 비어 있지 않고 고유해야 합니다.",
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
    _validate_operation_shape(operation, dimensions)
    if (operation in {AnalysisOperation.TOP_N, AnalysisOperation.BOTTOM_N}) != (
        result_limit is not None
    ) or (result_limit is not None and result_limit > 100):
        raise _error(
            AnalysisPlanErrorCode.INVALID_OPERATION,
            "AnalysisPlan 연산과 result_limit 조합이 유효하지 않습니다.",
        )
    bucket = value["time_bucket"]
    if not isinstance(bucket, str) or (
        operation is AnalysisOperation.TIME_TREND
        and (time_mode is not AnalysisTimeMode.RANGE or bucket not in ANALYSIS_TIME_BUCKETS)
    ) or (
        operation is not AnalysisOperation.TIME_TREND and bucket != "none"
    ):
        raise _error(
            AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
            "AnalysisPlan operation과 time bucket 조합이 유효하지 않습니다.",
        )
    parameter_names = [item.parameter for item in filters]
    parameter_names.extend(name for pair in periods for name in pair)
    if snapshot_parameter is not None:
        parameter_names.append(snapshot_parameter)
    if (
        any(not _valid_parameter_name(name) for name in parameter_names)
        or len(parameter_names) != len(set(parameter_names))
    ):
        raise _error(
            AnalysisPlanErrorCode.PERIOD_CONTRACT_MISMATCH,
            "AnalysisPlan parameter 이름은 유효하고 고유해야 합니다.",
        )
    if time_mode is AnalysisTimeMode.RANGE:
        expected_period_count = (
            2 if operation is AnalysisOperation.PERIOD_COMPARISON else 1
        )
        time_shape_valid = (
            len(periods) == expected_period_count and snapshot_parameter is None
        )
    else:
        time_shape_valid = (
            not periods
            and snapshot_parameter is not None
            and operation
            not in {AnalysisOperation.TIME_TREND, AnalysisOperation.PERIOD_COMPARISON}
        )
    if not time_shape_valid:
        raise _error(
            AnalysisPlanErrorCode.PERIOD_CONTRACT_MISMATCH,
            "AnalysisPlan time mode와 period·snapshot parameter가 일치하지 않습니다.",
        )
    join_ids = [item.join_id for item in joins]
    if (
        len(join_ids) != len(set(join_ids))
        or any(
            not isinstance(item, Mapping)
            or not all(
                isinstance(item.get(key), str)
                for key in ("join_id", "plan", "reason")
            )
            for item in value["joins"]
        )
        or any(
            not item.join_id
            or item.plan not in {member.value for member in FanoutPlan}
            or not item.reason
            for item in joins
        )
        or not isinstance(value["query_strategy"], str)
        or not value["query_strategy"]
        or not isinstance(value["context_package_hash"], str)
        or len(value["context_package_hash"]) != 64
        or any(character not in "0123456789abcdef" for character in value["context_package_hash"])
    ):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan JOIN·query strategy·package hash 형태가 유효하지 않습니다.",
        )


def _valid_parameter_name(value: object) -> bool:
    """SQL placeholder 이름을 소문자 snake_case 식별자로 제한한다."""

    return (
        isinstance(value, str)
        and bool(value)
        and "a" <= value[0] <= "z"
        and all(character == "_" or character.isdigit() or "a" <= character <= "z" for character in value)
    )


def validate_analysis_plan_payload(value: object, package: object) -> AnalysisPlan:
    """캐시나 단계 사이에서 전달된 계획이 현재 Context와 동일한지 재컴파일해 검증한다."""

    validate_analysis_plan_structure(value)
    assert isinstance(value, Mapping)
    if value.get("context_package_hash") != getattr(package, "package_hash", None):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan checksum이 현재 Runtime Context와 일치하지 않습니다.",
        )
    operation = AnalysisOperation(str(value["operation"]))
    time_mode = AnalysisTimeMode(str(value["time_mode"]))
    dimensions = tuple(_field_from_payload(item) for item in value["dimension_fields"])
    filters = tuple(_filter_from_payload(item) for item in value["filter_fields"])
    time_fields = tuple(_field_from_payload(item) for item in value["time_fields"])
    joins = tuple(
        PlannedJoin(str(item["join_id"]), str(item["plan"]), str(item["reason"]))
        for item in value["joins"]
    )
    periods = tuple(
        (str(item["start_parameter"]), str(item["end_parameter"]))
        for item in value["period_parameters"]
    )
    output_ids = tuple(value["output_metric_ids"])
    dependency_ids = tuple(value["dependency_metric_ids"])
    snapshot_parameter = value["snapshot_parameter"]
    result_limit = value["result_limit"]
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
        != _validated_planned_filters(value["filter_fields"], schemas, contracts)
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
    time_rules = contracts["time_rules"]
    if not isinstance(time_rules, Mapping):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan time_rules가 유효하지 않습니다.",
        )
    governed_mode = str(time_rules.get("mode") or AnalysisTimeMode.RANGE.value)
    if (
        time_mode.value != governed_mode
        or time_mode not in ACTIVE_ANALYSIS_TIME_MODES
        or tuple(sorted(time_fields)) != expected_time_fields
    ):
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
    declared_buckets = {
        _field_from_payload(item["field"]): str(item.get("bucket") or "none")
        for item in time_rules.get("fields", ())
        if isinstance(item, Mapping) and "field" in item
    }
    time_buckets = {declared_buckets.get(item) for item in time_fields}
    planned_bucket = str(value["time_bucket"])
    bucket_valid = (
        operation is AnalysisOperation.TIME_TREND
        and len(time_buckets) == 1
        and next(iter(time_buckets), None) in _SAFE_TIME_ROLLUPS
        and planned_bucket
        in _SAFE_TIME_ROLLUPS[str(next(iter(time_buckets)))]
    ) or (
        operation is not AnalysisOperation.TIME_TREND
        and planned_bucket == "none"
    )
    if None in time_buckets or not bucket_valid:
        raise _error(
            AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
            "AnalysisPlan time bucket이 현재 Runtime Context와 일치하지 않습니다.",
        )
    expected_periods: list[tuple[str, str]] = []
    expected_snapshot_parameter: str | None = None
    if time_mode is AnalysisTimeMode.RANGE:
        expected_periods.append(
            (
                str(time_rules.get("start_parameter") or ""),
                str(time_rules.get("end_parameter") or ""),
            )
        )
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
    else:
        expected_snapshot_parameter = str(time_rules.get("as_of_parameter") or "")
        if (
            time_rules.get("selection") != "max_source_value_lt_as_of"
            or not expected_snapshot_parameter
            or operation
            in {AnalysisOperation.TIME_TREND, AnalysisOperation.PERIOD_COMPARISON}
        ):
            raise _error(
                AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
                "AnalysisPlan 최신 스냅샷 선택 계약이 Runtime Context와 일치하지 않습니다.",
            )
    if (
        periods != tuple(expected_periods)
        or snapshot_parameter != expected_snapshot_parameter
    ):
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
        snapshot_parameter=snapshot_parameter,
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
    if (
        not isinstance(contracts, Mapping)
        or not required.issubset(contracts)
        or set(contracts) - required - {"filter_rules"}
    ):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan Runtime Context 계약 구성이 유효하지 않습니다.",
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


def _requested_filter_fields(
    value: object,
    schemas: Mapping[str, Mapping[str, Any]],
    contracts: Mapping[str, Any],
) -> tuple[PlannedFilter, ...]:
    """검증된 사용자 필터를 값 없이 서버 소유 named parameter에 결속한다."""

    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "filter_fields는 구조화된 필터 배열이어야 합니다.",
        )
    available = _available_filter_rules(contracts, schemas)
    by_signature: dict[tuple[str, str, str], list[PlannedFilter]] = {}
    for item in available:
        by_signature.setdefault(
            (item.asset_fqn, item.column, item.operator), []
        ).append(item)
    for candidates in by_signature.values():
        candidates.sort(key=lambda item: item.parameter)

    fields: list[PlannedFilter] = []
    required = {"asset_fqn", "column", "operator", "value_text"}
    for item in value:
        if not isinstance(item, Mapping) or set(item) != required:
            raise _error(
                AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                "filter_fields 항목은 asset_fqn, column, operator, value_text만 포함해야 합니다.",
            )
        if item["operator"] not in {"eq", "neq"} or not isinstance(
            item["value_text"], str
        ) or not item["value_text"].strip():
            raise _error(
                AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                "filter_fields predicate 계약이 유효하지 않습니다.",
            )
        field = _field_from_payload(
            {"asset_fqn": item["asset_fqn"], "column": item["column"]}
        )
        schema = schemas.get(field.asset_fqn)
        if schema is None or field.column not in schema["fields"]:
            raise _error(
                AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                "filter_fields가 승인된 asset schema 범위를 벗어났습니다.",
            )
        signature = (field.asset_fqn, field.column, str(item["operator"]))
        candidates = by_signature.get(signature, [])
        if not candidates:
            raise _error(
                AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                "filter_fields predicate에 대응하는 서버 소유 파라미터가 없습니다.",
            )
        fields.append(candidates.pop(0))
    if len(fields) != len(set(fields)):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "filter_fields에는 중복 predicate를 포함할 수 없습니다.",
        )
    return tuple(sorted(fields))


def _validated_planned_filters(
    value: object,
    schemas: Mapping[str, Mapping[str, Any]],
    contracts: Mapping[str, Any],
) -> tuple[PlannedFilter, ...]:
    """직렬화된 필터 계획이 현재 Runtime Context의 승인 predicate인지 검증한다."""

    if not isinstance(value, (list, tuple)):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan filter_fields는 배열이어야 합니다.",
        )
    filters = tuple(_filter_from_payload(item) for item in value)
    available = set(_available_filter_rules(contracts, schemas))
    if len(filters) != len(set(filters)) or not set(filters).issubset(available):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "AnalysisPlan filter predicate가 현재 Runtime Context와 일치하지 않습니다.",
        )
    return tuple(sorted(filters))


def _available_filter_rules(
    contracts: Mapping[str, Any],
    schemas: Mapping[str, Mapping[str, Any]],
) -> tuple[PlannedFilter, ...]:
    """asset-level 필터를 우선하고 구버전 계약은 Metric 필터로 제한해 호환한다."""

    raw_rules = contracts.get("filter_rules")
    legacy_fallback = raw_rules is None
    if legacy_fallback:
        metric_rules = contracts.get("metric_rules")
        raw_rules = [
            item
            for metric in (metric_rules if isinstance(metric_rules, list) else ())
            if isinstance(metric, Mapping)
            for item in metric.get("required_filters", ())
        ]
    if not isinstance(raw_rules, list):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "Runtime Context filter_rules가 배열이 아닙니다.",
        )
    parameter_contract = contracts.get("parameter_contract")
    parameters = (
        parameter_contract.get("parameters")
        if isinstance(parameter_contract, Mapping)
        else None
    )
    if not isinstance(parameters, list):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "Runtime Context parameter_contract가 유효하지 않습니다.",
        )
    filter_parameters = {
        str(item.get("name"))
        for item in parameters
        if isinstance(item, Mapping) and item.get("scope") == "filter"
    }
    result: list[PlannedFilter] = []
    for item in raw_rules:
        if not isinstance(item, Mapping) or set(item) != {
            "field",
            "operator",
            "parameter",
        }:
            raise _error(
                AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                "Runtime Context filter rule 형식이 유효하지 않습니다.",
            )
        field = _field_from_payload(item["field"])
        operator = str(item["operator"])
        parameter = str(item["parameter"])
        schema = schemas.get(field.asset_fqn)
        if (
            schema is None
            or field.column not in schema["fields"]
            or operator not in {"eq", "neq"}
            or parameter not in filter_parameters
        ):
            raise _error(
                AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
                "Runtime Context filter rule이 schema 또는 parameter 범위를 벗어났습니다.",
            )
        result.append(
            PlannedFilter(field.asset_fqn, field.column, operator, parameter)
        )
    if len(result) != len(set(result)) and not legacy_fallback:
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "Runtime Context filter rule이 중복되었습니다.",
        )
    return tuple(sorted(set(result)))


def _without_constant_aggregate_dimensions(
    dimensions: tuple[PlannedField, ...],
    request: Mapping[str, object],
) -> tuple[PlannedField, ...]:
    """동등 필터로 고정된 필드를 전체 집계의 불필요한 GROUP BY에서 제외한다.

    Node 1은 같은 업무 필드를 필터와 차원 후보로 함께 반환할 수 있다. ``eq`` 필터가
    적용된 필드는 결과 집합 전체에서 상수이므로 aggregate의 그룹 키로 남겨도 값은
    달라지지 않지만, 논리 계획의 단일 값 계약에는 어긋난다. 질문 문자열이나 업무 값을
    다시 해석하지 않고 검증된 predicate 구조만 사용해 중복 역할을 제거한다. 필터 자체는
    계획과 Context에 그대로 남으므로 접근 범위와 근거는 보존된다.
    """

    if request.get("analysis_operation") != AnalysisOperation.AGGREGATE.value:
        return dimensions
    raw_filters = request.get("filter_fields")
    if not isinstance(raw_filters, (list, tuple)):
        return dimensions
    constant_fields = {
        PlannedField(str(item["asset_fqn"]), str(item["column"]))
        for item in raw_filters
        if isinstance(item, Mapping) and item.get("operator") == "eq"
    }
    return tuple(item for item in dimensions if item not in constant_fields)


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


def _filter_from_payload(value: object) -> PlannedFilter:
    """직렬화된 필터 predicate를 strict typed 값으로 복원한다."""

    required = {"asset_fqn", "column", "operator", "parameter"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "계획 필터는 asset_fqn, column, operator, parameter만 포함해야 합니다.",
        )
    field = _field_from_payload(
        {"asset_fqn": value["asset_fqn"], "column": value["column"]}
    )
    operator = str(value["operator"])
    parameter = str(value["parameter"])
    if operator not in {"eq", "neq"} or not parameter:
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "계획 필터 operator 또는 parameter가 유효하지 않습니다.",
        )
    return PlannedFilter(field.asset_fqn, field.column, operator, parameter)


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
    str | None,
]:
    time_rules = contracts.get("time_rules")
    if not isinstance(time_rules, Mapping):
        raise _error(
            AnalysisPlanErrorCode.INVALID_RUNTIME_CONTRACT,
            "Runtime time_rules가 유효하지 않습니다.",
        )
    governed_mode = str(time_rules.get("mode") or AnalysisTimeMode.RANGE.value)
    requested_mode = str(request.get("time_mode") or governed_mode)
    try:
        mode = AnalysisTimeMode(requested_mode)
    except ValueError as error:
        raise _error(
            AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
            "요청한 time mode가 현재 AnalysisPlan version에 없습니다.",
        ) from error
    if mode not in ACTIVE_ANALYSIS_TIME_MODES or mode.value != governed_mode:
        raise _error(
            AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
            "요청한 시간 선택 규칙이 활성 Runtime Context에 아직 구현·발행되지 않았습니다.",
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
    if operation is AnalysisOperation.TIME_TREND and (
        mode is not AnalysisTimeMode.RANGE or len(buckets) != 1
    ):
        raise _error(
            AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
            "추이 지표들의 승인 time bucket이 서로 달라 하나의 계획으로 합칠 수 없습니다.",
        )
    requested_bucket = request.get("analysis_time_bucket")
    if operation is AnalysisOperation.TIME_TREND:
        source_bucket = next(iter(buckets))
        if (
            not isinstance(requested_bucket, str)
            or requested_bucket not in ANALYSIS_TIME_BUCKETS
            or source_bucket not in _SAFE_TIME_ROLLUPS
            or requested_bucket not in _SAFE_TIME_ROLLUPS[source_bucket]
        ):
            raise _error(
                AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
                "요청한 시간 grain은 source time bucket에서 안전하게 roll-up할 수 없습니다.",
            )
        bucket = requested_bucket
    else:
        if requested_bucket not in {None, "none"}:
            raise _error(
                AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
                "시간 추이 이외 연산은 analysis time bucket을 지정할 수 없습니다.",
            )
        bucket = "none"
    bound_names = {
        str(item.name) for item in tuple(getattr(package, "parameter_bindings", ()))
    }
    if mode is AnalysisTimeMode.LATEST_SNAPSHOT:
        parameter = str(time_rules.get("as_of_parameter") or "")
        if (
            time_rules.get("selection") != "max_source_value_lt_as_of"
            or operation
            in {AnalysisOperation.TIME_TREND, AnalysisOperation.PERIOD_COMPARISON}
            or not parameter
            or parameter not in bound_names
        ):
            raise _error(
                AnalysisPlanErrorCode.TIME_MODE_NOT_GOVERNED,
                "최신 스냅샷은 승인된 기준일 전 MAX 선택 규칙과 서버 binding을 요구합니다.",
            )
        return mode, fields, bucket, (), parameter
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
    if any(not a or not b or a == b or {a, b} - bound_names for a, b in periods):
        raise _error(
            AnalysisPlanErrorCode.PERIOD_CONTRACT_MISMATCH,
            "AnalysisPlan 기간 파라미터가 서버 소유 binding과 일치하지 않습니다.",
        )
    return mode, fields, bucket, tuple(periods), None


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
        distances = {anchor: 0}
        frontier = [anchor]
        while frontier:
            node = frontier.pop(0)
            for edge in sorted(by_node.get(node, ()), key=lambda item: str(item.id)):
                neighbor = str(edge.right) if str(edge.left) == node else str(edge.left)
                if neighbor not in distances:
                    distances[neighbor] = distances[node] + 1
                    frontier.append(neighbor)
        if target not in distances:
            raise _error(
                AnalysisPlanErrorCode.JOIN_PATH_UNAVAILABLE,
                "분석에 필요한 asset들이 승인된 JOIN graph로 연결되지 않습니다.",
            )
        path_counts = {anchor: 1}
        paths: dict[str, tuple[object, ...] | None] = {anchor: ()}
        for node in sorted(distances, key=lambda item: (distances[item], item)):
            for edge in sorted(by_node.get(node, ()), key=lambda item: str(item.id)):
                neighbor = str(edge.right) if str(edge.left) == node else str(edge.left)
                if distances.get(neighbor) != distances[node] + 1:
                    continue
                previous = path_counts.get(neighbor, 0)
                path_counts[neighbor] = min(2, previous + path_counts.get(node, 0))
                candidate = (
                    (*paths[node], edge) if paths.get(node) is not None else None
                )
                paths[neighbor] = candidate if previous == 0 else None
        path = paths.get(target)
        if path_counts.get(target) != 1 or path is None:
            raise _error(
                AnalysisPlanErrorCode.JOIN_PATH_UNAVAILABLE,
                "분석 asset 사이에 복수 최단 JOIN 경로가 있어 하나를 임의 선택할 수 없습니다.",
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
