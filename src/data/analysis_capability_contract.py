"""DataHub에 발행할 분석 연산·asset별 차원·시간 capability 계약을 검증한다.

이 계약은 기존 Runtime Governance v2 bundle을 변경하지 않는 후방 호환 sidecar다.
후보 파일, DataHub custom aspect, 향후 native semantic entity 중 어떤 저장소를 사용하더라도
동일한 payload를 이 모듈로 컴파일해야 하며, 실제 schema read-back 밖의 binding은 거부한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

from src.data.governance_contract import canonical_sha256


ANALYSIS_CAPABILITY_VERSION = "ANSWERVICE-ANALYSIS-CAPABILITY-v1"
ANALYSIS_CAPABILITY_RELEASE_VERSION = "AnswerviceAnalysisCapabilityRelease.v1"
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
    "latest_snapshot": "max_source_value_lt_as_of",
}
COMPARISON_START_PARAMETER = "comparison_start_date"
COMPARISON_END_PARAMETER = "comparison_end_date"


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
    data_available_from: date | None = None
    data_available_through: date | None = None
    conversation_default_operation: str | None = None


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


@dataclass(frozen=True)
class AnalysisCapabilityRelease:
    """봉인 checksum과 catalog identity에 결속된 런타임 capability sidecar다."""

    catalog_release_id: str
    catalog_sha256: str
    canonical_sha256: str
    content_sha256: str
    contract: AnalysisCapabilityContract

    def contract_for_catalog(
        self,
        catalog_release_id: str,
        catalog_sha256: str,
        canonical_sha256: str,
    ) -> AnalysisCapabilityContract:
        """현재 canonical catalog와 exact identity가 같은 계약만 반환한다."""

        if (
            self.catalog_release_id != catalog_release_id
            or self.catalog_sha256 != catalog_sha256
            or self.canonical_sha256 != canonical_sha256
        ):
            raise AnalysisCapabilityError(
                "analysis capability release differs from the runtime catalog"
            )
        return self.contract


def load_analysis_capability_release(
    path: str | Path,
    *,
    expected_catalog_release: str | None = None,
) -> AnalysisCapabilityRelease:
    """봉인 sidecar의 구조·checksum을 검증하고 runtime catalog 결속 정보를 보존한다.

    파일 안의 field 선언은 컴파일러의 구조 검증에만 사용한다. 요청 시점에는
    ``apply_analysis_capability_contract``가 DataHub runtime asset의 실제 time/dimension
    binding을 다시 대조하고, ``contract_for_catalog``가 active catalog receipt를 확인한다.
    """

    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AnalysisCapabilityError(
            "analysis capability release is unreadable"
        ) from error
    root = _mapping(document, "analysis capability release")
    _exact_keys(
        root,
        {
            "schema_version",
            "status",
            "catalog_release_id",
            "catalog_sha256",
            "canonical_sha256",
            "contract",
            "content_sha256",
        },
        "analysis capability release",
    )
    catalog_release_id = _text(
        root["catalog_release_id"], "analysis capability catalog release"
    )
    if (
        root["schema_version"] != ANALYSIS_CAPABILITY_RELEASE_VERSION
        or root["status"] != "SEALED"
        or (
            expected_catalog_release is not None
            and catalog_release_id != expected_catalog_release
        )
    ):
        raise AnalysisCapabilityError(
            "analysis capability release identity is invalid"
        )
    catalog_checksum = _sha256(
        root["catalog_sha256"], "analysis capability catalog checksum"
    )
    canonical_checksum = _sha256(
        root["canonical_sha256"], "analysis capability canonical checksum"
    )
    content_checksum = _sha256(
        root["content_sha256"], "analysis capability content checksum"
    )
    payload = {key: value for key, value in root.items() if key != "content_sha256"}
    if canonical_sha256(payload) != content_checksum:
        raise AnalysisCapabilityError(
            "analysis capability release checksum differs"
        )

    available_fields, dimension_columns = _declared_bindings(root["contract"])
    contract = compile_analysis_capability_contract(
        root["contract"],
        available_fields_by_asset=available_fields,
        dimension_family_columns=dimension_columns,
    )
    return AnalysisCapabilityRelease(
        catalog_release_id=catalog_release_id,
        catalog_sha256=catalog_checksum,
        canonical_sha256=canonical_checksum,
        content_sha256=content_checksum,
        contract=contract,
    )


def apply_analysis_capability_contract(
    contract: AnalysisCapabilityContract,
    assets: list[dict[str, object]],
) -> list[dict[str, object]]:
    """검증된 App sidecar의 per-asset 연산 계약만 runtime asset에 결속한다.

    DataHub가 소유한 물리 field·time mode·dimension binding과 sidecar가 정확히
    일치할 때만 비교 윈도우를 추가한다. sidecar에 없는 asset이나 snapshot asset은
    확장하지 않으며, 이미 존재하는 서로 다른 계약도 덮어쓰지 않는다.
    """

    result: list[dict[str, object]] = []
    comparison_enabled = "period_comparison" in contract.operations
    expected_window = {
        "start_parameter": COMPARISON_START_PARAMETER,
        "end_parameter": COMPARISON_END_PARAMETER,
    }
    for raw_asset in assets:
        asset = dict(raw_asset)
        fqn = str(asset.get("fqn") or "")
        capability = contract.asset(fqn)
        if capability is None:
            result.append(asset)
            continue
        metadata = asset.get("time_metadata")
        dimensions = asset.get("dimensions")
        if not isinstance(metadata, Mapping) or not isinstance(dimensions, list):
            raise AnalysisCapabilityError(
                "runtime asset is missing governed time or dimension metadata"
            )
        mode = str(metadata.get("mode") or "range")
        fields = metadata.get("fields")
        if mode != capability.time_mode or not isinstance(fields, list):
            raise AnalysisCapabilityError(
                "analysis capability time mode differs from runtime metadata"
            )
        matching_time_fields = [
            item
            for item in fields
            if isinstance(item, Mapping)
            and isinstance(item.get("field"), Mapping)
            and item["field"].get("asset_fqn") == fqn
            and item["field"].get("column") == capability.time_field
        ]
        if len(matching_time_fields) != 1:
            raise AnalysisCapabilityError(
                "analysis capability time field differs from runtime metadata"
            )
        dimension_columns: dict[str, set[str]] = {}
        for item in dimensions:
            if (
                isinstance(item, Mapping)
                and item.get("asset_fqn") == fqn
                and isinstance(item.get("id"), str)
                and isinstance(item.get("column"), str)
            ):
                dimension_columns.setdefault(str(item["id"]), set()).add(
                    str(item["column"])
                )
        if any(
            not set(binding.columns) <= dimension_columns.get(binding.id, set())
            for binding in capability.dimensions
        ):
            raise AnalysisCapabilityError(
                "analysis capability dimension differs from runtime metadata"
            )
        if comparison_enabled and mode == "range":
            existing = metadata.get("comparison_window")
            if existing is not None and existing != expected_window:
                raise AnalysisCapabilityError(
                    "runtime comparison window differs from the sealed capability"
                )
            enriched = dict(metadata)
            enriched["comparison_window"] = dict(expected_window)
            asset["time_metadata"] = enriched
        if capability.data_available_from is not None:
            available_from = capability.data_available_from.isoformat()
            available_through = capability.data_available_through
            if available_through is None:  # pragma: no cover - compiler invariant
                raise AnalysisCapabilityError(
                    "analysis capability availability range is incomplete"
                )
            through = available_through.isoformat()
            expected_values = {
                "data_available_from": available_from,
                "data_available_through": through,
                # RuntimeContextPackage의 기존 evidence cutoff 계약과 같은
                # release-bound watermark를 사용한다. wall clock과는 별개다.
                "evidence_cutoff": through,
            }
            if any(
                asset.get(name) not in (None, value)
                for name, value in expected_values.items()
            ):
                raise AnalysisCapabilityError(
                    "runtime data availability differs from the sealed capability"
                )
            asset.update(expected_values)
        if capability.conversation_default_operation is not None:
            default_operation = capability.conversation_default_operation
            if asset.get("conversation_default_operation") not in (
                None,
                default_operation,
            ):
                raise AnalysisCapabilityError(
                    "runtime Conversation default operation differs from the sealed capability"
                )
            asset["conversation_default_operation"] = default_operation
        result.append(asset)
    return result


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
        required_asset_keys = {"fqn", "time", "dimensions"}
        optional_asset_keys = {
            "data_availability",
            "conversation_default_operation",
        }
        if not required_asset_keys <= set(asset) or not set(asset) <= (
            required_asset_keys | optional_asset_keys
        ):
            raise AnalysisCapabilityError(
                f"analysis asset[{index}] fields do not match the contract"
            )
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

        conversation_default_operation: str | None = None
        if asset.get("conversation_default_operation") is not None:
            conversation_default_operation = _text(
                asset["conversation_default_operation"],
                f"{fqn}.conversation_default_operation",
            )
            # Only a governed range time series can be a generally reusable
            # presentation-ready default. Ranking, comparison and breakdown
            # require additional user slots and must never be synthesized.
            if (
                conversation_default_operation != "time_trend"
                or mode != "range"
                or conversation_default_operation not in operations
            ):
                raise AnalysisCapabilityError(
                    "analysis capability Conversation default operation is unsupported"
                )

        available_from: date | None = None
        available_through: date | None = None
        raw_availability = asset.get("data_availability")
        if raw_availability is not None:
            availability = _mapping(raw_availability, f"{fqn}.data_availability")
            _exact_keys(
                availability,
                {"data_available_from", "data_available_through"},
                f"{fqn}.data_availability",
            )
            if mode != "range":
                raise AnalysisCapabilityError(
                    "analysis capability data availability requires range time mode"
                )
            try:
                available_from = date.fromisoformat(
                    _text(
                        availability["data_available_from"],
                        f"{fqn}.data_availability.data_available_from",
                    )
                )
                available_through = date.fromisoformat(
                    _text(
                        availability["data_available_through"],
                        f"{fqn}.data_availability.data_available_through",
                    )
                )
            except ValueError as error:
                raise AnalysisCapabilityError(
                    "analysis capability data availability date is invalid"
                ) from error
            if available_from > available_through:
                raise AnalysisCapabilityError(
                    "analysis capability data availability range is invalid"
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
                data_available_from=available_from,
                data_available_through=available_through,
                conversation_default_operation=conversation_default_operation,
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


def _sha256(value: object, context: str) -> str:
    checksum = _text(value, context)
    if len(checksum) != 64 or any(
        character not in "0123456789abcdef" for character in checksum
    ):
        raise AnalysisCapabilityError(f"{context} must be a lowercase SHA-256")
    return checksum


def _declared_bindings(
    value: object,
) -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """sidecar 자체의 선언을 구조 컴파일 입력으로 투영한다."""

    root = _mapping(value, "analysis capability")
    available: dict[str, set[str]] = {}
    dimensions: dict[str, set[str]] = {}
    for index, raw_asset in enumerate(_list(root.get("assets"), "analysis assets")):
        asset = _mapping(raw_asset, f"analysis asset[{index}]")
        fqn = _text(asset.get("fqn"), f"analysis asset[{index}].fqn")
        time = _mapping(asset.get("time"), f"{fqn}.time")
        available.setdefault(fqn, set()).add(
            _text(time.get("field"), f"{fqn}.time.field")
        )
        for dimension_index, raw_dimension in enumerate(
            _list(asset.get("dimensions"), f"{fqn}.dimensions")
        ):
            dimension = _mapping(
                raw_dimension,
                f"{fqn}.dimensions[{dimension_index}]",
            )
            dimension_id = _text(
                dimension.get("id"), f"{fqn}.dimensions[{dimension_index}].id"
            )
            columns = _unique_texts(
                dimension.get("columns"),
                f"{fqn}.dimensions[{dimension_index}].columns",
            )
            available[fqn].update(columns)
            dimensions.setdefault(dimension_id, set()).update(columns)
    return (
        {fqn: frozenset(fields) for fqn, fields in available.items()},
        {name: frozenset(columns) for name, columns in dimensions.items()},
    )


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    context: str,
) -> None:
    if set(value) != expected:
        raise AnalysisCapabilityError(f"{context} fields do not match the contract")
