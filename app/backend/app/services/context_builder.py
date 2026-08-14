from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from enum import Enum


class ContextBuildErrorCode(str, Enum):
    INVALID_METADATA = "INVALID_METADATA"
    DUPLICATE_ASSET = "DUPLICATE_ASSET"
    DATASET_LIMIT_EXCEEDED = "DATASET_LIMIT_EXCEEDED"
    COLUMN_LIMIT_EXCEEDED = "COLUMN_LIMIT_EXCEEDED"
    TOKEN_LIMIT_EXCEEDED = "TOKEN_LIMIT_EXCEEDED"
    INVALID_METRIC = "INVALID_METRIC"
    DUPLICATE_METRIC = "DUPLICATE_METRIC"
    PERIOD_REQUIRED = "PERIOD_REQUIRED"


class ContextBuildError(ValueError):
    def __init__(
        self,
        code: ContextBuildErrorCode,
        message: str,
        suggestions: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.suggestions = suggestions


@dataclass(frozen=True)
class ContextRequiredFilter:
    field: str
    operator: str
    value: str | bool | int | float
    value_type: str = ""

    def __post_init__(self) -> None:
        value_type = self.value_type or _value_type(self.value)
        if self.operator != "eq" or not _typed_value_is_valid(value_type, self.value):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "Required filter는 승인된 type의 eq 값이어야 합니다.",
            )
        object.__setattr__(self, "value_type", value_type)


@dataclass(frozen=True)
class ContextParameterBinding:
    name: str
    value_type: str
    value: str | bool | int | float

    def __post_init__(self) -> None:
        if not self.name or not _typed_value_is_valid(self.value_type, self.value):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Context parameter binding의 name·type·value가 유효하지 않습니다.",
            )


@dataclass(frozen=True)
class ContextMetricFormula:
    operator: str
    operands: tuple[str, ...]

    def __post_init__(self) -> None:
        valid_arity = (
            len(self.operands) == 2
            if self.operator != "add"
            else 2 <= len(self.operands) <= 8
        )
        if (
            self.operator not in {"add", "subtract", "multiply", "divide"}
            or not valid_arity
            or any(not _is_identifier(operand) for operand in self.operands)
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "Metric formula는 승인된 연산자와 2~8개의 명시적 operand를 사용해야 합니다.",
            )


@dataclass(frozen=True)
class ContextMetric:
    id: str
    asset_fqn: str
    field: str
    aggregation: str
    time_field: str
    required_filters: tuple[ContextRequiredFilter, ...]
    result_field: str = ""
    unit: str = ""
    formula: ContextMetricFormula | None = None
    reduction: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_field", self.result_field or self.id)
        default_reduction = (
            "sum"
            if self.aggregation.lower()
            in {"sum", "count", "count_distinct", "negative_sum", "derived_sum"}
            else {
                "min": "min",
                "max": "max",
                "avg": "average",
                "average": "average",
            }.get(self.aggregation.lower(), "scalar")
        )
        object.__setattr__(self, "reduction", self.reduction or default_reduction)
        if (
            not _is_identifier(self.result_field)
            or self.reduction
            not in {
                "sum",
                "min",
                "max",
                "average",
                "scalar",
                "weighted_ratio",
                "recompute",
            }
            or (
                self.formula is not None
                and self.reduction not in {"weighted_ratio", "recompute", "sum"}
            )
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "Metric result field, formula와 reduction 계약이 유효하지 않습니다.",
            )


@dataclass(frozen=True)
class ContextMetricTerm:
    id: str
    urn: str
    label: str
    aliases: tuple[str, ...]
    definition: str
    unit: str
    version: str

    def __post_init__(self) -> None:
        if (
            not _is_identifier(self.id)
            or self.urn != f"urn:li:glossaryTerm:{self.id}"
            or not self.label.strip()
            or not self.aliases
            or self.label not in self.aliases
            or any(not alias.strip() for alias in self.aliases)
            or not self.definition.strip()
            or not self.unit.strip()
            or not self.version.strip()
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "DataHub Metric Glossary Term 계약이 유효하지 않습니다.",
            )


@dataclass(frozen=True)
class ContextAsset:
    urn: str
    fqn: str
    columns: tuple[str, ...]
    join_ids: tuple[str, ...] = ()
    metrics: tuple[ContextMetric, ...] = ()
    metric_registry_required: bool = False
    required_filters: tuple[ContextRequiredFilter, ...] = ()
    column_types: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.urn.strip() or not self.fqn.strip():
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Context asset에는 URN과 FQN이 필요합니다.",
            )
        if not self.columns or any(not column.strip() for column in self.columns):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Context asset에는 하나 이상의 유효한 column이 필요합니다.",
            )
        if any(
            name not in self.columns or not native_type.strip()
            for name, native_type in self.column_types
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Context column type metadata must reference approved columns.",
            )


@dataclass(frozen=True)
class ContextBuildRequest:
    context_release: str
    policy_version: str
    time_version: str
    entitlement_hash: str
    assets: tuple[ContextAsset, ...]
    token_count: int
    model_context_tokens: int
    parameter_bindings: tuple[ContextParameterBinding, ...] = ()
    metric_terms: tuple[ContextMetricTerm, ...] = ()


@dataclass(frozen=True)
class ContextPackage:
    context_release: str
    policy_version: str
    time_version: str
    entitlement_hash: str
    assets: tuple[ContextAsset, ...]
    dataset_count: int
    column_count: int
    token_count: int
    token_limit: int
    package_hash: str
    approved_join_ids: tuple[str, ...]
    metrics: tuple[ContextMetric, ...] = ()
    parameter_bindings: tuple[ContextParameterBinding, ...] = ()
    required_filters: tuple[ContextRequiredFilter, ...] = ()
    metric_terms: tuple[ContextMetricTerm, ...] = ()


class ContextPackageBuilder:
    MAX_DATASETS = 8
    MAX_COLUMNS = 60
    MAX_TOKENS = 6_000
    MODEL_CONTEXT_RATIO = 0.25

    def build(
        self,
        request: ContextBuildRequest,
        entitled_asset_urns: frozenset[str],
    ) -> ContextPackage:
        self._validate_request_metadata(request)
        assets = tuple(
            sorted(
                (
                    asset
                    for asset in request.assets
                    if asset.urn in entitled_asset_urns
                ),
                key=lambda asset: (asset.urn, asset.fqn),
            )
        )
        self._validate_unique_assets(assets)
        metrics = tuple(
            sorted(
                (metric for asset in assets for metric in asset.metrics),
                key=lambda metric: (metric.id, metric.asset_fqn),
            )
        )
        metric_terms = tuple(sorted(request.metric_terms, key=lambda term: term.id))
        if len({term.id for term in metric_terms}) != len(metric_terms):
            raise ContextBuildError(
                ContextBuildErrorCode.DUPLICATE_METRIC,
                "DataHub Metric Glossary Term은 중복될 수 없습니다.",
            )
        required_filters = tuple(
            item for asset in assets for item in asset.required_filters
        )
        self._validate_metrics(assets, metrics)
        self._validate_parameter_bindings(request.parameter_bindings)

        dataset_count = len(assets)
        column_count = sum(len(asset.columns) for asset in assets)
        token_limit = min(
            self.MAX_TOKENS,
            int(request.model_context_tokens * self.MODEL_CONTEXT_RATIO),
        )
        self._validate_limits(
            dataset_count=dataset_count,
            column_count=column_count,
            token_count=request.token_count,
            token_limit=token_limit,
        )

        canonical = {
            "context_release": request.context_release,
            "policy_version": request.policy_version,
            "time_version": request.time_version,
            "entitlement_hash": request.entitlement_hash,
            "assets": [
                {
                    "urn": asset.urn,
                    "fqn": asset.fqn,
                    "columns": list(asset.columns),
                    "column_types": dict(asset.column_types),
                    "join_ids": list(asset.join_ids),
                }
                for asset in assets
            ],
            "metrics": [
                {
                    "id": metric.id,
                    "asset_fqn": metric.asset_fqn,
                    "field": metric.field,
                    "aggregation": metric.aggregation,
                    "time_field": metric.time_field,
                    "result_field": metric.result_field,
                    "unit": metric.unit,
                    "formula": (
                        {
                            "operator": metric.formula.operator,
                            "operands": list(metric.formula.operands),
                        }
                        if metric.formula is not None
                        else None
                    ),
                    "reduction": metric.reduction,
                    "required_filters": [
                        {
                            "field": item.field,
                            "operator": item.operator,
                            "value_type": item.value_type,
                            "value": item.value,
                        }
                        for item in metric.required_filters
                    ],
                }
                for metric in metrics
            ],
            "metric_terms": [
                {
                    "id": term.id,
                    "urn": term.urn,
                    "label": term.label,
                    "aliases": list(term.aliases),
                    "definition": term.definition,
                    "unit": term.unit,
                    "version": term.version,
                }
                for term in metric_terms
            ],
            "token_count": request.token_count,
            "parameter_bindings": [
                {
                    "name": item.name,
                    "value_type": item.value_type,
                    "value": item.value,
                }
                for item in request.parameter_bindings
            ],
            "required_filters": [
                {
                    "field": item.field,
                    "operator": item.operator,
                    "value_type": item.value_type,
                    "value": item.value,
                }
                for item in required_filters
            ],
        }
        package_hash = hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return ContextPackage(
            context_release=request.context_release,
            policy_version=request.policy_version,
            time_version=request.time_version,
            entitlement_hash=request.entitlement_hash,
            assets=assets,
            metrics=metrics,
            dataset_count=dataset_count,
            column_count=column_count,
            token_count=request.token_count,
            token_limit=token_limit,
            package_hash=package_hash,
            approved_join_ids=tuple(sorted({join_id for asset in assets for join_id in asset.join_ids})),
            parameter_bindings=request.parameter_bindings,
            required_filters=required_filters,
            metric_terms=metric_terms,
        )

    @staticmethod
    def _validate_parameter_bindings(
        bindings: tuple[ContextParameterBinding, ...],
    ) -> None:
        names = [item.name for item in bindings]
        if len(names) != len(set(names)):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Context parameter binding name은 중복될 수 없습니다.",
            )

    @staticmethod
    def _validate_metrics(
        assets: tuple[ContextAsset, ...],
        metrics: tuple[ContextMetric, ...],
    ) -> None:
        ids = [metric.id for metric in metrics]
        if any(asset.metric_registry_required for asset in assets) and not metrics:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "선택된 Context asset에는 하나 이상의 승인 metric이 필요합니다.",
            )
        if len(ids) != len(set(ids)):
            raise ContextBuildError(
                ContextBuildErrorCode.DUPLICATE_METRIC,
                "동일한 metric id를 중복 포함할 수 없습니다.",
            )
        columns_by_fqn = {asset.fqn: set(asset.columns) for asset in assets}
        for metric in metrics:
            required_fields = {item.field for item in metric.required_filters}
            columns = columns_by_fqn.get(metric.asset_fqn, set())
            if (
                not all(
                    (metric.id, metric.asset_fqn, metric.field, metric.aggregation, metric.time_field)
                )
                or metric.field not in columns
                or metric.time_field not in columns
                or required_fields.difference(columns)
            ):
                raise ContextBuildError(
                    ContextBuildErrorCode.INVALID_METRIC,
                    "Metric은 선택된 asset column과 구조화 required filter를 사용해야 합니다.",
                )

    @staticmethod
    def _validate_request_metadata(request: ContextBuildRequest) -> None:
        metadata = (
            request.context_release,
            request.policy_version,
            request.time_version,
            request.entitlement_hash,
        )
        if any(not value.strip() for value in metadata):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Context release, policy, time, entitlement 정보가 필요합니다.",
            )
        if request.token_count < 0 or request.model_context_tokens <= 0:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Token 값은 유효한 양수 범위여야 합니다.",
            )

    @staticmethod
    def _validate_unique_assets(assets: tuple[ContextAsset, ...]) -> None:
        if not assets:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Context에는 하나 이상의 권한 있는 승인 asset이 필요합니다.",
            )
        urns = [asset.urn for asset in assets]
        if len(urns) != len(set(urns)):
            raise ContextBuildError(
                ContextBuildErrorCode.DUPLICATE_ASSET,
                "동일한 asset URN을 중복 포함할 수 없습니다.",
            )

    def _validate_limits(
        self,
        *,
        dataset_count: int,
        column_count: int,
        token_count: int,
        token_limit: int,
    ) -> None:
        if dataset_count > self.MAX_DATASETS:
            raise ContextBuildError(
                ContextBuildErrorCode.DATASET_LIMIT_EXCEEDED,
                f"Dataset은 최대 {self.MAX_DATASETS}개까지 허용됩니다.",
            )
        if column_count > self.MAX_COLUMNS:
            raise ContextBuildError(
                ContextBuildErrorCode.COLUMN_LIMIT_EXCEEDED,
                f"Column은 최대 {self.MAX_COLUMNS}개까지 허용됩니다.",
            )
        if token_count > token_limit:
            raise ContextBuildError(
                ContextBuildErrorCode.TOKEN_LIMIT_EXCEEDED,
                f"Context token은 최대 {token_limit}개까지 허용됩니다.",
            )


def _value_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _typed_value_is_valid(value_type: str, value: object) -> bool:
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if value_type == "string":
        return isinstance(value, str) and bool(value)
    if value_type == "date" and isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    return False


def _is_identifier(value: str) -> bool:
    return bool(value) and value.isascii() and all(
        character.isalnum() or character == "_" for character in value
    ) and (value[0].isalpha() or value[0] == "_")
