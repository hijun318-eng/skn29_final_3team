"""승인된 카탈로그 메타데이터 및 지표/파라미터 계약을 불변 ContextPackage로 조립하는 빌더 모듈.

[핵심 목적]
DataHub 및 사용자 권한 검사를 통과한 자산(Asset), 지표(Metric), 용어사전(Glossary Term), 파라미터 바인딩을
최대 한도(Dataset 수, 컬럼 수, 토큰 예산)와 정규화된 해시(`package_hash`)로 결속하여,
LLM 및 SQL Guard가 소비할 수 있는 최소 권한의 불변 `ContextPackage`를 결정론적으로 빌드합니다.

[보안 및 무결성 원칙]
1. 최소 권한 및 크기 제한: 최대 8개 데이터셋, 최대 60개 컬럼, 모델 컨텍스트의 25% 이내 토큰 제한
2. 메타데이터 변조 방지: 정규 JSON 직렬화 후 SHA-256 해시를 생성하여 런타임 위변조 방지
3. Fail-Closed: 권한 위반, 스키마 불일치, 지표 수식 오류 발생 시 `ContextBuildError`를 발생시켜 즉각 차단
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from enum import Enum

from app.services.context.builder_errors import ContextBuildError, ContextBuildErrorCode
from app.services.context.package_types import (
    ContextAsset,
    ContextBuildRequest,
    ContextDimensionMemberReceipt,
    ContextMetric,
    ContextMetricTerm,
    ContextPackage,
    ContextParameterBinding,
    ContextRequiredFilter,
)
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V2

# 오류·값 객체는 별도 모듈이 선언하지만, 호출자들이 오랫동안 사용해 온 공개 표면은
# 이 모듈이므로 그대로 재노출한다.
__all__ = [
    "ContextAsset",
    "ContextBuildError",
    "ContextBuildErrorCode",
    "ContextBuildRequest",
    "ContextDimensionMemberReceipt",
    "ContextMetric",
    "ContextMetricTerm",
    "ContextPackage",
    "ContextPackageBuilder",
    "ContextParameterBinding",
    "ContextRequiredFilter",
]


class ContextPackageBuilder:
    """[책임] 권한 검사된 DataHub 메타데이터, 지표 및 파라미터를 불변 ContextPackage 스냅샷으로 조립한다.
    - 입출력: ContextBuildRequest 및 entitled_asset_urns 수신 → 패키지 해시가 봉인된 ContextPackage 객체 반환
    - 주의조건: 데이터셋 8개/컬럼 60개 한도 초과, 미승인 URN 접근 시 ContextBuildError 발생으로 fail-closed
    """

    MAX_DATASETS = 8
    MAX_COLUMNS = 60
    MAX_TOKENS = 6_000
    MODEL_CONTEXT_RATIO = 0.25

    def build(
        self,
        request: ContextBuildRequest,
        entitled_asset_urns: frozenset[str],
    ) -> ContextPackage:
        """[책임] 권한 및 상한 규격을 검증하고 정규화된 SHA-256 해시가 부여된 불변 ContextPackage를 생성한다.
        - 입출력: ContextBuildRequest 및 entitled_asset_urns 수신 → 검증된 ContextPackage 객체 생성 후 파이프라인으로 반환
        - 주의조건: 허용 상한(8개 데이터셋/60개 컬럼) 초과, 미승인 URN 참조, 지표 수식 오류 시 ContextBuildError 발생
        """
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
        dimension_member_receipts = tuple(
            sorted(
                request.dimension_member_receipts,
                key=lambda item: (item.dimension_id, item.member_id),
            )
        )
        if len(
            {
                (item.dimension_id, item.member_id)
                for item in dimension_member_receipts
            }
        ) != len(dimension_member_receipts):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Dimension Member receipt는 중복될 수 없습니다.",
            )
        if len({term.id for term in metric_terms}) != len(metric_terms):
            raise ContextBuildError(
                ContextBuildErrorCode.DUPLICATE_METRIC,
                "DataHub Metric Glossary Term은 중복될 수 없습니다.",
            )
        governance_versions = {metric.governance_version for metric in metrics}
        if metrics and governance_versions != {RUNTIME_GOVERNANCE_VERSION_V2}:
            raise ContextBuildError(
                ContextBuildErrorCode.GOVERNANCE_VERSION_UNSUPPORTED,
                "Production 분석에는 Metric별 권한이 완전한 v2 governance release가 필요합니다.",
            )
        governed_v2 = bool(metrics)
        business_metric_ids = {
            metric.id for metric in metrics if metric.visibility == "BUSINESS"
        }
        if governed_v2 and {term.id for term in metric_terms} != business_metric_ids:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "v2 BUSINESS Metric과 DataHub Glossary Term 범위가 다릅니다.",
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
                    "reduction": metric.reduction,
                    "numerator_metric_id": metric.numerator_metric_id,
                    "denominator_metric_id": metric.denominator_metric_id,
                    "zero_policy": metric.zero_policy,
                    "visibility": metric.visibility,
                    "governance_version": metric.governance_version,
                    "allowed_roles": list(metric.allowed_roles),
                    "contains_pii": metric.contains_pii,
                    "allowed_join_ids": list(metric.allowed_join_ids),
                    "join_required": metric.join_required,
                    "query_strategies": list(metric.query_strategies),
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
                    "checksum": term.checksum,
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
        if dimension_member_receipts:
            canonical["dimension_member_receipts"] = [
                {
                    "dimension_id": item.dimension_id,
                    "member_id": item.member_id,
                    "term_urn": item.term_urn,
                    "canonical_value": item.canonical_value,
                    "version": item.version,
                    "semantic_sha256": item.semantic_sha256,
                    "asset_fqn": item.asset_fqn,
                    "column": item.column,
                }
                for item in dimension_member_receipts
            ]
        if request.product_release_id is not None:
            canonical["product_release_id"] = request.product_release_id
        if request.evidence_cutoff is not None:
            canonical["evidence_cutoff"] = request.evidence_cutoff.isoformat()
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
            product_release_id=request.product_release_id,
            evidence_cutoff=request.evidence_cutoff,
            parameter_bindings=request.parameter_bindings,
            required_filters=required_filters,
            metric_terms=metric_terms,
            dimension_member_receipts=dimension_member_receipts,
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
        metrics_by_id = {metric.id: metric for metric in metrics}
        for metric in metrics:
            if metric.reduction == "ratio":
                numerator = metrics_by_id.get(metric.numerator_metric_id)
                denominator = metrics_by_id.get(metric.denominator_metric_id)
                if (
                    numerator is None
                    or denominator is None
                    or numerator.reduction == "ratio"
                    or denominator.reduction == "ratio"
                ):
                    raise ContextBuildError(
                        ContextBuildErrorCode.INVALID_METRIC,
                        "Ratio metric의 분자·분모는 같은 Context 안의 단일 metric이어야 합니다.",
                    )
                continue
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
        if (
            request.product_release_id is not None
            and not request.product_release_id.strip()
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Product release ID는 비어 있을 수 없습니다.",
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
