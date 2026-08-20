"""컨텍스트(Context) 구축 및 거버넌스 계약 도메인 패키지.

[주요 구성 모듈]
- builder.py: ContextPackageBuilder 및 불변 ContextPackage 스냅샷 정의
- contract.py: GovernedJoin 조인 계약 및 RuntimeContextPackage 확장
- runtime_contracts.py: 런타임 스키마/지표/조인/시간/파라미터/쿼리 정책 조립기
- query_planner.py: 지표 참조 카탈로그 및 Grain 기반 3대 쿼리 전략 플래너
- metric_resolver.py: DataHub 용어사전 기반 단일 지표 및 기간/차원 해석기
- filter_candidate_resolver.py: 차원 용어 기반 필터 후보 검증기
- filter_value_resolver.py: Trino 실데이터 조회를 통한 필터 값 검증기
- service.py: DataHub/Trino 연동 런타임 컨텍스트 빌드 서비스
- registry_service.py: PostgreSQL Context Registry 생명주기 관리 서비스
- values.py: 스칼라 값 타입 및 비교 연산자 유효성 검증 유틸리티
"""

from app.services.context.builder import (
    ContextAsset,
    ContextBuildError,
    ContextBuildErrorCode,
    ContextBuildRequest,
    ContextMetric,
    ContextMetricTerm,
    ContextPackage,
    ContextPackageBuilder,
    ContextParameterBinding,
    ContextRequiredFilter,
)
from app.services.context.contract import (
    GovernedJoin,
    RuntimeContextPackage,
    enrich_context_package,
)
from app.services.context.filter_candidate_resolver import (
    dimension_terms,
    resolve_filter_candidates,
    validated_pre_filters,
)
from app.services.context.filter_value_resolver import (
    FilterValueUnresolvedError,
    ResolvedFilterValue,
    resolve_filter_value,
)
from app.services.context.metric_resolver import MetricResolver
from app.services.context.query_planner import (
    RAW_APPROVED_DETAIL,
    VIEW_COMPOSE,
    VIEW_REUSE,
    determine_query_strategy,
)
from app.services.context.registry_service import ContextRegistryService
from app.services.context.runtime_contracts import (
    build_runtime_contracts,
    comparison_time_parameter_names,
    filter_parameter_bindings,
    schema_columns,
    time_parameter_names,
)
from app.services.context.service import PipelineContextService
from app.services.context.values import (
    FILTER_OPERATORS,
    RATIO_ZERO_POLICIES,
)

__all__ = [
    "ContextAsset",
    "ContextBuildError",
    "ContextBuildErrorCode",
    "ContextBuildRequest",
    "ContextMetric",
    "ContextMetricTerm",
    "ContextPackage",
    "ContextPackageBuilder",
    "ContextParameterBinding",
    "ContextRequiredFilter",
    "GovernedJoin",
    "RuntimeContextPackage",
    "enrich_context_package",
    "dimension_terms",
    "resolve_filter_candidates",
    "validated_pre_filters",
    "FilterValueUnresolvedError",
    "ResolvedFilterValue",
    "resolve_filter_value",
    "MetricResolver",
    "RAW_APPROVED_DETAIL",
    "VIEW_COMPOSE",
    "VIEW_REUSE",
    "determine_query_strategy",
    "ContextRegistryService",
    "build_runtime_contracts",
    "comparison_time_parameter_names",
    "filter_parameter_bindings",
    "schema_columns",
    "time_parameter_names",
    "PipelineContextService",
    "FILTER_OPERATORS",
    "RATIO_ZERO_POLICIES",
]
