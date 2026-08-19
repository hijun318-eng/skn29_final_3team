"""projection alias와 aggregate AST를 runtime metric의 source field·reduction에 대조하고 CTE·derived scope를 거슬러 정확한 metric lineage를 확인한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlglot import exp

from app.services.pipeline_sql_schema import canonical_identifier, field_identity
from app.services.pipeline_sql_scopes import (
    ProjectionScopeEvidence,
    ScopeEvidence,
    projection_scope_evidence,
    resolve_scope_operand,
    source_column,
)
from src.ai.sql_policy import SqlValidationResult


@dataclass(frozen=True)
class MetricMatch:
    """한 projection이 승인 metric 계산과 정확히 일치했음을 나타내는 AST 증거다.

    metric ID와 최상위 ``WHERE``에서 확인한 typed 비교 집합만 보존한다. 중첩 OR/NOT/CASE나
    다른 scope의 조건은 포함하지 않아 필수 filter·time predicate를 우회 증거로 쓸 수 없다.
    """
    metric_id: str
    where_comparisons: frozenset[tuple[str, str, str]]


def match_metric(
    scope: ProjectionScopeEvidence,
    metric: Any,
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> MetricMatch | None:
    """지표 후보를 거버넌스 제약과 입력 증거로 판정해 하나의 결과로 좁힌다."""
    if len(scope.projections) != 1:
        return None
    try:
        field = field_identity(f"{metric.asset_fqn}.{metric.field}", assets)
    except ValueError:
        return None
    projection = scope.projections[0]
    if canonical_identifier(projection.alias or "") != canonical_identifier(
        metric.result_field
    ):
        return None
    expression = projection.this if isinstance(projection, exp.Alias) else projection
    where = _match_expression(
        expression,
        str(metric.aggregation).casefold(),
        field,
        scope.scope,
        frozenset(),
    )
    return MetricMatch(str(metric.id), where) if where is not None else None


def metric_matches(
    evidence: ProjectionScopeEvidence | SqlValidationResult,
    metric: Any,
    assets: dict[str, tuple[Any, frozenset[str]]],
) -> bool:
    """SQLGlot projection이 governed metric의 정확한 AST 의미를 구현하는지 판정한다.

    전체 SQL 결과가 오면 metric result alias의 scope를 먼저 찾고, 이미 좁혀진 scope도
    허용한다. 승인 aggregation·source field·derived lineage가 모두 맞을 때만 ``True``다.
    """
    scope = (
        projection_scope_evidence(evidence, metric.result_field)
        if isinstance(evidence, SqlValidationResult)
        else evidence
    )
    return scope is not None and match_metric(scope, metric, assets) is not None


def _match_expression(
    expression: exp.Expression,
    aggregation: str,
    field: str,
    scope: ScopeEvidence,
    inherited_where: frozenset[tuple[str, str, str]],
) -> frozenset[tuple[str, str, str]] | None:
    where = inherited_where | scope.where_comparisons
    if aggregation == "none":
        if resolve_scope_operand(expression, scope) == field:
            return _include_derived_where(expression, scope, where)
        return _derived_passthrough(expression, aggregation, field, scope, where)

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
        "min": exp.Min,
        "max": exp.Max,
    }.get(aggregation)
    if rollup is not None and isinstance(expression, rollup):
        operand = expression.this
        if isinstance(operand, exp.Distinct):
            return None
        return _derived_passthrough(operand, aggregation, field, scope, where)
    return _derived_passthrough(expression, aggregation, field, scope, where)


def _derived_passthrough(
    expression: exp.Expression,
    aggregation: str,
    field: str,
    scope: ScopeEvidence,
    where: frozenset[tuple[str, str, str]],
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
    return _match_expression(body, aggregation, field, child, where)


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
