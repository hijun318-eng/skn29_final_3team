"""DataHub에 발행할 분석 연산·asset별 차원·시간 capability 계약을 검증한다.

이 계약은 기존 Runtime Governance v2 bundle을 변경하지 않는 후방 호환 sidecar다.
후보 파일, DataHub custom aspect, 향후 native semantic entity 중 어떤 저장소를 사용하더라도
동일한 payload를 이 모듈로 컴파일해야 하며, 실제 schema read-back 밖의 binding은 거부한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


ANALYSIS_CAPABILITY_VERSION = "ANSWERVICE-ANALYSIS-CAPABILITY-v1"
ANALYSIS_OPERATIONS = frozenset(
    {
        "aggregate",
        "breakdown",
        "time_trend",
        "top_n",
        "bottom_n",
        "period_comparison",
    }
)
TIME_MODES = frozenset({"range", "latest_snapshot"})
TIME_DEFAULTS = {
    "range": "required_period",
    "latest_snapshot": "max_source_value_lte_as_of",
}


class AnalysisCapabilityError(ValueError):
    """분석 capability sidecar를 실제 asset schema에 안전하게 결속할 수 없음을 나타낸다."""


@dataclass(frozen=True)
class DimensionBinding:
    """업무 차원 하나를 특정 asset의 하나 이상 물리 컬럼에 결속한다."""

    id: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class AssetAnalysisCapability:
    """한 asset에서 허용되는 차원과 시간 선택 의미를 보존한다."""

    asset_fqn: str
    time_mode: str
    time_field: str
    time_default: str
    dimensions: tuple[DimensionBinding, ...]


@dataclass(frozen=True)
class AnalysisCapabilityContract:
    """한 semantic release에 결합되는 범용 분석 연산 capability sidecar다."""

    version: str
    max_metrics_per_plan: int
    operations: tuple[str, ...]
    assets: tuple[AssetAnalysisCapability, ...]

    def asset(self, fqn: str) -> AssetAnalysisCapability | None:
        """FQN이 일치하는 asset capability를 반환한다."""

        return next((item for item in self.assets if item.asset_fqn == fqn), None)


def compile_analysis_capability_contract(
    value: object,
    *,
    available_fields_by_asset: Mapping[str, frozenset[str] | set[str]],
    dimension_family_columns: Mapping[str, frozenset[str] | set[str]],
) -> AnalysisCapabilityContract:
    """sidecar payload를 실제 schema와 차원 family 범위에 대조해 typed 계약으로 만든다."""

    root = _mapping(value, "analysis capability")
    _exact_keys(
        root,
        {"version", "max_metrics_per_plan", "operations", "assets"},
        "analysis capability",
    )
    if root["version"] != ANALYSIS_CAPABILITY_VERSION:
        raise AnalysisCapabilityError("analysis capability version is unsupported")
    maximum = root["max_metrics_per_plan"]
    if (
        not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or not 1 <= maximum <= 4
    ):
        raise AnalysisCapabilityError(
            "analysis capability max_metrics_per_plan must be between 1 and 4"
        )
    operations = _unique_texts(root["operations"], "analysis operations")
    if not operations or not set(operations) <= ANALYSIS_OPERATIONS:
        raise AnalysisCapabilityError("analysis capability operation is unsupported")

    assets: list[AssetAnalysisCapability] = []
    seen_assets: set[str] = set()
    for index, raw_asset in enumerate(_list(root["assets"], "analysis assets")):
        asset = _mapping(raw_asset, f"analysis asset[{index}]")
        _exact_keys(asset, {"fqn", "time", "dimensions"}, f"analysis asset[{index}]")
        fqn = _text(asset["fqn"], f"analysis asset[{index}].fqn")
        available = available_fields_by_asset.get(fqn)
        if fqn in seen_assets or available is None:
            raise AnalysisCapabilityError(
                "analysis capability asset is duplicate or outside schema read-back"
            )
        seen_assets.add(fqn)
        time = _mapping(asset["time"], f"{fqn}.time")
        _exact_keys(time, {"mode", "field", "default"}, f"{fqn}.time")
        mode = _text(time["mode"], f"{fqn}.time.mode")
        field = _text(time["field"], f"{fqn}.time.field")
        default = _text(time["default"], f"{fqn}.time.default")
        if (
            mode not in TIME_MODES
            or default != TIME_DEFAULTS[mode]
            or field not in available
        ):
            raise AnalysisCapabilityError(
                "analysis capability time binding is outside its asset schema or mode"
            )

        dimensions: list[DimensionBinding] = []
        seen_dimensions: set[str] = set()
        for dimension_index, raw_dimension in enumerate(
            _list(asset["dimensions"], f"{fqn}.dimensions")
        ):
            dimension = _mapping(
                raw_dimension,
                f"{fqn}.dimensions[{dimension_index}]",
            )
            _exact_keys(
                dimension,
                {"id", "columns"},
                f"{fqn}.dimensions[{dimension_index}]",
            )
            dimension_id = _text(
                dimension["id"], f"{fqn}.dimensions[{dimension_index}].id"
            )
            columns = _unique_texts(
                dimension["columns"],
                f"{fqn}.dimensions[{dimension_index}].columns",
            )
            family_columns = dimension_family_columns.get(dimension_id)
            if (
                dimension_id in seen_dimensions
                or not columns
                or family_columns is None
                or not set(columns) <= set(available)
                or not set(columns) <= set(family_columns)
            ):
                raise AnalysisCapabilityError(
                    "analysis dimension binding is duplicate or outside family/asset schema"
                )
            seen_dimensions.add(dimension_id)
            dimensions.append(DimensionBinding(dimension_id, columns))
        assets.append(
            AssetAnalysisCapability(
                asset_fqn=fqn,
                time_mode=mode,
                time_field=field,
                time_default=default,
                dimensions=tuple(sorted(dimensions, key=lambda item: item.id)),
            )
        )
    if not assets:
        raise AnalysisCapabilityError("analysis capability requires at least one asset")
    return AnalysisCapabilityContract(
        version=ANALYSIS_CAPABILITY_VERSION,
        max_metrics_per_plan=maximum,
        operations=tuple(sorted(operations)),
        assets=tuple(sorted(assets, key=lambda item: item.asset_fqn)),
    )


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AnalysisCapabilityError(f"{context} must be an object")
    return value


def _list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise AnalysisCapabilityError(f"{context} must be an array")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnalysisCapabilityError(f"{context} must be non-empty text")
    return value


def _unique_texts(value: object, context: str) -> tuple[str, ...]:
    values = tuple(_text(item, context) for item in _list(value, context))
    if len(values) != len(set(values)):
        raise AnalysisCapabilityError(f"{context} must contain unique values")
    return values


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    context: str,
) -> None:
    if set(value) != expected:
        raise AnalysisCapabilityError(f"{context} fields do not match the contract")
