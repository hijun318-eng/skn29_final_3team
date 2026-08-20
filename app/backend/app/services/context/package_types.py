"""ContextPackage를 구성하는 불변 typed 값 객체 모듈.

[핵심 목적]
승인된 자산·지표·용어·파라미터 바인딩을 런타임에서 변형할 수 없는 frozen dataclass로
고정한다. 조립 규칙과 한도 검증은 `app.services.context.builder`가 소유하며, 이 모듈은
그 결과물이 가질 수 있는 형태만 선언한다.

[경계]
값 객체는 자기 필드의 형식 불변식만 책임진다. 권한·크기 한도·해시 결속처럼 패키지 전체를
가로지르는 판단은 빌더에 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.services.context.values import (
    FILTER_OPERATORS,
    RATIO_ZERO_POLICIES,
    _is_identifier,
    _typed_value_is_valid,
    _value_type,
)
from app.services.context.builder_errors import ContextBuildError, ContextBuildErrorCode
from src.data.metric_governance import (
    QUERY_STRATEGIES,
    RUNTIME_GOVERNANCE_VERSION_V2,
)

@dataclass(frozen=True)
class ContextRequiredFilter:
    """거버넌스 지표 계산에 반드시 요구되는 필수 필터(스칼라 비교 조건) 데이터 클래스."""

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
    """SQL 플레이스홀더에 결합할 파라미터 이름, 타입, 스칼라 값 데이터 클래스."""

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
    """승인된 자산의 물리 컬럼에서 결과값을 집계/계산하는 단일 지표 정의 데이터 클래스."""

    id: str
    asset_fqn: str
    field: str
    aggregation: str
    time_field: str
    required_filters: tuple[ContextRequiredFilter, ...]
    result_field: str = ""
    unit: str = ""
    reduction: str = ""
    numerator_metric_id: str = ""
    denominator_metric_id: str = ""
    zero_policy: str = ""
    visibility: str = "BUSINESS"
    governance_version: str = ""
    allowed_roles: tuple[str, ...] = ()
    contains_pii: bool = False
    allowed_join_ids: tuple[str, ...] = ()
    join_required: bool = False
    query_strategies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_field", self.result_field or self.id)
        if self.visibility not in {"BUSINESS", "SUPPORT"}:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "Metric visibility 계약이 유효하지 않습니다.",
            )
        if self.governance_version == RUNTIME_GOVERNANCE_VERSION_V2 and (
            not self.allowed_roles
            or len(self.allowed_roles) != len(set(self.allowed_roles))
            or self.contains_pii is not False
            or self.join_required != bool(self.allowed_join_ids)
            or not self.query_strategies
            or not set(self.query_strategies) <= QUERY_STRATEGIES
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "v2 Metric 권한·PII·Join·Query Strategy 계약이 유효하지 않습니다.",
            )
        aggregation = self.aggregation.lower()
        if aggregation == "ratio":
            if (
                self.asset_fqn
                or self.field
                or self.time_field
                or self.required_filters
                or not self.numerator_metric_id
                or not self.denominator_metric_id
                or self.numerator_metric_id == self.denominator_metric_id
                or self.zero_policy not in RATIO_ZERO_POLICIES
            ):
                raise ContextBuildError(
                    ContextBuildErrorCode.INVALID_METRIC,
                    "Ratio metric은 승인된 분자·분모 id와 zero_policy만으로 구성되어야 합니다.",
                )
            default_reduction = "ratio"
        else:
            default_reduction = (
                "sum"
                if aggregation
                in {"sum", "count", "count_distinct", "negative_sum", "derived_sum"}
                else {
                    "min": "min",
                    "max": "max",
                    "avg": "average",
                    "average": "average",
                }.get(aggregation, "scalar")
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
                "ratio",
            }
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "Metric result field와 reduction 계약이 유효하지 않습니다.",
            )


@dataclass(frozen=True)
class ContextMetricTerm:
    """DataHub 비즈니스 용어사전(Glossary Term)에서 조회한 지표 메타데이터 데이터 클래스."""

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
    """권한 검사를 통과한 DataHub 데이터셋의 URN, Trino FQN, 컬럼 및 조인 메타데이터 데이터 클래스."""

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
    """ContextPackage 생성을 위한 요청 파라미터 묶음 데이터 클래스."""

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
    """모델과 SQL Guard가 공유하는 최소 권한 불변 컨텍스트 스냅샷."""

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
