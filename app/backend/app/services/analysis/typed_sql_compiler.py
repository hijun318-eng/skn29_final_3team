"""승인된 단일 Serving View 논리 계획을 결정론적 Trino SQL AST로 컴파일한다.

이 모듈의 권위 입력은 질문 원문이나 지표 이름 사전이 아니라 검증된 ``AnalysisPlan``과
``RuntimeContextPackage``다. 현재 활성 범위는 JOIN이 필요 없는 ``VIEW_REUSE``이며, 모든
결과는 기존 SQL Guard가 다시 파싱·검증·바인딩한다. 서로 다른 자산·시간 필드·필터 의미를
한 SQL로 합쳐야 하는 계획은 추측하지 않고 기존 제한된 Node 2 경로에 맡긴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlglot import exp

from app.services.analysis.logical_plan import (
    AnalysisOperation,
    AnalysisPlan,
    AnalysisTimeMode,
    PlannedField,
)
from app.services.context.query_planner import VIEW_REUSE


TYPED_SQL_COMPILER_VERSION = "ANSWERVICE-TYPED-SQL-v1.1.0"
_SUPPORTED_AGGREGATIONS = frozenset(
    {"sum", "count", "count_distinct", "average", "min", "max", "exists"}
)
_COMPARISON_OPERATORS: dict[str, type[exp.Binary]] = {
    "eq": exp.EQ,
    "neq": exp.NEQ,
    "gt": exp.GT,
    "gte": exp.GTE,
    "lt": exp.LT,
    "lte": exp.LTE,
}


def typed_sql_capabilities() -> dict[str, object]:
    """현재 결정론적 SQL 컴파일러가 실제로 여는 구조적 capability를 반환한다."""

    return {
        "version": TYPED_SQL_COMPILER_VERSION,
        "query_strategies": [VIEW_REUSE],
        "operations": sorted(item.value for item in AnalysisOperation),
        "time_modes": sorted(item.value for item in AnalysisTimeMode),
        "max_physical_assets": 1,
        "join_plans": [],
    }


def compile_typed_sql(
    plan: AnalysisPlan,
    package: object,
) -> dict[str, object] | None:
    """지원 가능한 VIEW_REUSE 계획을 SQLGlot AST로 컴파일한다.

    반환값이 ``None``이면 계획이 현재 결정론적 범위 밖이라는 뜻이며 안전성 실패를 성공으로
    바꾸지 않는다. 호출자는 기존 Node 2 후보를 생성하더라도 동일한 ``AnalysisPlan``과 G2
    검증을 강제해야 한다.
    """

    if (
        plan.query_strategy != VIEW_REUSE
        or plan.joins
    ):
        return None

    contracts = getattr(package, "runtime_contracts", None)
    if not isinstance(contracts, Mapping):
        return None
    rules = _rules_by_id(contracts.get("metric_rules"))
    package_metrics = {
        str(metric.id): metric for metric in tuple(getattr(package, "metrics", ()))
    }
    dependency_ids = set(plan.dependency_metric_ids)
    if (
        not rules
        or set(rules) != dependency_ids
        or set(package_metrics) != dependency_ids
    ):
        return None

    leaf_rules = tuple(
        rule for rule in rules.values() if _source_kind(rule) == "column"
    )
    if not leaf_rules or any(
        str(rule.get("aggregation", "")).casefold()
        not in _SUPPORTED_AGGREGATIONS
        for rule in leaf_rules
    ):
        return None

    source_assets = {
        _field(rule.get("source", {}).get("field")).asset_fqn
        for rule in leaf_rules
    }
    source_assets.update(
        item.asset_fqn
        for item in (*plan.dimension_fields, *plan.filter_fields, *plan.time_fields)
    )
    if len(source_assets) != 1:
        return None
    source_fqn = next(iter(source_assets))

    if len(set(plan.time_fields)) != 1:
        return None
    time_field = plan.time_fields[0]
    time_type = _time_native_type(contracts.get("time_rules"), time_field)
    if time_type is None:
        return None

    filter_sets = {_filter_signature(rule) for rule in leaf_rules}
    if len(filter_sets) != 1:
        return None
    filters = next(iter(filter_sets))
    if any(item[0] != source_fqn for item in filters):
        return None

    projection_ids = tuple(
        dict.fromkeys((*plan.output_metric_ids, *plan.dependency_metric_ids))
    )
    metric_aliases = {
        metric_id: str(rules[metric_id].get("result_field") or "")
        for metric_id in projection_ids
    }
    if (
        any(not value for value in metric_aliases.values())
        or len({value.casefold() for value in metric_aliases.values()})
        != len(metric_aliases)
    ):
        return None

    table_alias = "source_view"
    grouped_fields = _grouped_fields(plan)
    dimension_aliases = _dimension_aliases(
        grouped_fields,
        time_field,
        plan.operation,
        frozenset(value.casefold() for value in metric_aliases.values()),
    )
    if dimension_aliases is None:
        return None

    if plan.time_mode is AnalysisTimeMode.RANGE:
        if not plan.period_parameters or plan.snapshot_parameter is not None:
            return None
        primary = _period_predicate(
            time_field,
            table_alias,
            plan.period_parameters[0],
            time_type,
        )
        comparison = (
            _period_predicate(
                time_field,
                table_alias,
                plan.period_parameters[1],
                time_type,
            )
            if plan.operation is AnalysisOperation.PERIOD_COMPARISON
            and len(plan.period_parameters) == 2
            else None
        )
    else:
        if (
            plan.period_parameters
            or not plan.snapshot_parameter
            or plan.operation
            in {AnalysisOperation.TIME_TREND, AnalysisOperation.PERIOD_COMPARISON}
        ):
            return None
        primary = _latest_snapshot_predicate(
            time_field,
            source_fqn,
            table_alias,
            plan.snapshot_parameter,
            time_type,
        )
        comparison = None
    if plan.operation is AnalysisOperation.PERIOD_COMPARISON and comparison is None:
        return None

    projections: list[exp.Expression] = []
    for field in grouped_fields:
        projections.append(
            exp.column(field.column, table=table_alias).as_(dimension_aliases[field])
        )
    for metric_id in projection_ids:
        expression = _metric_expression(metric_id, rules, table_alias, frozenset())
        if expression is None:
            return None
        result_alias = metric_aliases[metric_id]
        if comparison is None:
            projections.append(expression.as_(result_alias))
        else:
            projections.extend(
                (
                    exp.Filter(
                        this=expression.copy(),
                        expression=exp.Where(this=primary.copy()),
                    ).as_(result_alias),
                    exp.Filter(
                        this=expression.copy(),
                        expression=exp.Where(this=comparison.copy()),
                    ).as_(f"{result_alias}__comparison"),
                )
            )

    query = exp.select(*projections).from_(
        exp.to_table(source_fqn).as_(table_alias)
    )
    filter_predicates = [
        _filter_predicate(item, table_alias) for item in sorted(filters)
    ]
    if comparison is None:
        query = query.where(primary, *filter_predicates)
    else:
        query = query.where(
            exp.or_(primary.copy(), comparison.copy()),
            *filter_predicates,
        )
    if grouped_fields:
        query = query.group_by(
            *(exp.column(item.column, table=table_alias) for item in grouped_fields)
        )

    if plan.operation in {AnalysisOperation.TOP_N, AnalysisOperation.BOTTOM_N}:
        query = query.order_by(
            exp.Ordered(
                this=exp.column(metric_aliases[plan.output_metric_ids[0]]),
                desc=plan.operation is AnalysisOperation.TOP_N,
            ),
            *(
                exp.Ordered(this=exp.column(dimension_aliases[item]), desc=False)
                for item in plan.dimension_fields
            ),
        )
    elif plan.operation is AnalysisOperation.TIME_TREND:
        query = query.order_by(
            exp.Ordered(this=exp.column(dimension_aliases[time_field]), desc=False)
        )

    policy = contracts.get("query_policy")
    max_limit = policy.get("max_limit") if isinstance(policy, Mapping) else None
    limit = plan.result_limit if plan.result_limit is not None else max_limit
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return None
    query = query.limit(limit)
    return {
        "sql": query.sql(dialect="trino"),
        "model_version": TYPED_SQL_COMPILER_VERSION,
        "plan_source": "typed_sql_compiler",
    }


def _rules_by_id(value: object) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return {}
    rules = {
        str(item.get("id")): item
        for item in value
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    return rules if len(rules) == len(value) else {}


def _source_kind(rule: Mapping[str, Any]) -> str:
    source = rule.get("source")
    return str(source.get("kind")) if isinstance(source, Mapping) else ""


def _field(value: object) -> PlannedField:
    if not isinstance(value, Mapping):
        return PlannedField("", "")
    return PlannedField(str(value.get("asset_fqn") or ""), str(value.get("column") or ""))


def _time_native_type(value: object, field: PlannedField) -> str | None:
    if not isinstance(value, Mapping) or not isinstance(value.get("fields"), list):
        return None
    matches = [
        str(item.get("native_type") or "")
        for item in value["fields"]
        if isinstance(item, Mapping) and _field(item.get("field")) == field
    ]
    return matches[0] if len(matches) == 1 and matches[0] else None


def _filter_signature(
    rule: Mapping[str, Any],
) -> tuple[tuple[str, str, str, str], ...]:
    values = rule.get("required_filters")
    if not isinstance(values, list):
        return (("", "", "", ""),)
    result = []
    for item in values:
        if not isinstance(item, Mapping):
            return (("", "", "", ""),)
        field = _field(item.get("field"))
        operator = str(item.get("operator") or "")
        parameter = str(item.get("parameter") or "")
        if not field.asset_fqn or not field.column or operator not in _COMPARISON_OPERATORS or not parameter:
            return (("", "", "", ""),)
        result.append((field.asset_fqn, field.column, operator, parameter))
    return tuple(sorted(result))


def _grouped_fields(plan: AnalysisPlan) -> tuple[PlannedField, ...]:
    fields = list(plan.dimension_fields)
    if plan.operation is AnalysisOperation.TIME_TREND and plan.time_fields[0] not in fields:
        fields.append(plan.time_fields[0])
    return tuple(fields)


def _dimension_aliases(
    fields: tuple[PlannedField, ...],
    time_field: PlannedField,
    operation: AnalysisOperation,
    reserved: frozenset[str],
) -> dict[PlannedField, str] | None:
    aliases: dict[PlannedField, str] = {}
    used = set(reserved)
    for field in fields:
        alias = (
            "period"
            if operation is AnalysisOperation.TIME_TREND and field == time_field
            else field.column
        )
        if not alias or alias.casefold() in used:
            return None
        aliases[field] = alias
        used.add(alias.casefold())
    return aliases


def _period_predicate(
    field: PlannedField,
    table_alias: str,
    parameters: tuple[str, str],
    native_type: str,
) -> exp.Expression:
    column = exp.column(field.column, table=table_alias)
    start, end = parameters
    return exp.and_(
        exp.GTE(
            this=column.copy(),
            expression=_cast_parameter(start, native_type),
        ),
        exp.LT(
            this=column.copy(),
            expression=_cast_parameter(end, native_type),
        ),
    )


def _latest_snapshot_predicate(
    field: PlannedField,
    source_fqn: str,
    table_alias: str,
    parameter: str,
    native_type: str,
) -> exp.Expression:
    """기준일 전의 실제 source 최댓값 하나를 선택하는 scalar subquery를 만든다."""

    lookup_alias = "snapshot_lookup"
    lookup = (
        exp.select(exp.Max(this=exp.column(field.column, table=lookup_alias)))
        .from_(exp.to_table(source_fqn).as_(lookup_alias))
        .where(
            exp.LT(
                this=exp.column(field.column, table=lookup_alias),
                expression=_cast_parameter(parameter, native_type),
            )
        )
    )
    return exp.EQ(
        this=exp.column(field.column, table=table_alias),
        expression=exp.Subquery(this=lookup),
    )


def _cast_parameter(name: str, native_type: str) -> exp.Cast:
    return exp.Cast(
        this=exp.Placeholder(this=name),
        to=exp.DataType.build(native_type, dialect="trino"),
    )


def _filter_predicate(
    value: tuple[str, str, str, str],
    table_alias: str,
) -> exp.Expression:
    _asset, column, operator, parameter = value
    return _COMPARISON_OPERATORS[operator](
        this=exp.column(column, table=table_alias),
        expression=exp.Placeholder(this=parameter),
    )


def _metric_expression(
    metric_id: str,
    rules: Mapping[str, Mapping[str, Any]],
    table_alias: str,
    visiting: frozenset[str],
) -> exp.Expression | None:
    if metric_id in visiting or metric_id not in rules:
        return None
    rule = rules[metric_id]
    source = rule.get("source")
    if not isinstance(source, Mapping):
        return None
    kind = str(source.get("kind") or "")
    if kind == "ratio":
        numerator = _metric_expression(
            str(source.get("numerator_metric_id") or ""),
            rules,
            table_alias,
            visiting | {metric_id},
        )
        denominator = _metric_expression(
            str(source.get("denominator_metric_id") or ""),
            rules,
            table_alias,
            visiting | {metric_id},
        )
        if (
            numerator is None
            or denominator is None
            or source.get("zero_policy") != "null_on_zero_denominator"
        ):
            return None
        return exp.Div(
            this=exp.Cast(
                this=numerator,
                to=exp.DataType.build("DOUBLE"),
            ),
            expression=exp.Nullif(
                this=denominator,
                expression=exp.Literal.number(0),
            ),
        )
    if kind != "column":
        return None
    field = _field(source.get("field"))
    column = exp.column(field.column, table=table_alias)
    aggregation = str(rule.get("aggregation") or "").casefold()
    if aggregation == "sum":
        return exp.Sum(this=column)
    if aggregation == "count":
        return exp.Count(this=column)
    if aggregation == "count_distinct":
        return exp.Count(this=exp.Distinct(expressions=[column]))
    if aggregation == "average":
        return exp.Avg(this=column)
    if aggregation == "min":
        return exp.Min(this=column)
    if aggregation == "max":
        return exp.Max(this=column)
    if aggregation == "exists":
        return exp.GT(
            this=exp.Count(this=column),
            expression=exp.Literal.number(0),
        )
    return None
