"""SQLGlot AST의 필수 필터, 반개방 시간 조건, 리니지 참조(References) 생성 모듈.

[핵심 목적]
1. 필수 비즈니스 필터 검증: 지표 정의에 선언된 필수 필터(예: `is_deleted = false`, `status = 'CONFIRMED'`)가
   SQL의 WHERE 절에 명시적으로 포함되었는지 AST 비교 증거로 검증합니다.
2. 반개방 기간 검증: 시계열 조건이 항상 일관된 반개방 구간(`time_field >= :period_start AND time_field < :period_end_exclusive`)으로
   파라미터화되었는지 확인합니다.
3. 신뢰할 수 있는 데이터 리니지(References) 조립: LLM이 주장하는 설명 대신 실제 SQLGlot이 확인한 테이블, 컬럼, 조인 ID, 지표 ID만을
   추출하여 감사(Audit) 가능한 출처 증거(Evidence)로 변환합니다.
"""

from __future__ import annotations

from typing import Any

from sqlglot import exp

from app.services.sql_guard.join_semantics import JoinDecision, join_violation
from app.services.sql_guard.metric_semantics import (
    MetricMatch,
    match_metric,
    metric_matches,
)
from app.services.sql_guard.schema import (
    canonical_fqn,
    field_identity,
    identifier_node,
    operand_identity,
    source_aliases,
)
from src.ai.sql_policy import SqlValidationResult


def required_filter_violation(
    package: Any,
    comparisons: set[tuple[str, str, str]],
    assets: dict[str, tuple[Any, frozenset[str]]],
    metric_id: str | None = None,
) -> str | None:
    """ContextPackage에 정의된 필수 필터 규칙들이 AST 비교 조건 집합에 모두 존재하는지 검증합니다.

    Args:
        package: ContextPackage 인스턴스
        comparisons: AST에서 추출된 비교 조건 튜플 집합 (field, op, param)
        assets: 승인된 자산 룩업 맵
        metric_id: 특정 지표 대상 필터만 검증할 경우 지정

    Returns:
        필수 필터 누락 시 위반 메시지 문자열 (모두 만족하면 None)
    """
    contracts = getattr(package, "runtime_contracts", None) or {}
    rules = contracts.get("metric_rules") or ()
    selected = [
        item
        for item in rules
        if metric_id is None or str(item.get("id")) == metric_id
    ]
    if metric_id is not None and len(selected) != 1:
        return f"런타임 지표 규칙 {metric_id!r} 이(가) 누락되었거나 중복되었습니다."

    for rule in selected:
        for item in rule.get("required_filters", ()):
            field_value = item.get("field") if isinstance(item, dict) else None
            if not isinstance(field_value, dict):
                return "런타임 필수 필터 필드 정의가 유효하지 않습니다."
            field = field_identity(
                f"{field_value.get('asset_fqn')}.{field_value.get('column')}",
                assets,
            )
            parameter = str(item.get("parameter") or "")
            operator = str(item.get("operator") or "")
            if not parameter or (field, operator, f":{parameter}") not in comparisons:
                return f"필수 필터 파라미터 {parameter!r} 에 대한 조건식이 누락되었습니다."
    return None


def time_rule_violation(
    package: Any,
    comparisons: set[tuple[str, str, str]],
    assets: dict[str, tuple[Any, frozenset[str]]],
    metric: Any | None = None,
    window: str = "primary",
    result: SqlValidationResult | None = None,
) -> str | None:
    """지표 시간 필드가 승인된 기간 또는 최신 스냅샷 선택 형태인지 검증합니다.

    Args:
        package: ContextPackage 인스턴스
        comparisons: AST 비교 조건 집합
        assets: 승인 자산 맵
        metric: 대상 지표
        window: 'primary' (기본 분석 기간) 또는 'comparison' (비교 분석 기간)

    Returns:
        시간 조건 위반 시 설명 메시지 (성공 시 None)
    """
    contracts = getattr(package, "runtime_contracts", None) or {}
    time_rules = contracts.get("time_rules") or {}
    selected = metric or (package.metrics[0] if len(package.metrics) == 1 else None)
    if selected is None:
        return "지표별 시간 규칙이 필요합니다."
    if not selected.time_field:
        if str(getattr(selected, "aggregation", "")).casefold() != "ratio":
            return None
        metrics_by_id = {str(item.id): item for item in package.metrics}
        operands = (
            metrics_by_id.get(str(selected.numerator_metric_id)),
            metrics_by_id.get(str(selected.denominator_metric_id)),
        )
        if any(item is None or not item.time_field for item in operands):
            return "Ratio 지표의 시간 규칙 operand가 불완전합니다."
        for operand in operands:
            assert operand is not None
            violation = time_rule_violation(
                package,
                comparisons,
                assets,
                operand,
                window,
                result,
            )
            if violation is not None:
                return violation
        return None

    field = field_identity(f"{selected.asset_fqn}.{selected.time_field}", assets)
    mode = str(time_rules.get("mode") or "range")
    if mode == "latest_snapshot":
        if window != "primary":
            return "최신 스냅샷 시간 규칙은 비교 기간을 지원하지 않습니다."
        return _latest_snapshot_violation(
            result,
            field=field,
            parameter=str(time_rules.get("as_of_parameter") or ""),
            native_type=_time_native_type(time_rules, field),
            selection=str(time_rules.get("selection") or ""),
        )
    if mode != "range":
        return "지원되지 않는 시간 선택 mode입니다."
    if window == "comparison":
        comparison = time_rules.get("comparison_window") or {}
        start_parameter = str(comparison.get("start_parameter") or "")
        end_parameter = str(comparison.get("end_parameter") or "")
    else:
        start_parameter = str(time_rules.get("start_parameter") or "")
        end_parameter = str(time_rules.get("end_parameter") or "")

    required = {
        (field, "gte", f":{start_parameter}"),
        (field, "lt", f":{end_parameter}"),
    }
    comparison = time_rules.get("comparison_window") or {}
    governed_parameters = {
        f":{name}"
        for name in (
            str(time_rules.get("start_parameter") or ""),
            str(time_rules.get("end_parameter") or ""),
            str(comparison.get("start_parameter") or ""),
            str(comparison.get("end_parameter") or ""),
        )
        if name
    }
    actual_window = {
        item
        for item in comparisons
        if item[0] == field and item[2] in governed_parameters
    }
    if not start_parameter or not end_parameter or actual_window != required:
        return "지표 시간 필드는 거버넌스 승인을 받은 반개방 기간 파라미터(>= start AND < end)를 반드시 사용해야 합니다."
    return None


def _latest_snapshot_violation(
    result: SqlValidationResult | None,
    *,
    field: str,
    parameter: str,
    native_type: str | None,
    selection: str,
) -> str | None:
    """MAX(source_time) < :as_of scalar subquery의 정확한 AST shape를 검증한다."""

    if (
        result is None
        or not isinstance(result.expression, exp.Select)
        or selection != "max_source_value_lt_as_of"
        or not parameter
        or not native_type
    ):
        return "최신 스냅샷 선택 계약 또는 SQL AST 증거가 불완전합니다."
    subqueries = tuple(result.expression.find_all(exp.Subquery))
    if len(subqueries) != 1:
        return "최신 스냅샷 SQL은 정확히 하나의 scalar MAX subquery를 사용해야 합니다."

    where = result.expression.args.get("where")
    if not isinstance(where, exp.Where) or where.this is None:
        return "최신 스냅샷 선택 조건이 누락되었습니다."
    aliases = source_aliases(result)
    candidates: list[tuple[exp.Column, exp.Subquery]] = []
    for predicate in _conjuncts(where.this):
        if not isinstance(predicate, exp.EQ):
            continue
        left, right = predicate.this, predicate.expression
        if isinstance(left, exp.Column) and isinstance(right, exp.Subquery):
            candidates.append((left, right))
        elif isinstance(right, exp.Column) and isinstance(left, exp.Subquery):
            candidates.append((right, left))
    if len(candidates) != 1 or candidates[0][1] is not subqueries[0]:
        return "최신 스냅샷 equality는 최상위 AND 조건 하나로 고정되어야 합니다."
    outer_column, subquery = candidates[0]
    if operand_identity(outer_column, aliases, result.physical_tables) != field:
        return "최신 스냅샷 equality가 승인된 시간 필드를 사용하지 않습니다."

    inner = subquery.this
    if not isinstance(inner, exp.Select) or not _is_minimal_snapshot_select(inner):
        return "최신 스냅샷 subquery에는 MAX·단일 source·기준일 조건만 허용됩니다."
    source = inner.args.get("from_")
    table = source.this if isinstance(source, exp.From) else None
    if not isinstance(table, exp.Table) or _table_fqn(table) != field.rsplit(".", 1)[0]:
        return "최신 스냅샷 subquery source가 지표 자산과 일치하지 않습니다."

    projection = inner.expressions[0]
    projection = projection.this if isinstance(projection, exp.Alias) else projection
    if (
        not isinstance(projection, exp.Max)
        or operand_identity(projection.this, aliases, result.physical_tables) != field
    ):
        return "최신 스냅샷 subquery는 승인 시간 필드의 MAX만 계산해야 합니다."
    inner_where = inner.args.get("where")
    predicate = _unwrap(inner_where.this) if isinstance(inner_where, exp.Where) else None
    if not isinstance(predicate, exp.LT):
        return "최신 스냅샷 source에는 시간 필드 < 기준일 조건이 필요합니다."
    if operand_identity(predicate.this, aliases, result.physical_tables) != field:
        return "최신 스냅샷 기준일 조건이 승인 시간 필드를 사용하지 않습니다."
    if not _typed_parameter(predicate.expression, parameter, native_type):
        return "최신 스냅샷 기준일은 승인된 typed named parameter를 사용해야 합니다."
    return None


def _conjuncts(value: exp.Expression) -> tuple[exp.Expression, ...]:
    value = _unwrap(value)
    if isinstance(value, exp.And):
        return (*_conjuncts(value.this), *_conjuncts(value.expression))
    return (value,)


def _unwrap(value: exp.Expression) -> exp.Expression:
    while isinstance(value, exp.Paren):
        value = value.this
    return value


def _is_minimal_snapshot_select(value: exp.Select) -> bool:
    allowed = {"expressions", "from_", "where"}
    return len(value.expressions) == 1 and all(
        name in allowed or item in (None, False, [], ())
        for name, item in value.args.items()
    )


def _table_fqn(value: exp.Table) -> str:
    return ".".join(identifier_node(item) for item in value.parts)


def _typed_parameter(value: exp.Expression, parameter: str, native_type: str) -> bool:
    value = _unwrap(value)
    if not isinstance(value, exp.Cast) or not isinstance(value.this, exp.Placeholder):
        return False
    target = value.args.get("to")
    if not isinstance(target, exp.DataType) or value.this.name != parameter:
        return False
    expected = exp.DataType.build(native_type, dialect="trino")
    return target.sql(dialect="trino") == expected.sql(dialect="trino")


def _time_native_type(time_rules: Any, field: str) -> str | None:
    if not isinstance(time_rules, dict):
        return None
    matches = [
        str(item.get("native_type") or "")
        for item in time_rules.get("fields", ())
        if isinstance(item, dict)
        and isinstance(item.get("field"), dict)
        and f"{item['field'].get('asset_fqn')}.{item['field'].get('column')}" == field
    ]
    return matches[0] if len(matches) == 1 and matches[0] else None


def references(
    result: SqlValidationResult,
    package: Any,
    assets: dict[str, tuple[Any, frozenset[str]]],
    used_join_ids: frozenset[str],
) -> tuple[dict[str, Any], ...]:
    """검증된 SQLGlot AST로부터 실제 사용된 테이블, 컬럼, 조인 ID, 지표 ID 리니지 참조 목록을 생성합니다.

    Args:
        result: SQLGlot 파싱 결과
        package: ContextPackage 인스턴스
        assets: 승인 자산 맵
        used_join_ids: 검증을 통과한 조인 ID 집합

    Returns:
        감사 가능한 출처 메타데이터 튜플
    """
    graph = tuple(getattr(package, "join_graph", ()))
    metrics = tuple(getattr(package, "metrics", ()))
    metrics_by_id = {str(item.id): item for item in metrics}

    def _reporting_fqn(metric: Any) -> str:
        # ratio metric은 별도 물리 자산이 없으므로 분자 지표의 자산 FQN에 귀속
        if str(metric.aggregation).casefold() != "ratio":
            return str(metric.asset_fqn)
        numerator = metrics_by_id.get(str(metric.numerator_metric_id))
        return str(numerator.asset_fqn) if numerator is not None else ""

    output = []
    for fqn in result.physical_tables:
        asset = assets[fqn][0]
        columns = sorted({item.name for item in result.columns if item.source_table == fqn})
        output.append(
            {
                "urn": asset.urn,
                "fqn": fqn,
                "columns": columns,
                "join_ids": sorted(
                    item.id
                    for item in graph
                    if item.id in used_join_ids
                    and fqn in {canonical_fqn(item.left), canonical_fqn(item.right)}
                ),
                "metric_ids": sorted(
                    str(metric.id)
                    for metric in metrics
                    if canonical_fqn(_reporting_fqn(metric)) == fqn
                ),
            }
        )
    return tuple(output)


__all__ = [
    "JoinDecision",
    "MetricMatch",
    "join_violation",
    "match_metric",
    "metric_matches",
    "references",
    "required_filter_violation",
    "time_rule_violation",
]
