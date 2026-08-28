"""SQLGlot AST의 지표 집계 함수(Aggregation) 및 수식 의미론(Metric Semantics) 검증 모듈.

[핵심 목적]
생성된 SQL 쿼리의 프로젝션 컬럼 및 집계 수식이 DataHub에 등록된 공식 비즈니스 지표(Metric)의 정의와
완벽히 일치하는지 AST 수준에서 검증합니다.

[지원하는 지표 집계 형태]
1. 기본 집계: SUM(col), COUNT(col), COUNT(DISTINCT col), AVG(col), MIN(col), MAX(col)
2. 파생 지표 (Ratio Metric): `CAST(분자식 AS DOUBLE) / NULLIF(분모식, 0)` 형태의 비율 지표를 분자/분모 각각 재귀적으로 검증
3. 존재/조건 확인 지표 (Exists Metric): `COUNT(col) > 0` 형태의 Boolean 판별 지표
4. 다중 기간 비교 지표: `AGG(col) FILTER (WHERE ...)` 형태의 윈도우 필터 분리 검증
5. CTE/서브쿼리 롤업: 하위 CTE에서 집계된 컬럼을 상위 쿼리에서 재집계(Rollup)하는 리니지 추적
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlglot import exp

from app.services.sql_guard.schema import canonical_identifier, field_identity
from app.services.sql_guard.scopes import (
    ProjectionScopeEvidence,
    ScopeEvidence,
    clause_comparisons,
    projection_scope_evidence,
    resolve_scope_operand,
    source_column,
)
from src.ai.sql_policy import SqlValidationResult


@dataclass(frozen=True)
class MetricMatch:
    """단일 프로젝션이 승인된 지표 계산식과 정확히 일치했음을 나타내는 AST 증거 클래스.

    Attributes:
        metric_id: 일치한 지표 ID
        where_comparisons: 해당 지표 스코프 및 상위 WHERE 절에서 확인된 비교 조건 집합
    """

    metric_id: str
    where_comparisons: frozenset[tuple[str, str, str]]


def match_metric(
    scope: ProjectionScopeEvidence,
    metric: Any,
    assets: dict[str, tuple[Any, frozenset[str]]],
    metrics_by_id: dict[str, Any] | None = None,
    filtered: bool = False,
    expected_alias: str | None = None,
    unique_fields: frozenset[str] = frozenset(),
) -> MetricMatch | None:
    """프로젝션 스코프의 AST 수식이 승인된 거버넌스 지표 정의와 일치하는지 검증합니다.

    Args:
        scope: 대상 프로젝션 스코프 증거
        metric: ContextMetric 인스턴스
        assets: 승인된 자산 룩업 맵
        metrics_by_id: ratio 지표 검증을 위한 전체 지표 사전
        filtered: FILTER(WHERE ...) 절을 포함하는 조건부 집계 여부
        expected_alias: 비교 지표 등에 요구되는 명시적 컬럼 별칭

    Returns:
        일치 시 MetricMatch 객체, 불일치 시 None
    """
    if len(scope.projections) != 1:
        return None
    projection = scope.projections[0]
    if canonical_identifier(projection.alias or "") != canonical_identifier(
        expected_alias or metric.result_field
    ):
        return None
    expression = projection.this if isinstance(projection, exp.Alias) else projection
    filter_where: frozenset[tuple[str, str, str]] = frozenset()

    # 1. FILTER (WHERE ...) 구문 검증
    if filtered:
        if not isinstance(expression, exp.Filter):
            return None
        filter_clause = expression.args.get("expression")
        if not isinstance(filter_clause, exp.Where) or filter_clause.this is None:
            return None
        filter_where = frozenset(clause_comparisons(filter_clause.this, scope.scope))
        expression = expression.this
    elif isinstance(expression, exp.Filter):
        return None

    # 2. 비율 지표 (Ratio Metric) 검증
    if str(metric.aggregation).casefold() == "ratio":
        if metrics_by_id is None:
            return None
        where = _match_ratio_expression(
            expression,
            metric,
            metrics_by_id,
            assets,
            scope.scope,
            unique_fields,
        )
        return MetricMatch(str(metric.id), where) if where is not None else None

    try:
        field = field_identity(f"{metric.asset_fqn}.{metric.field}", assets)
    except ValueError:
        return None

    # 3. 존재 확인 지표 (Exists Metric: COUNT > 0) 검증
    if str(metric.aggregation).casefold() == "exists":
        where = _match_exists_expression(
            expression, field, scope.scope, filter_where, unique_fields
        )
        return MetricMatch(str(metric.id), where) if where is not None else None

    # 4. 일반 집계 함수 (SUM, COUNT, AVG, MIN, MAX 등) 검증
    where = _match_expression(
        expression,
        str(metric.aggregation).casefold(),
        field,
        scope.scope,
        filter_where,
        unique_fields,
    )
    return MetricMatch(str(metric.id), where) if where is not None else None


def _match_ratio_expression(
    expression: exp.Expression,
    metric: Any,
    metrics_by_id: dict[str, Any],
    assets: dict[str, tuple[Any, frozenset[str]]],
    scope: ScopeEvidence,
    unique_fields: frozenset[str],
) -> frozenset[tuple[str, str, str]] | None:
    """Trino 정수 나눗셈을 막는 ``CAST(분자식 AS DOUBLE) / NULLIF(분모식, 0)``를 검증합니다."""
    if metric.zero_policy != "null_on_zero_denominator" or not isinstance(expression, exp.Div):
        return None
    numerator = metrics_by_id.get(metric.numerator_metric_id)
    denominator = metrics_by_id.get(metric.denominator_metric_id)
    if numerator is None or denominator is None:
        return None
    denominator_node = expression.expression
    numerator_node = expression.this
    if (
        not isinstance(numerator_node, exp.Cast)
        or not isinstance(numerator_node.args.get("to"), exp.DataType)
        or numerator_node.args["to"].this != exp.DataType.Type.DOUBLE
        or not isinstance(denominator_node, exp.Nullif)
        or not isinstance(denominator_node.expression, exp.Literal)
        or denominator_node.expression.is_string
        or str(denominator_node.expression.this) != "0"
    ):
        return None
    try:
        numerator_field = field_identity(f"{numerator.asset_fqn}.{numerator.field}", assets)
        denominator_field = field_identity(f"{denominator.asset_fqn}.{denominator.field}", assets)
    except ValueError:
        return None
    numerator_where = _match_expression(
        numerator_node.this,
        str(numerator.aggregation).casefold(),
        numerator_field,
        scope,
        frozenset(),
        unique_fields,
    )
    denominator_where = _match_expression(
        denominator_node.this,
        str(denominator.aggregation).casefold(),
        denominator_field,
        scope,
        frozenset(),
        unique_fields,
    )
    if numerator_where is None or denominator_where is None:
        return None
    return numerator_where | denominator_where


def _match_exists_expression(
    expression: exp.Expression,
    field: str,
    scope: ScopeEvidence,
    inherited_where: frozenset[tuple[str, str, str]],
    unique_fields: frozenset[str],
) -> frozenset[tuple[str, str, str]] | None:
    """존재 확인 지표의 필수 형태인 'COUNT(field) > 0' 구문을 검증합니다."""
    if not isinstance(expression, exp.GT):
        return None
    threshold = expression.expression
    if not isinstance(threshold, exp.Literal) or threshold.is_string or str(threshold.this) != "0":
        return None
    return _match_expression(
        expression.this,
        "count",
        field,
        scope,
        inherited_where,
        unique_fields,
    )


def metric_matches(
    evidence: ProjectionScopeEvidence | SqlValidationResult,
    metric: Any,
    assets: dict[str, tuple[Any, frozenset[str]]],
    metrics_by_id: dict[str, Any] | None = None,
    filtered: bool = False,
    unique_fields: frozenset[str] = frozenset(),
) -> bool:
    """SQL 프로젝션 결과가 주어진 지표의 거버넌스 정의와 일치하는지 여부를 반환합니다."""
    scope = (
        projection_scope_evidence(evidence, metric.result_field)
        if isinstance(evidence, SqlValidationResult)
        else evidence
    )
    return (
        scope is not None
        and match_metric(
            scope,
            metric,
            assets,
            metrics_by_id,
            filtered,
            unique_fields=unique_fields,
        )
        is not None
    )


def _match_expression(
    expression: exp.Expression,
    aggregation: str,
    field: str,
    scope: ScopeEvidence,
    inherited_where: frozenset[tuple[str, str, str]],
    unique_fields: frozenset[str],
) -> frozenset[tuple[str, str, str]] | None:
    """단일 표현식 노드가 요구된 집계 함수와 컬럼 필드에 부합하는지 재귀적으로 검증합니다."""
    where = inherited_where | scope.where_comparisons
    if aggregation == "none":
        if resolve_scope_operand(expression, scope) == field:
            return _include_derived_where(expression, scope, where)
        return _derived_passthrough(
            expression, aggregation, field, scope, where, unique_fields
        )

    expected = {
        "sum": exp.Sum,
        "count": exp.Count,
        "count_distinct": exp.Count,
        "average": exp.Avg,
        "min": exp.Min,
        "max": exp.Max,
    }.get(aggregation)
    if expected is None:
        return None
    if isinstance(expression, expected):
        operand = _aggregate_operand(expression, aggregation)
        if operand is not None and resolve_scope_operand(operand, scope) == field:
            return _include_derived_where(operand, scope, where)

    rollup = {
        "sum": exp.Sum,
        "count": exp.Sum,
        "count_distinct": exp.Sum,
        "min": exp.Min,
        "max": exp.Max,
    }.get(aggregation)
    if rollup is not None and isinstance(expression, rollup):
        if aggregation == "count_distinct" and field not in unique_fields:
            return None
        operand = expression.this
        if isinstance(operand, exp.Distinct):
            return None
        return _derived_passthrough(
            operand, aggregation, field, scope, where, unique_fields
        )
    return _derived_passthrough(
        expression, aggregation, field, scope, where, unique_fields
    )


def _derived_passthrough(
    expression: exp.Expression,
    aggregation: str,
    field: str,
    scope: ScopeEvidence,
    where: frozenset[tuple[str, str, str]],
    unique_fields: frozenset[str],
) -> frozenset[tuple[str, str, str]] | None:
    resolved = source_column(expression, scope)
    if resolved is None:
        return None
    source, name = resolved
    child = source.derived_scope
    if child is None:
        return None
    projection = child.projections.get(name)
    if projection is None:
        return None
    body = projection.this if isinstance(projection, exp.Alias) else projection
    return _match_expression(
        body, aggregation, field, child, where, unique_fields
    )


def _include_derived_where(
    expression: exp.Expression,
    scope: ScopeEvidence,
    where: frozenset[tuple[str, str, str]],
) -> frozenset[tuple[str, str, str]]:
    resolved = source_column(expression, scope)
    source = resolved[0] if resolved is not None else None
    child = source.derived_scope if source is not None else None
    return where | child.where_comparisons if child is not None else where


def _aggregate_operand(
    expression: exp.Expression,
    aggregation: str,
) -> exp.Expression | None:
    operand = expression.this
    if aggregation == "count_distinct":
        if not isinstance(operand, exp.Distinct) or len(operand.expressions) != 1:
            return None
        return operand.expressions[0]
    if isinstance(operand, exp.Distinct):
        return None
    return operand
