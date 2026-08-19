"""승인 asset·metric·glossary·parameter 계약을 크기 상한과 권한 URN에 대조해 해시된 불변 ContextPackage로 만들며 위반은 ContextBuildError로 거부한다."""
# architecture-max-lines: 600 -- Context typed 계약과 canonical hash builder가 동일 검증 불변식을 공유해 한 변경 단위로 유지한다.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from enum import Enum

from app.services.context_values import (
    FILTER_OPERATORS,
    _is_identifier,
    _typed_value_is_valid,
    _value_type,
)


class ContextBuildErrorCode(str, Enum):
    """ContextBuildErrorCode 계약에서 허용하는 상태 값을 정의한다."""
    INVALID_METADATA = "INVALID_METADATA"
    DUPLICATE_ASSET = "DUPLICATE_ASSET"
    DATASET_LIMIT_EXCEEDED = "DATASET_LIMIT_EXCEEDED"
    COLUMN_LIMIT_EXCEEDED = "COLUMN_LIMIT_EXCEEDED"
    TOKEN_LIMIT_EXCEEDED = "TOKEN_LIMIT_EXCEEDED"
    INVALID_METRIC = "INVALID_METRIC"
    DUPLICATE_METRIC = "DUPLICATE_METRIC"
    PERIOD_REQUIRED = "PERIOD_REQUIRED"


class ContextBuildError(ValueError):
    """runtime metadata나 사용자 분석 범위가 context 계약을 만들 수 없음을 나타낸다.

    ``code``는 metadata 무결성·상한·metric·기간 실패를 구분하고 ``suggestions``는 모호성
    해소 후보만 전달한다. 호출자는 이를 기본 context로 보정하지 않고 차단 응답으로 변환한다.
    """
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
    """거버넌스가 지표 계산에 반드시 요구하는 scalar 비교 조건을 나타낸다.

    필드·연산자·값과 명시 타입을 함께 보존하며, 승인된 연산자와 실제 Python 값의 타입이
    일치하지 않으면 생성 단계에서 ``ContextBuildError``로 거부한다.
    """
    field: str
    operator: str
    value: str | bool | int | float
    value_type: str = ""

    def __post_init__(self) -> None:
        value_type = self.value_type or _value_type(self.value)
        if (
            self.operator not in FILTER_OPERATORS
            or not _typed_value_is_valid(value_type, self.value)
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "Required filter는 승인된 type의 eq 값이어야 합니다.",
            )
        object.__setattr__(self, "value_type", value_type)


@dataclass(frozen=True)
class ContextParameterBinding:
    """모델 SQL placeholder에 결합할 이름·논리 타입·scalar 값을 보존한다.

    빈 이름이나 선언 타입과 다른 값은 package hash에 들어가기 전에 거부해 SQL AST
    binding 단계가 문자열 추론이나 암묵적 형 변환에 의존하지 않게 한다.
    """
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
    """승인 asset의 물리 열에서 결과 필드를 계산하는 단일 지표 계약이다.

    지표 ID, asset FQN, source/result field, aggregation, time field, 필수 filter와 reduction을
    함께 묶는다. 지원하지 않는 aggregation·reduction이나 식별자 불변식은 생성 시점에
    차단되어 모델이 임의 계산 의미를 보충할 수 없다.
    """
    id: str
    asset_fqn: str
    field: str
    aggregation: str
    time_field: str
    required_filters: tuple[ContextRequiredFilter, ...]
    result_field: str = ""
    unit: str = ""
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
            }
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "Metric result field와 reduction 계약이 유효하지 않습니다.",
            )


@dataclass(frozen=True)
class ContextMetricTerm:
    """DataHub glossary에서 읽은 지표의 식별자·표시명·별칭·정의·버전 무결성 계약이다.

    URN은 지표 ID와 정확히 대응하고 label은 aliases에 포함되어야 한다. definition, unit,
    version, checksum 중 하나라도 비면 용어 해석을 추정하지 않고 context build를 거부한다.
    """
    id: str
    urn: str
    label: str
    aliases: tuple[str, ...]
    definition: str
    unit: str
    version: str
    checksum: str

    def __post_init__(self) -> None:
        if (
            not _is_identifier(self.id)
            or not (
                self.urn == f"urn:li:glossaryTerm:{self.id}"
                or self.urn == f"urn:li:glossaryTerm:answervice_{self.id}"
            )
            or not self.label.strip()
            or not self.aliases
            or self.label not in self.aliases
            or any(not alias.strip() for alias in self.aliases)
            or not self.definition.strip()
            or not self.unit.strip()
            or not self.version.strip()
            or not self.checksum.strip()
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "DataHub Metric Glossary Term 계약이 유효하지 않습니다.",
            )


@dataclass(frozen=True)
class ContextAsset:
    """권한 검사를 통과한 한 DataHub dataset의 URN·Trino FQN·열·지표·조인 연결을 보존한다.

    빈 asset identity나 column, column type 불일치는 ``ContextBuildError``로 차단한다.
    ``join_ids``와 metric metadata는 이후 SQLGlot lineage 검증의 승인 목록으로만 쓰이며
    이름 패턴으로 관계를 추론하지 않는다.
    """
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
    """context package 생성을 위한 승인 release·policy·time·entitlement와 자산 입력이다.

    호출자는 권한 후보 asset, parameter와 glossary term, token 예산, 선택적 product release와
    evidence cutoff를 전달한다. builder는 이 값들을 다시 검증한 뒤 canonical hash 입력으로
    사용한다.
    """
    context_release: str
    policy_version: str
    time_version: str
    entitlement_hash: str
    assets: tuple[ContextAsset, ...]
    token_count: int
    model_context_tokens: int
    product_release_id: str | None = None
    evidence_cutoff: date | None = None
    parameter_bindings: tuple[ContextParameterBinding, ...] = ()
    metric_terms: tuple[ContextMetricTerm, ...] = ()


@dataclass(frozen=True)
class ContextPackage:
    """모델과 SQL guard가 함께 소비하는 최소 권한 context의 불변 snapshot이다.

    승인 asset·metric·filter·parameter·glossary term와 실제 크기, token 한도, join ID를
    canonical ``package_hash``에 결속한다. 요청 중 metadata가 바뀌어도 이 snapshot 밖의
    자산이나 규칙을 실행 단계에서 추가할 수 없다.
    """
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
    product_release_id: str | None = None
    evidence_cutoff: date | None = None
    metrics: tuple[ContextMetric, ...] = ()
    parameter_bindings: tuple[ContextParameterBinding, ...] = ()
    required_filters: tuple[ContextRequiredFilter, ...] = ()
    metric_terms: tuple[ContextMetricTerm, ...] = ()


class ContextPackageBuilder:
    """모델과 SQL 생성기에 전달할 최소 데이터 context를 만든다.

    이미 권한 검사를 통과한 자산만 받으며, 자산 수·열 수·token 예산을
    다시 제한한다. metric 공식과 parameter 타입도 여기서 검증해 이후
    단계가 불완전하거나 과도한 context를 실행하지 못하게 한다.
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
        """권한 URN으로 asset을 제한하고 metric·glossary·binding·크기 상한을 검증한 뒤 canonical SHA-256이 포함된 불변 package를 반환하며 위반은 ``ContextBuildError``로 거부한다."""
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
