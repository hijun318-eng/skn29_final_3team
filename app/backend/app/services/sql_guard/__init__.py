"""SQL AST 거버넌스 및 세맨틱 가드(SQL Guard) 패키지.

[주요 구성 모듈]
- guard.py: AST 검증 진입점(validate_plan), 정적 정책 검증 및 GuardDecision 생성
- semantics.py: 필수 필터, 시간 조건 및 감사 리니지(references) 생성
- schema.py: 승인된 스키마/컬럼 대조 및 Trino 식별자 정규화
- scopes.py: SELECT 스코프별 소스, 프로젝션, 조인 증거 추출
- metric_semantics.py: 지표 집계 함수 및 비율/존재 지표 AST 일치 검증
- join_semantics.py: 승인된 조인 위상(Join Graph) 및 사전 집계 Grain 검증
"""

from app.services.sql_guard.guard import (
    GuardDecision,
    SemanticDecision,
    apply_guard_decision,
    validate_parsed_semantics,
    validate_plan,
)
from app.services.sql_guard.join_semantics import JoinDecision, join_violation
from app.services.sql_guard.metric_semantics import (
    MetricMatch,
    match_metric,
    metric_matches,
)
from app.services.sql_guard.schema import (
    approved_assets,
    canonical_fqn,
    canonical_identifier,
    column_violation,
    comparison_evidence,
    comparisons,
    declared_assets,
    declared_metrics,
    field_identity,
    identifier_node,
    operand_identity,
    reverse_operator,
    source_aliases,
)
from app.services.sql_guard.scopes import (
    JoinClauseEvidence,
    ProjectionScopeEvidence,
    ScopeEvidence,
    SourceEvidence,
    clause_comparisons,
    projection_scope_evidence,
    resolve_scope_operand,
    scope_evidence,
    source_column,
)
from app.services.sql_guard.semantics import (
    references,
    required_filter_violation,
    time_rule_violation,
)

__all__ = [
    "GuardDecision",
    "SemanticDecision",
    "validate_plan",
    "validate_parsed_semantics",
    "apply_guard_decision",
    "approved_assets",
    "canonical_fqn",
    "canonical_identifier",
    "column_violation",
    "comparisons",
    "comparison_evidence",
    "declared_assets",
    "declared_metrics",
    "field_identity",
    "identifier_node",
    "operand_identity",
    "reverse_operator",
    "source_aliases",
    "JoinClauseEvidence",
    "ProjectionScopeEvidence",
    "ScopeEvidence",
    "SourceEvidence",
    "clause_comparisons",
    "projection_scope_evidence",
    "resolve_scope_operand",
    "scope_evidence",
    "source_column",
    "JoinDecision",
    "MetricMatch",
    "join_violation",
    "match_metric",
    "metric_matches",
    "references",
    "required_filter_violation",
    "time_rule_violation",
]
