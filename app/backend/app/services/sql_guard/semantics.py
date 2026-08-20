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

from app.services.sql_guard.join_semantics import JoinDecision, join_violation
from app.services.sql_guard.metric_semantics import (
    MetricMatch,
    match_metric,
    metric_matches,
)
from app.services.sql_guard.schema import canonical_fqn, field_identity
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
) -> str | None:
    """지표의 시간 필드가 반개방 파라미터 [start, end) 형태로 조건에 반영되었는지 검증합니다.

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
        return None

    field = field_identity(f"{selected.asset_fqn}.{selected.time_field}", assets)
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
    if not start_parameter or not end_parameter or not required.issubset(comparisons):
        return "지표 시간 필드는 거버넌스 승인을 받은 반개방 기간 파라미터(>= start AND < end)를 반드시 사용해야 합니다."
    return None


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
