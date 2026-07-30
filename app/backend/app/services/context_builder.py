from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum


class ContextBuildErrorCode(str, Enum):
    INVALID_METADATA = "INVALID_METADATA"
    DUPLICATE_ASSET = "DUPLICATE_ASSET"
    DATASET_LIMIT_EXCEEDED = "DATASET_LIMIT_EXCEEDED"
    COLUMN_LIMIT_EXCEEDED = "COLUMN_LIMIT_EXCEEDED"
    TOKEN_LIMIT_EXCEEDED = "TOKEN_LIMIT_EXCEEDED"


class ContextBuildError(ValueError):
    def __init__(self, code: ContextBuildErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ContextAsset:
    urn: str
    fqn: str
    columns: tuple[str, ...]

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
                }
                for asset in assets
            ],
            "token_count": request.token_count,
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
            dataset_count=dataset_count,
            column_count=column_count,
            token_count=request.token_count,
            token_limit=token_limit,
            package_hash=package_hash,
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
