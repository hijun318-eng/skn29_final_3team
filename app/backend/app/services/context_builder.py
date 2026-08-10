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


class ContextBuildError(ValueError):
    def __init__(self, code: ContextBuildErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


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
class ContextMetric:
    id: str
    asset_fqn: str
    field: str
    aggregation: str
    time_field: str
    required_filters: tuple[ContextRequiredFilter, ...]


@dataclass(frozen=True)
class ContextAsset:
    urn: str
    fqn: str
    columns: tuple[str, ...]
    join_ids: tuple[str, ...] = ()
    metrics: tuple[ContextMetric, ...] = ()
    metric_registry_required: bool = False
    required_filters: tuple[ContextRequiredFilter, ...] = ()

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
                or not metric.required_filters
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
