"""승인된 단일 자산 논리 계획을 결정론적 Trino SQL AST로 컴파일한다.

이 모듈의 권위 입력은 질문 원문이나 지표 이름 사전이 아니라 검증된 ``AnalysisPlan``과
``RuntimeContextPackage``다. 현재 활성 범위는 JOIN이 필요 없는 ``VIEW_REUSE``와 DataHub가
분자·분모를 완전히 승인한 단일 자산 ``RAW_APPROVED_DETAIL`` 비율식이며, 모든 결과는 기존
SQL Guard가 다시 파싱·검증·바인딩한다. 서로 다른 자산·시간 필드·필터 의미를 한 SQL로
합쳐야 하는 계획은 추측하지 않고 기존 제한된 Node 2 경로에 맡긴다.
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
    PlannedFilter,
)
from app.services.context.contract import GovernedJoin
from app.services.context.fanout_policy import FanoutPlan
from app.services.context.query_planner import (
    RAW_APPROVED_DETAIL,
    VIEW_COMPOSE,
    VIEW_REUSE,
)


TYPED_SQL_COMPILER_VERSION = "ANSWERVICE-TYPED-SQL-v1.3.2"
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


def compile_typed_sql(
    plan: AnalysisPlan,
    package: object,
) -> dict[str, object] | None:
    """지원 가능한 단일 자산 계획을 SQLGlot AST로 컴파일한다.

    반환값이 ``None``이면 계획이 현재 결정론적 범위 밖이라는 뜻이며 안전성 실패를 성공으로
    바꾸지 않는다. 호출자는 기존 Node 2 후보를 생성하더라도 동일한 ``AnalysisPlan``과 G2
    검증을 강제해야 한다.
    """

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

    if plan.joins:
        return _compile_joined_sql(plan, package, contracts, rules)
    has_governed_ratio = any(
        _source_kind(rule) == "ratio" for rule in rules.values()
    )
    if plan.query_strategy != VIEW_REUSE and not (
        plan.query_strategy == RAW_APPROVED_DETAIL and has_governed_ratio
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

    # G3 must receive the governed operands used by derived ratios.  They remain
    # internal execution evidence: the response layer removes SUPPORT-only fields
    # from API tables, charts, and the persisted presentation snapshot.
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
    group_expressions = {
        field: _group_expression(
            field,
            table_alias,
            time_field,
            plan.operation,
            plan.time_bucket,
        )
        for field in grouped_fields
    }
    for field in grouped_fields:
        projections.append(
            group_expressions[field].copy().as_(dimension_aliases[field])
        )
    for metric_id in projection_ids:
        result_alias = metric_aliases[metric_id]
        if comparison is not None and _source_kind(rules[metric_id]) == "ratio":
            primary_ratio = _metric_expression(
                metric_id,
                rules,
                table_alias,
                frozenset(),
                aggregate_filter=primary,
            )
            comparison_ratio = _metric_expression(
                metric_id,
                rules,
                table_alias,
                frozenset(),
                aggregate_filter=comparison,
            )
            if primary_ratio is None or comparison_ratio is None:
                return None
            projections.extend(
                (
                    primary_ratio.as_(result_alias),
                    comparison_ratio.as_(f"{result_alias}__comparison"),
                )
            )
            continue
        expression = _metric_expression(metric_id, rules, table_alias, frozenset())
        if expression is None:
            return None
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
            *(group_expressions[item].copy() for item in grouped_fields)
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
    elif grouped_fields:
        query = query.order_by(
            *(
                exp.Ordered(this=exp.column(dimension_aliases[item]), desc=False)
                for item in grouped_fields
            )
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


def _compile_joined_sql(
    plan: AnalysisPlan,
    package: object,
    contracts: Mapping[str, Any],
    rules: Mapping[str, Mapping[str, Any]],
) -> dict[str, object] | None:
    """정확히 두 asset과 한 governed edge인 Phase 9 계획을 AST로 컴파일한다."""

    if (
        len(plan.joins) != 1
        or plan.query_strategy
        not in {RAW_APPROVED_DETAIL, VIEW_COMPOSE, VIEW_REUSE}
        or plan.operation
        not in {AnalysisOperation.AGGREGATE, AnalysisOperation.BREAKDOWN}
        or plan.time_mode is not AnalysisTimeMode.RANGE
        or len(plan.period_parameters) != 1
        or plan.snapshot_parameter is not None
    ):
        return None
    graph = tuple(getattr(package, "join_graph", ()))
    matches = [item for item in graph if str(item.id) == plan.joins[0].join_id]
    if len(matches) != 1 or not isinstance(matches[0], GovernedJoin):
        return None
    edge = matches[0]
    endpoints = frozenset({str(edge.left), str(edge.right)})
    if len(endpoints) != 2:
        return None

    leaf_rules = {
        metric_id: rule
        for metric_id, rule in rules.items()
        if _source_kind(rule) == "column"
    }
    if not leaf_rules or any(
        str(rule.get("aggregation") or "").casefold()
        not in _SUPPORTED_AGGREGATIONS
        for rule in leaf_rules.values()
    ):
        return None
    measure_assets = {
        _field(rule.get("source", {}).get("field")).asset_fqn
        for rule in leaf_rules.values()
    }
    referenced_assets = {
        item.asset_fqn
        for item in (*plan.dimension_fields, *plan.filter_fields, *plan.time_fields)
    } | measure_assets
    if referenced_assets != endpoints or not measure_assets.issubset(endpoints):
        return None

    time_fields = {item.asset_fqn: item for item in plan.time_fields}
    if len(time_fields) != len(plan.time_fields) or not measure_assets.issubset(time_fields):
        return None
    time_types = {
        asset: _time_native_type(contracts.get("time_rules"), field)
        for asset, field in time_fields.items()
    }
    if any(value is None for value in time_types.values()):
        return None
    filters = _joined_filter_rules(plan, rules)
    if filters is None or any(item[0] not in endpoints for item in filters):
        return None

    projection_ids = tuple(
        dict.fromkeys((*plan.output_metric_ids, *plan.dependency_metric_ids))
    )
    metric_aliases = {
        metric_id: str(rules[metric_id].get("result_field") or "")
        for metric_id in plan.dependency_metric_ids
    }
    if (
        any(not value for value in metric_aliases.values())
        or len({value.casefold() for value in metric_aliases.values()})
        != len(metric_aliases)
    ):
        return None
    dimension_aliases = _dimension_aliases(
        tuple(plan.dimension_fields),
        plan.time_fields[0],
        plan.operation,
        frozenset(value.casefold() for value in metric_aliases.values()),
    )
    if dimension_aliases is None:
        return None

    strategy = plan.joins[0].plan
    if strategy == FanoutPlan.DIRECT_JOIN.value:
        query = _compile_direct_join(
            plan,
            edge,
            rules,
            projection_ids,
            metric_aliases,
            dimension_aliases,
            filters,
            time_fields,
            time_types,
        )
    elif strategy == FanoutPlan.PREAGGREGATE.value:
        query = _compile_preaggregate_join(
            plan,
            edge,
            rules,
            projection_ids,
            metric_aliases,
            dimension_aliases,
            filters,
            time_fields,
            time_types,
        )
    elif strategy == FanoutPlan.SEMI_JOIN.value:
        query = _compile_semi_join(
            plan,
            edge,
            rules,
            projection_ids,
            metric_aliases,
            dimension_aliases,
            filters,
            time_fields,
            time_types,
            measure_assets,
        )
    else:
        return None
    if query is None:
        return None
    if plan.operation is AnalysisOperation.BREAKDOWN:
        query = query.order_by(
            *(
                exp.Ordered(this=exp.column(dimension_aliases[item]), desc=False)
                for item in plan.dimension_fields
            )
        )
    query = _bounded_limit(query, plan, contracts)
    if query is None:
        return None
    return {
        "sql": query.sql(dialect="trino"),
        "model_version": TYPED_SQL_COMPILER_VERSION,
        "plan_source": "typed_sql_compiler",
    }


def _compile_direct_join(
    plan: AnalysisPlan,
    edge: GovernedJoin,
    rules: Mapping[str, Mapping[str, Any]],
    projection_ids: tuple[str, ...],
    metric_aliases: Mapping[str, str],
    dimension_aliases: Mapping[PlannedField, str],
    filters: tuple[tuple[str, str, str, str], ...],
    time_fields: Mapping[str, PlannedField],
    time_types: Mapping[str, str | None],
) -> exp.Select | None:
    aliases = {str(edge.left): "joined_left", str(edge.right): "joined_right"}
    projections = _joined_projections(
        plan,
        rules,
        projection_ids,
        metric_aliases,
        dimension_aliases,
        aliases,
    )
    if projections is None:
        return None
    predicates = _time_and_filter_predicates(
        plan, aliases, filters, time_fields, time_types
    )
    join_predicates = _edge_predicates(edge, aliases)
    if not join_predicates:
        return None
    query = (
        exp.select(*projections)
        .from_(exp.to_table(str(edge.left)).as_(aliases[str(edge.left)]))
        .join(
            exp.to_table(str(edge.right)).as_(aliases[str(edge.right)]),
            on=exp.and_(*join_predicates),
            join_type=str(edge.kind).upper(),
        )
    )
    if predicates:
        query = query.where(*predicates)
    if plan.dimension_fields:
        query = query.group_by(
            *(
                exp.column(item.column, table=aliases[item.asset_fqn])
                for item in plan.dimension_fields
            )
        )
    return query


def _compile_preaggregate_join(
    plan: AnalysisPlan,
    edge: GovernedJoin,
    rules: Mapping[str, Mapping[str, Any]],
    projection_ids: tuple[str, ...],
    metric_aliases: Mapping[str, str],
    dimension_aliases: Mapping[PlannedField, str],
    filters: tuple[tuple[str, str, str, str], ...],
    time_fields: Mapping[str, PlannedField],
    time_types: Mapping[str, str | None],
) -> exp.Select | None:
    oriented = _many_one_assets(edge)
    if oriented is None:
        return None
    many_asset, one_asset = oriented
    many_alias, child_alias, one_alias = "many_source", "many_preaggregated", "one_source"
    group_columns = _preaggregation_columns(edge, many_asset)
    if not group_columns or any(
        item.asset_fqn != one_asset for item in plan.dimension_fields
    ):
        return None
    many_leaf_ids = tuple(
        metric_id
        for metric_id, rule in rules.items()
        if _source_kind(rule) == "column"
        and _field(rule.get("source", {}).get("field")).asset_fqn == many_asset
    )
    if not many_leaf_ids:
        return None
    child_metric_projections: list[exp.Expression] = []
    for metric_id in many_leaf_ids:
        rule = rules[metric_id]
        aggregation = str(rule.get("aggregation") or "").casefold()
        if aggregation not in {"sum", "count", "count_distinct", "min", "max"}:
            return None
        expression = _metric_expression(metric_id, rules, many_alias, frozenset())
        if expression is None:
            return None
        child_metric_projections.append(expression.as_(metric_aliases[metric_id]))
    child = exp.select(
        *(
            exp.column(column, table=many_alias).as_(column)
            for column in group_columns
        ),
        *child_metric_projections,
    ).from_(exp.to_table(many_asset).as_(many_alias))
    child_predicates = _time_and_filter_predicates(
        plan,
        {many_asset: many_alias},
        tuple(item for item in filters if item[0] == many_asset),
        {many_asset: time_fields[many_asset]},
        {many_asset: time_types[many_asset]},
    )
    if child_predicates:
        child = child.where(*child_predicates)
    child = child.group_by(
        *(exp.column(column, table=many_alias) for column in group_columns)
    )

    aliases = {many_asset: child_alias, one_asset: one_alias}
    projections = _joined_projections(
        plan,
        rules,
        projection_ids,
        metric_aliases,
        dimension_aliases,
        aliases,
        preaggregated_asset=many_asset,
    )
    if projections is None:
        return None
    join_predicates = _edge_predicates(edge, aliases)
    if not join_predicates:
        return None
    query = (
        exp.select(*projections)
        .from_(exp.to_table(one_asset).as_(one_alias))
        .join(
            exp.Subquery(this=child).as_(child_alias),
            on=exp.and_(*join_predicates),
            join_type=str(edge.kind).upper(),
        )
    )
    root_predicates = _time_and_filter_predicates(
        plan,
        {one_asset: one_alias},
        tuple(item for item in filters if item[0] == one_asset),
        (
            {one_asset: time_fields[one_asset]}
            if one_asset in time_fields
            else {}
        ),
        (
            {one_asset: time_types[one_asset]}
            if one_asset in time_types
            else {}
        ),
    )
    if root_predicates:
        query = query.where(*root_predicates)
    if plan.dimension_fields:
        query = query.group_by(
            *(exp.column(item.column, table=one_alias) for item in plan.dimension_fields)
        )
    return query


def _compile_semi_join(
    plan: AnalysisPlan,
    edge: GovernedJoin,
    rules: Mapping[str, Mapping[str, Any]],
    projection_ids: tuple[str, ...],
    metric_aliases: Mapping[str, str],
    dimension_aliases: Mapping[PlannedField, str],
    filters: tuple[tuple[str, str, str, str], ...],
    time_fields: Mapping[str, PlannedField],
    time_types: Mapping[str, str | None],
    measure_assets: set[str],
) -> exp.Select | None:
    oriented = _many_one_assets(edge)
    if oriented is None:
        return None
    many_asset, one_asset = oriented
    if measure_assets != {one_asset} or any(
        item.asset_fqn != one_asset for item in plan.dimension_fields
    ):
        return None
    many_filters = tuple(item for item in filters if item[0] == many_asset)
    if not many_filters:
        return None
    one_alias, many_alias = "one_source", "filter_source"
    aliases = {one_asset: one_alias, many_asset: many_alias}
    projections = _joined_projections(
        plan,
        rules,
        projection_ids,
        metric_aliases,
        dimension_aliases,
        {one_asset: one_alias},
    )
    if projections is None:
        return None
    correlations = _edge_predicates(edge, aliases)
    if not correlations:
        return None
    inner = exp.select(exp.Literal.number(1)).from_(
        exp.to_table(many_asset).as_(many_alias)
    ).where(
        *correlations,
        *(_filter_predicate(item, many_alias) for item in many_filters),
    )
    query = exp.select(*projections).from_(
        exp.to_table(one_asset).as_(one_alias)
    )
    root_predicates = _time_and_filter_predicates(
        plan,
        {one_asset: one_alias},
        tuple(item for item in filters if item[0] == one_asset),
        {one_asset: time_fields[one_asset]},
        {one_asset: time_types[one_asset]},
    )
    query = query.where(*root_predicates, exp.Exists(this=inner))
    if plan.dimension_fields:
        query = query.group_by(
            *(exp.column(item.column, table=one_alias) for item in plan.dimension_fields)
        )
    return query


def _joined_projections(
    plan: AnalysisPlan,
    rules: Mapping[str, Mapping[str, Any]],
    projection_ids: tuple[str, ...],
    metric_aliases: Mapping[str, str],
    dimension_aliases: Mapping[PlannedField, str],
    aliases: Mapping[str, str],
    *,
    preaggregated_asset: str | None = None,
) -> list[exp.Expression] | None:
    projections: list[exp.Expression] = [
        exp.column(item.column, table=aliases[item.asset_fqn]).as_(
            dimension_aliases[item]
        )
        for item in plan.dimension_fields
        if item.asset_fqn in aliases
    ]
    if len(projections) != len(plan.dimension_fields):
        return None
    for metric_id in projection_ids:
        expression = _joined_metric_expression(
            metric_id,
            rules,
            aliases,
            frozenset(),
            preaggregated_asset=preaggregated_asset,
        )
        if expression is None:
            return None
        projections.append(expression.as_(metric_aliases[metric_id]))
    return projections


def _joined_metric_expression(
    metric_id: str,
    rules: Mapping[str, Mapping[str, Any]],
    aliases: Mapping[str, str],
    visiting: frozenset[str],
    *,
    preaggregated_asset: str | None,
) -> exp.Expression | None:
    if metric_id in visiting or metric_id not in rules:
        return None
    rule = rules[metric_id]
    source = rule.get("source")
    if not isinstance(source, Mapping):
        return None
    if source.get("kind") == "ratio":
        numerator = _joined_metric_expression(
            str(source.get("numerator_metric_id") or ""),
            rules,
            aliases,
            visiting | {metric_id},
            preaggregated_asset=preaggregated_asset,
        )
        denominator = _joined_metric_expression(
            str(source.get("denominator_metric_id") or ""),
            rules,
            aliases,
            visiting | {metric_id},
            preaggregated_asset=preaggregated_asset,
        )
        if (
            numerator is None
            or denominator is None
            or source.get("zero_policy") != "null_on_zero_denominator"
        ):
            return None
        return exp.Div(
            this=exp.Cast(this=numerator, to=exp.DataType.build("DOUBLE")),
            expression=exp.Nullif(
                this=denominator,
                expression=exp.Literal.number(0),
            ),
        )
    if source.get("kind") != "column":
        return None
    field = _field(source.get("field"))
    alias = aliases.get(field.asset_fqn)
    if alias is None:
        return None
    if field.asset_fqn == preaggregated_asset:
        return exp.Sum(this=exp.column(str(rule.get("result_field")), table=alias))
    return _metric_expression(metric_id, rules, alias, frozenset())


def _joined_filter_rules(
    plan: AnalysisPlan,
    rules: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[str, str, str, str], ...] | None:
    values = {
        (item.asset_fqn, item.column, item.operator, item.parameter)
        for item in plan.filter_fields
    }
    for rule in rules.values():
        if _source_kind(rule) != "column":
            continue
        signature = _filter_signature(rule)
        if signature == (("", "", "", ""),):
            return None
        values.update(signature)
    return tuple(sorted(values))


def _time_and_filter_predicates(
    plan: AnalysisPlan,
    aliases: Mapping[str, str],
    filters: tuple[tuple[str, str, str, str], ...],
    time_fields: Mapping[str, PlannedField],
    time_types: Mapping[str, str | None],
) -> list[exp.Expression]:
    predicates: list[exp.Expression] = []
    for asset in sorted(aliases):
        if asset in time_fields and time_types.get(asset):
            predicates.append(
                _period_predicate(
                    time_fields[asset],
                    aliases[asset],
                    plan.period_parameters[0],
                    str(time_types[asset]),
                )
            )
    predicates.extend(
        _filter_predicate(item, aliases[item[0]])
        for item in filters
        if item[0] in aliases
    )
    return predicates


def _edge_predicates(
    edge: GovernedJoin,
    aliases: Mapping[str, str],
) -> list[exp.Expression]:
    predicates: list[exp.Expression] = []
    for left, right in edge.equality_conditions:
        left_field = _edge_field(left, aliases)
        right_field = _edge_field(right, aliases)
        if left_field is None or right_field is None:
            return []
        predicates.append(exp.EQ(this=left_field, expression=right_field))
    if edge.temporal_conditions:
        return []
    return predicates


def _edge_field(value: str, aliases: Mapping[str, str]) -> exp.Column | None:
    matches = [asset for asset in aliases if value.startswith(f"{asset}.")]
    if len(matches) != 1:
        return None
    asset = matches[0]
    column = value.removeprefix(f"{asset}.")
    if not column or "." in column:
        return None
    return exp.column(column, table=aliases[asset])


def _many_one_assets(edge: GovernedJoin) -> tuple[str, str] | None:
    if edge.cardinality == "many_to_one":
        return str(edge.left), str(edge.right)
    if edge.cardinality == "one_to_many":
        return str(edge.right), str(edge.left)
    return None


def _preaggregation_columns(
    edge: GovernedJoin,
    asset_fqn: str,
) -> tuple[str, ...]:
    result = []
    for value in (*edge.preaggregation_grain, *edge.preaggregation_keys):
        prefix = f"{asset_fqn}."
        if not value.startswith(prefix):
            continue
        column = value.removeprefix(prefix)
        if not column or "." in column:
            return ()
        result.append(column)
    return tuple(dict.fromkeys(result))


def _bounded_limit(
    query: exp.Select,
    plan: AnalysisPlan,
    contracts: Mapping[str, Any],
) -> exp.Select | None:
    policy = contracts.get("query_policy")
    max_limit = policy.get("max_limit") if isinstance(policy, Mapping) else None
    limit = plan.result_limit if plan.result_limit is not None else max_limit
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return None
    return query.limit(limit)


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
    fields: list[PlannedField] = []
    if plan.operation is AnalysisOperation.TIME_TREND:
        fields.append(plan.time_fields[0])
    fields.extend(item for item in plan.dimension_fields if item not in fields)
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


def _group_expression(
    field: PlannedField,
    table_alias: str,
    time_field: PlannedField,
    operation: AnalysisOperation,
    time_bucket: str,
) -> exp.Expression:
    """계획의 논리 시간 grain을 물리 source field의 결정론적 AST로 컴파일한다."""

    column = exp.column(field.column, table=table_alias)
    if (
        operation is not AnalysisOperation.TIME_TREND
        or field != time_field
        or time_bucket == "day"
    ):
        return column
    return exp.Cast(
        this=exp.TimestampTrunc(
            this=column,
            unit=exp.Var(this=time_bucket.upper()),
        ),
        to=exp.DataType.build("DATE"),
    )


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
    *,
    aggregate_filter: exp.Expression | None = None,
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
            aggregate_filter=aggregate_filter,
        )
        denominator = _metric_expression(
            str(source.get("denominator_metric_id") or ""),
            rules,
            table_alias,
            visiting | {metric_id},
            aggregate_filter=aggregate_filter,
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
        aggregate: exp.Expression | None = exp.Sum(this=column)
    elif aggregation == "count":
        aggregate = exp.Count(this=column)
    elif aggregation == "count_distinct":
        aggregate = exp.Count(this=exp.Distinct(expressions=[column]))
    elif aggregation == "average":
        aggregate = exp.Avg(this=column)
    elif aggregation == "min":
        aggregate = exp.Min(this=column)
    elif aggregation == "max":
        aggregate = exp.Max(this=column)
    elif aggregation == "exists":
        aggregate = exp.Count(this=column)
        aggregate = _with_aggregate_filter(aggregate, aggregate_filter)
        return exp.GT(
            this=aggregate,
            expression=exp.Literal.number(0),
        )
    else:
        aggregate = None
    return _with_aggregate_filter(aggregate, aggregate_filter)


def _with_aggregate_filter(
    aggregate: exp.Expression | None,
    predicate: exp.Expression | None,
) -> exp.Expression | None:
    """기간 비교 ratio의 leaf 집계에만 동일한 반개방 기간 FILTER를 결속한다."""

    if aggregate is None or predicate is None:
        return aggregate
    return exp.Filter(
        this=aggregate,
        expression=exp.Where(this=predicate.copy()),
    )
