from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from sqlglot import exp, parse_one

from app.services.context.builder import (
    ContextAsset,
    ContextBuildRequest,
    ContextMetric,
    ContextMetricTerm,
    ContextPackageBuilder,
    ContextParameterBinding,
    ContextRequiredFilter,
)
from app.services.context.contract import GovernedJoin, enrich_context_package
from app.services.analysis.logical_plan import (
    AnalysisOperation,
    AnalysisPlanError,
    AnalysisTimeMode,
    build_analysis_plan,
    validate_analysis_plan_payload,
)
from app.services.analysis.typed_sql_compiler import (
    TYPED_SQL_COMPILER_VERSION,
    compile_typed_sql,
)
from app.services.analysis.result_validator import PipelineResultValidator
from app.services.context.query_planner import VIEW_REUSE
from app.services.sql_guard import apply_guard_decision, validate_plan
from src.ai.schema import ContractError, validate_payload
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V2


def _package(fqn: str = "orbit.ops.event_fact"):
    asset = ContextAsset(
        urn=f"urn:test:{fqn}",
        fqn=fqn,
        columns=("occurred_on", "amount", "active"),
        column_types=(("occurred_on", "date"), ("amount", "double"), ("active", "boolean")),
        metrics=(
            ContextMetric(
                id="governed_amount",
                asset_fqn=fqn,
                field="amount",
                aggregation="sum",
                time_field="occurred_on",
                required_filters=(ContextRequiredFilter("active", "eq", True),),
                result_field="governed_total",
                unit="credits",
                governance_version=RUNTIME_GOVERNANCE_VERSION_V2,
                allowed_roles=("analyst",),
                contains_pii=False,
                allowed_join_ids=(),
                join_required=False,
                query_strategies=("RAW_APPROVED_DETAIL",),
            ),
        ),
        metric_registry_required=True,
    )
    base = ContextPackageBuilder().build(
        ContextBuildRequest(
            context_release="context-runtime-7",
            policy_version="policy-runtime-4",
            time_version="calendar-runtime-2",
            entitlement_hash="entitled-user",
            assets=(asset,),
            token_count=10,
            model_context_tokens=8_000,
            parameter_bindings=(
                ContextParameterBinding("window_begin", "date", "2026-07-01"),
                ContextParameterBinding("window_stop", "date", "2026-08-01"),
                ContextParameterBinding("active_flag", "boolean", True),
            ),
            metric_terms=(
                ContextMetricTerm(
                    id="governed_amount",
                    urn="urn:li:glossaryTerm:governed_amount",
                    label="Governed amount",
                    aliases=("Governed amount",),
                    definition="Runtime-governed amount.",
                    unit="credits",
                    version="term-runtime-1",
                    checksum="term-checksum",
                ),
            ),
        ),
        frozenset({asset.urn}),
    )
    contracts = {
        "schema_context": {
            "version": base.context_release,
            "assets": [
                {
                    "urn": asset.urn,
                    "fqn": fqn,
                    "grain": {"kind": "event", "keys": ["occurred_on"]},
                    "columns": [
                        {
                            "name": name,
                            "native_type": dict(asset.column_types)[name],
                            "nullable": False,
                            "role": (
                                "time" if name == "occurred_on" else
                                "measure" if name == "amount" else "attribute"
                            ),
                        }
                        for name in asset.columns
                    ],
                }
            ],
        },
        "metric_rules": [
            {
                "id": "governed_amount",
                "source": {
                    "kind": "column",
                    "field": {"asset_fqn": fqn, "column": "amount"},
                },
                "aggregation": "sum",
                "result_field": "governed_total",
                "unit": "credits",
                "time_field": {"asset_fqn": fqn, "column": "occurred_on"},
                "dimensions": [],
                "required_filters": [
                    {
                        "field": {"asset_fqn": fqn, "column": "active"},
                        "operator": "eq",
                        "parameter": "active_flag",
                    }
                ],
            }
        ],
        "join_graph": {"edges": []},
        "time_rules": {
            "timezone": "Asia/Seoul",
            "calendar_id": "gregorian-kr",
            "interval": "[start,end)",
            "start_parameter": "window_begin",
            "end_parameter": "window_stop",
            "fields": [
                {
                    "field": {"asset_fqn": fqn, "column": "occurred_on"},
                    "native_type": "date",
                    "bucket": "day",
                    "timezone_mode": "preserve",
                }
            ],
        },
        "parameter_contract": {
            "style": "named",
            "parameters": [
                {"name": "window_begin", "type": "date", "scope": "time"},
                {"name": "window_stop", "type": "date", "scope": "time"},
                {"name": "active_flag", "type": "boolean", "scope": "filter"},
            ],
        },
        "query_policy": {
            "dialect": "trino",
            "statement_type": "select",
            "read_only": True,
            "require_limit": True,
            "max_limit": 100,
            "allowed_functions": ["SUM", "MAX", "CAST"],
            "allowed_catalogs": [fqn.split(".", 1)[0]],
        },
    }
    return enrich_context_package(base, contracts, ())


def _sql(
    fqn: str = "orbit.ops.event_fact",
    *,
    start_predicate: str | None = None,
    filter_predicate: str | None = None,
) -> str:
    start = start_predicate or "e.occurred_on >= CAST(:window_begin AS DATE)"
    required_filter = filter_predicate or "e.active = :active_flag"
    return f"""
        SELECT SUM(e.amount) AS governed_total
        FROM {fqn} AS e
        WHERE {start}
          AND e.occurred_on < CAST(:window_stop AS DATE)
          AND {required_filter}
        LIMIT 100
    """


def _joined_package(*, kind: str = "inner", preaggregation: bool = False):
    package = _package()
    joined_metric = replace(
        package.metrics[0],
        allowed_join_ids=("customer_edge",),
        join_required=True,
    )
    fact = replace(
        package.assets[0],
        columns=(*package.assets[0].columns, "customer_id"),
        column_types=(*package.assets[0].column_types, ("customer_id", "varchar")),
        join_ids=("customer_edge",),
        metrics=(joined_metric,),
    )
    dimension = ContextAsset(
        urn="urn:test:orbit.ops.customer_dim",
        fqn="orbit.ops.customer_dim",
        columns=("customer_id", "segment"),
        column_types=(("customer_id", "varchar"), ("segment", "varchar")),
        join_ids=("customer_edge",),
        metric_registry_required=True,
    )
    join = GovernedJoin(
        id="customer_edge",
        left=fact.fqn,
        right=dimension.fqn,
        kind=kind,
        cardinality="many_to_one",
        equality_conditions=(
            (f"{fact.fqn}.customer_id", f"{dimension.fqn}.customer_id"),
        ),
        temporal_conditions=(),
        preaggregation_required=preaggregation,
        preaggregation_grain=(f"{fact.fqn}.occurred_on",),
        preaggregation_keys=(f"{fact.fqn}.customer_id",),
    )
    contracts = deepcopy(package.runtime_contracts)
    contracts["schema_context"]["assets"] = [
        {
            **contracts["schema_context"]["assets"][0],
            "columns": [
                *contracts["schema_context"]["assets"][0]["columns"],
                {
                    "name": "customer_id",
                    "native_type": "varchar",
                    "nullable": False,
                    "role": "identifier",
                },
            ],
        },
        {
            "urn": dimension.urn,
            "fqn": dimension.fqn,
            "grain": {"kind": "row", "keys": ["customer_id"]},
            "columns": [
                {
                    "name": "customer_id",
                    "native_type": "varchar",
                    "nullable": False,
                    "role": "identifier",
                },
                {
                    "name": "segment",
                    "native_type": "varchar",
                    "nullable": False,
                    "role": "dimension",
                },
            ],
        },
    ]
    contracts["join_graph"] = {"edges": [join.as_dict()]}
    return replace(
        package,
        assets=(fact, dimension),
        dataset_count=2,
        column_count=len(fact.columns) + len(dimension.columns),
        approved_join_ids=(join.id,),
        metrics=(joined_metric,),
        runtime_contracts=contracts,
        join_graph=(join,),
    )


def test_v2_metric_must_allow_every_join_edge_used_by_sql() -> None:
    package = _joined_package()
    denied_metric = replace(
        package.metrics[0],
        allowed_join_ids=(),
        join_required=False,
    )
    denied = replace(package, metrics=(denied_metric,))

    decision = validate_plan({"sql": _joined_sql()}, denied)

    assert decision.violation == "JOIN_PERMISSION_DENIED"


def test_guard_records_the_runtime_fanout_decision() -> None:
    decision = validate_plan({"sql": _joined_sql()}, _joined_package())

    assert decision.ok, decision
    assert decision.ast_evidence is not None
    assert decision.ast_evidence["fanout_plans"] == [
        {
            "join_id": "customer_edge",
            "plan": "DIRECT_JOIN",
            "reason": "UNIQUE_ONE_SIDE",
        }
    ]


def test_logical_analysis_plan_is_compiled_from_runtime_slots_not_question_text() -> None:
    package = _package()

    plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_amount",
            "intent_candidates": ["general"],
            "period_relationship": "single",
        },
        package,
    )

    assert plan.operation is AnalysisOperation.AGGREGATE
    assert plan.output_metric_ids == ("governed_amount",)
    assert plan.period_parameters == (("window_begin", "window_stop"),)
    assert plan.context_package_hash == package.package_hash
    assert validate_analysis_plan_payload(plan.as_dict(), package) == plan


def test_logical_plan_preserves_the_governed_filter_predicate_identity() -> None:
    package = _package()

    plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_amount",
            "intent_candidates": ["general"],
            "period_relationship": "single",
            "filter_fields": [
                {
                    "asset_fqn": "orbit.ops.event_fact",
                    "column": "active",
                    "operator": "eq",
                    "value_text": "true",
                },
            ],
        },
        package,
    )

    assert [item.as_dict() for item in plan.filter_fields] == [
        {
            "asset_fqn": "orbit.ops.event_fact",
            "column": "active",
            "operator": "eq",
            "parameter": "active_flag",
        }
    ]
    assert validate_analysis_plan_payload(plan.as_dict(), package) == plan


def test_logical_plan_removes_eq_filtered_field_from_aggregate_grouping() -> None:
    """값이 고정된 필터 필드는 aggregate GROUP BY로 중복 실행하지 않는다."""

    package = _ranked_package()
    plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_amount",
            "analysis_operation": "aggregate",
            "intent_candidates": ["aggregate"],
            "period_relationship": "single",
            "dimension_fields": [
                {"asset_fqn": "orbit.ops.event_fact", "column": "active"}
            ],
            "filter_fields": [
                {
                    "asset_fqn": "orbit.ops.event_fact",
                    "column": "active",
                    "operator": "eq",
                    "value_text": "true",
                }
            ],
        },
        package,
    )

    assert plan.operation is AnalysisOperation.AGGREGATE
    assert plan.dimension_fields == ()
    assert [item.as_dict() for item in plan.filter_fields] == [
        {
            "asset_fqn": "orbit.ops.event_fact",
            "column": "active",
            "operator": "eq",
            "parameter": "active_flag",
        }
    ]
    assert validate_analysis_plan_payload(plan.as_dict(), package) == plan


def _view_reuse_package(package):
    """동형 테스트 계약을 승인 Serving 단일 뷰 전략으로 전환한다."""

    return replace(
        package,
        metrics=tuple(
            replace(metric, query_strategies=(VIEW_REUSE,))
            for metric in package.metrics
        ),
        query_strategy=VIEW_REUSE,
    )


def _snapshot_view_reuse_package():
    """특정 도메인 이름 없이 기준일 전 최신 snapshot 계약을 구성한다."""

    package = _view_reuse_package(_package())
    contracts = deepcopy(package.runtime_contracts)
    contracts["time_rules"] = {
        "timezone": "Asia/Seoul",
        "calendar_id": "gregorian-kr",
        "mode": "latest_snapshot",
        "selection": "max_source_value_lt_as_of",
        "as_of_parameter": "snapshot_as_of",
        "fields": deepcopy(package.runtime_contracts["time_rules"]["fields"]),
    }
    contracts["parameter_contract"]["parameters"] = [
        {"name": "snapshot_as_of", "type": "date", "scope": "time"},
        {"name": "active_flag", "type": "boolean", "scope": "filter"},
    ]
    return replace(
        package,
        runtime_contracts=contracts,
        parameter_bindings=(
            ContextParameterBinding("snapshot_as_of", "date", "2026-08-20"),
            ContextParameterBinding("active_flag", "boolean", True),
        ),
    )


def _multi_metric_view_reuse_package(*, shared_filters: bool = True):
    """같은 물리 뷰의 두 지표가 필터 의미를 공유하거나 분리하는 계약을 만든다."""

    package = _view_reuse_package(_package())
    first = package.metrics[0]
    second = replace(
        first,
        id="governed_count",
        field="active",
        aggregation="count",
        result_field="governed_count",
        unit="rows",
        required_filters=first.required_filters if shared_filters else (),
    )
    contracts = deepcopy(package.runtime_contracts)
    second_rule = deepcopy(contracts["metric_rules"][0])
    second_rule.update(
        id=second.id,
        source={
            "kind": "column",
            "field": {"asset_fqn": second.asset_fqn, "column": second.field},
        },
        aggregation="count",
        result_field=second.result_field,
        unit=second.unit,
        required_filters=(
            deepcopy(contracts["metric_rules"][0]["required_filters"])
            if shared_filters
            else []
        ),
    )
    contracts["metric_rules"].append(second_rule)
    contracts["query_policy"]["allowed_functions"].append("COUNT")
    return replace(
        package,
        metrics=(first, second),
        runtime_contracts=contracts,
    )


def test_typed_sql_compiler_builds_a_guarded_view_reuse_aggregate() -> None:
    """특정 지표명 없이 단일 Serving View 집계를 SQLGlot AST로 생성한다."""

    package = _view_reuse_package(_package())
    plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_amount",
            "analysis_operation": "aggregate",
            "period_relationship": "single",
        },
        package,
    )

    candidate = compile_typed_sql(plan, package)

    assert candidate is not None
    assert candidate["model_version"] == TYPED_SQL_COMPILER_VERSION
    assert candidate["plan_source"] == "typed_sql_compiler"
    candidate["analysis_plan"] = plan.as_dict()
    accepted = validate_plan(candidate, package)
    assert accepted.ok, accepted
    assert accepted.ast_evidence is not None
    assert accepted.ast_evidence["analysis_operation"] == "aggregate"


def test_typed_sql_compiler_handles_multiple_metrics_with_one_filter_scope() -> None:
    """같은 시간·필터 의미를 공유하는 여러 Metric은 한 SELECT로 안전하게 합성한다."""

    package = _multi_metric_view_reuse_package()
    plan = build_analysis_plan(
        {
            "selected_metric_ids": ["governed_amount", "governed_count"],
            "analysis_operation": "aggregate",
            "period_relationship": "single",
        },
        package,
    )

    candidate = compile_typed_sql(plan, package)

    assert candidate is not None
    candidate["analysis_plan"] = plan.as_dict()
    accepted = validate_plan(candidate, package)
    assert accepted.ok, accepted


@pytest.mark.parametrize(
    ("operation", "expected_order"),
    [("top_n", "DESC"), ("bottom_n", "ASC")],
)
def test_typed_sql_compiler_builds_stable_ranked_view_reuse_queries(
    operation: str,
    expected_order: str,
) -> None:
    """순위 연산은 첫 지표와 모든 차원 tie-breaker를 계획 순서로 생성한다."""

    package = _view_reuse_package(_ranked_package())
    plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_amount",
            "analysis_operation": operation,
            "result_limit": 5,
            "dimension_fields": [
                {"asset_fqn": "orbit.ops.event_fact", "column": "active"}
            ],
            "period_relationship": "single",
        },
        package,
    )

    candidate = compile_typed_sql(plan, package)

    assert candidate is not None
    assert f"governed_total {expected_order}" in str(candidate["sql"])
    candidate["analysis_plan"] = plan.as_dict()
    accepted = validate_plan(candidate, package)
    assert accepted.ok, accepted


def test_typed_sql_compiler_builds_time_trend_and_period_comparison() -> None:
    """같은 컴파일 경로가 시간 추이와 두 반개방 기간의 조건부 집계를 모두 지원한다."""

    trend_package = _view_reuse_package(_package())
    trend_plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_amount",
            "analysis_operation": "time_trend",
            "analysis_time_bucket": "day",
            "period_relationship": "single",
        },
        trend_package,
    )
    trend = compile_typed_sql(trend_plan, trend_package)
    assert trend is not None
    trend["analysis_plan"] = trend_plan.as_dict()
    assert validate_plan(trend, trend_package).ok

    comparison_package = _view_reuse_package(_comparison_package())
    comparison_plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_amount",
            "analysis_operation": "period_comparison",
            "period_relationship": "comparison",
        },
        comparison_package,
    )
    comparison = compile_typed_sql(comparison_plan, comparison_package)
    assert comparison is not None
    assert "FILTER(WHERE" in str(comparison["sql"]).replace(" ", "")
    comparison["analysis_plan"] = comparison_plan.as_dict()
    accepted = validate_plan(comparison, comparison_package)
    assert accepted.ok, accepted


def test_typed_sql_compiler_builds_and_guards_latest_snapshot_selection() -> None:
    """명시적 계약은 source의 기준일 전 MAX snapshot 하나만 선택해 G2를 통과한다."""

    package = _snapshot_view_reuse_package()
    plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_amount",
            "analysis_operation": "aggregate",
            "period_relationship": "single",
        },
        package,
    )

    assert plan.time_mode is AnalysisTimeMode.LATEST_SNAPSHOT
    assert plan.period_parameters == ()
    assert plan.snapshot_parameter == "snapshot_as_of"
    assert validate_analysis_plan_payload(plan.as_dict(), package) == plan

    candidate = compile_typed_sql(plan, package)
    assert candidate is not None
    sql = str(candidate["sql"])
    assert "MAX(snapshot_lookup.occurred_on)" in sql
    assert "snapshot_lookup.occurred_on < CAST(:snapshot_as_of AS DATE)" in sql
    assert "source_view.occurred_on = (SELECT" in sql
    candidate["analysis_plan"] = plan.as_dict()
    accepted = validate_plan(candidate, package)
    assert accepted.ok, accepted


@pytest.mark.parametrize("mutation", ["inclusive_cutoff", "wrong_reducer", "non_conjunctive"])
def test_latest_snapshot_guard_rejects_semantic_shape_mutations(mutation: str) -> None:
    """기준일 경계·MAX reducer·최상위 AND equality가 달라지면 실행 전에 차단한다."""

    package = _snapshot_view_reuse_package()
    package.runtime_contracts["query_policy"]["allowed_functions"].append("MIN")
    if mutation == "non_conjunctive":
        contracts = deepcopy(package.runtime_contracts)
        contracts["metric_rules"][0]["required_filters"] = []
        contracts["parameter_contract"]["parameters"] = [
            {"name": "snapshot_as_of", "type": "date", "scope": "time"}
        ]
        package = replace(
            package,
            metrics=(replace(package.metrics[0], required_filters=()),),
            runtime_contracts=contracts,
            parameter_bindings=(
                ContextParameterBinding("snapshot_as_of", "date", "2026-08-20"),
            ),
        )
    plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_amount",
            "analysis_operation": "aggregate",
            "period_relationship": "single",
        },
        package,
    )
    candidate = compile_typed_sql(plan, package)
    assert candidate is not None
    expression = parse_one(str(candidate["sql"]), read="trino")
    if mutation == "inclusive_cutoff":
        cutoff = next(
            item
            for item in expression.find_all(exp.LT)
            if item.find(exp.Placeholder) is not None
        )
        cutoff.replace(exp.LTE(this=cutoff.this.copy(), expression=cutoff.expression.copy()))
    elif mutation == "wrong_reducer":
        reducer = next(expression.find_all(exp.Max))
        reducer.replace(exp.Min(this=reducer.this.copy()))
    else:
        where = expression.args["where"]
        where.set("this", exp.or_(where.this.copy(), exp.Boolean(this=True)))
    rejected = validate_plan(
        {"sql": expression.sql(dialect="trino"), "analysis_plan": plan.as_dict()},
        package,
    )
    assert rejected.violation == "TIME_RULE_MISMATCH"


@pytest.mark.parametrize("operation", ["time_trend", "period_comparison"])
def test_latest_snapshot_plan_does_not_invent_range_operations(operation: str) -> None:
    """스냅샷 계약을 추이 또는 두 기간 비교로 재해석하지 않는다."""

    with pytest.raises(AnalysisPlanError) as captured:
        build_analysis_plan(
            {
                "selected_metric_id": "governed_amount",
                "analysis_operation": operation,
                "period_relationship": (
                    "comparison" if operation == "period_comparison" else "single"
                ),
            },
            _snapshot_view_reuse_package(),
        )
    assert captured.value.code.value == "TIME_MODE_NOT_GOVERNED"


def test_typed_sql_compiler_does_not_guess_a_join_or_mixed_filter_scope() -> None:
    """단일 뷰 경계를 벗어난 계획은 SQL을 만들지 않고 기존 guarded 경로로 남긴다."""

    joined = _joined_package()
    joined_plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_amount",
            "analysis_operation": "aggregate",
            "period_relationship": "single",
        },
        joined,
    )
    assert compile_typed_sql(joined_plan, joined) is None

    mixed = _multi_metric_view_reuse_package(shared_filters=False)
    mixed_plan = build_analysis_plan(
        {
            "selected_metric_ids": ["governed_amount", "governed_count"],
            "analysis_operation": "aggregate",
            "period_relationship": "single",
        },
        mixed,
    )
    assert compile_typed_sql(mixed_plan, mixed) is None


def test_typed_sql_compiler_builds_a_ratio_from_governed_operands() -> None:
    """동일 scope의 분자·분모는 DOUBLE/NULLIF 비율식과 원본 증거를 함께 생성한다."""

    package = _multi_metric_view_reuse_package()
    numerator, denominator = (
        replace(metric, visibility="SUPPORT") for metric in package.metrics
    )
    ratio = ContextMetric(
        id="governed_ratio",
        asset_fqn="",
        field="",
        aggregation="ratio",
        time_field="",
        required_filters=(),
        result_field="governed_ratio",
        unit="ratio",
        numerator_metric_id=numerator.id,
        denominator_metric_id=denominator.id,
        zero_policy="null_on_zero_denominator",
        governance_version=RUNTIME_GOVERNANCE_VERSION_V2,
        allowed_roles=("analyst",),
        contains_pii=False,
        allowed_join_ids=(),
        join_required=False,
        query_strategies=(VIEW_REUSE,),
    )
    contracts = deepcopy(package.runtime_contracts)
    contracts["metric_rules"].append(
        {
            "id": ratio.id,
            "source": {
                "kind": "ratio",
                "numerator_metric_id": numerator.id,
                "denominator_metric_id": denominator.id,
                "zero_policy": ratio.zero_policy,
            },
            "aggregation": "ratio",
            "result_field": ratio.result_field,
            "unit": ratio.unit,
            "time_field": None,
            "dimensions": [],
            "required_filters": [],
        }
    )
    contracts["query_policy"]["allowed_functions"].append("NULLIF")
    package = replace(
        package,
        metrics=(numerator, denominator, ratio),
        runtime_contracts=contracts,
    )
    plan = build_analysis_plan(
        {
            "selected_metric_id": ratio.id,
            "analysis_operation": "aggregate",
            "period_relationship": "single",
        },
        package,
    )

    candidate = compile_typed_sql(plan, package)

    assert candidate is not None
    assert "NULLIF" in str(candidate["sql"])
    assert str(candidate["sql"]).count(" AS governed_total") == 1
    assert str(candidate["sql"]).count(" AS governed_count") == 1
    assert str(candidate["sql"]).count(" AS governed_ratio") == 1
    candidate["analysis_plan"] = plan.as_dict()
    accepted = validate_plan(candidate, package)
    assert accepted.ok, accepted

    apply_guard_decision(candidate, accepted)
    columns = tuple(candidate["ast_evidence"]["projection_aliases"])
    rows = [
        {
            "governed_ratio": 2.0,
            "governed_total": 10.0,
            "governed_count": 5,
        }
    ]
    query = {
        "evidence_complete": True,
        "query_id": "ratio-evidence-query",
        "rows": rows,
        "result_metadata": PipelineResultValidator.result_metadata(rows, columns),
        "filters": {},
        "sampling": {"applied": False, "returned_rows": 1, "total_rows": 1},
        "masking": {"applied": False, "fields": []},
    }
    assert PipelineResultValidator.g3_violation(query, candidate, package) is None


@pytest.mark.parametrize(
    "invalid_filter",
    [
        {"asset_fqn": "orbit.ops.event_fact", "column": "active"},
        {
            "asset_fqn": "orbit.ops.event_fact",
            "column": "active",
            "operator": "contains",
            "value_text": "true",
        },
        {
            "asset_fqn": "orbit.ops.event_fact",
            "column": "active",
            "operator": "eq",
            "value_text": "",
        },
    ],
)
def test_logical_plan_rejects_invalid_filter_predicate_contract(
    invalid_filter: dict[str, str],
) -> None:
    with pytest.raises(AnalysisPlanError, match="filter_fields"):
        build_analysis_plan(
            {
                "selected_metric_id": "governed_amount",
                "intent_candidates": ["general"],
                "period_relationship": "single",
                "filter_fields": [invalid_filter],
            },
            _package(),
        )


def test_logical_plan_rejects_a_dimension_not_bound_to_the_selected_metric() -> None:
    package = _joined_package()

    with pytest.raises(AnalysisPlanError, match="binding"):
        build_analysis_plan(
            {
                "selected_metric_id": "governed_amount",
                "intent_candidates": ["breakdown"],
                "period_relationship": "single",
                "dimension_fields": [
                    {
                        "asset_fqn": "orbit.ops.customer_dim",
                        "column": "segment",
                    }
                ],
            },
            package,
        )


def test_logical_plan_checksum_cannot_be_reused_with_another_context() -> None:
    package = _package()
    plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_amount",
            "intent_candidates": ["aggregate"],
            "period_relationship": "single",
        },
        package,
    ).as_dict()
    plan["context_package_hash"] = "different-context"

    with pytest.raises(AnalysisPlanError, match="checksum"):
        validate_analysis_plan_payload(plan, package)


def _ranked_package():
    package = _package()
    contracts = deepcopy(package.runtime_contracts)
    contracts["metric_rules"][0]["dimensions"] = [
        {"asset_fqn": "orbit.ops.event_fact", "column": "active"}
    ]
    return replace(package, runtime_contracts=contracts)


def test_guard_enforces_top_n_order_direction_and_exact_result_limit() -> None:
    package = _ranked_package()
    plan = build_analysis_plan(
        {
            "selected_metric_ids": ["governed_amount"],
            "analysis_operation": "top_n",
            "result_limit": 5,
            "dimension_fields": [
                {"asset_fqn": "orbit.ops.event_fact", "column": "active"}
            ],
            "period_relationship": "single",
        },
        package,
    )
    sql = """
        SELECT e.active, SUM(e.amount) AS governed_total
        FROM orbit.ops.event_fact AS e
        WHERE e.occurred_on >= CAST(:window_begin AS DATE)
          AND e.occurred_on < CAST(:window_stop AS DATE)
          AND e.active = :active_flag
        GROUP BY e.active
        ORDER BY governed_total DESC, active ASC
        LIMIT 5
    """

    accepted = validate_plan(
        {"sql": sql, "analysis_plan": plan.as_dict()},
        package,
    )
    wrong_direction = validate_plan(
        {
            "sql": sql.replace("DESC", "ASC"),
            "analysis_plan": plan.as_dict(),
        },
        package,
    )
    wrong_limit = validate_plan(
        {
            "sql": sql.replace("LIMIT 5", "LIMIT 6"),
            "analysis_plan": plan.as_dict(),
        },
        package,
    )
    missing_tie_breaker = validate_plan(
        {
            "sql": sql.replace(", active ASC", ""),
            "analysis_plan": plan.as_dict(),
        },
        package,
    )

    assert accepted.ok, accepted
    assert wrong_direction.violation == "ANALYSIS_OPERATION_MISMATCH"
    assert wrong_limit.violation == "ANALYSIS_OPERATION_MISMATCH"
    assert missing_tie_breaker.violation == "ANALYSIS_OPERATION_MISMATCH"


def test_guard_enforces_time_trend_group_projection_and_ascending_order() -> None:
    package = _package()
    plan = build_analysis_plan(
        {
            "selected_metric_ids": ["governed_amount"],
            "analysis_operation": "time_trend",
            "analysis_time_bucket": "day",
            "period_relationship": "single",
        },
        package,
    )
    sql = """
        SELECT e.occurred_on AS period, SUM(e.amount) AS governed_total
        FROM orbit.ops.event_fact AS e
        WHERE e.occurred_on >= CAST(:window_begin AS DATE)
          AND e.occurred_on < CAST(:window_stop AS DATE)
          AND e.active = :active_flag
        GROUP BY e.occurred_on
        ORDER BY period ASC
        LIMIT 100
    """

    accepted = validate_plan(
        {"sql": sql, "analysis_plan": plan.as_dict()},
        package,
    )
    descending = validate_plan(
        {
            "sql": sql.replace("period ASC", "period DESC"),
            "analysis_plan": plan.as_dict(),
        },
        package,
    )

    assert accepted.ok, accepted
    assert descending.violation == "ANALYSIS_OPERATION_MISMATCH"


def test_monthly_time_trend_compiles_exact_rollup_and_rejects_ast_mutations() -> None:
    """일 단위 source의 월 추이는 compiler 소유 DATE_TRUNC 구조만 허용한다."""

    package = _view_reuse_package(_package())
    plan = build_analysis_plan(
        {
            "selected_metric_ids": ["governed_amount"],
            "analysis_operation": "time_trend",
            "analysis_time_bucket": "month",
            "period_relationship": "single",
        },
        package,
    )
    candidate = compile_typed_sql(plan, package)
    assert candidate is not None
    assert "DATE_TRUNC('MONTH', source_view.occurred_on)" in str(candidate["sql"])
    candidate["analysis_plan"] = plan.as_dict()
    accepted = validate_plan(candidate, package)
    assert accepted.ok, accepted

    wrong_unit = parse_one(str(candidate["sql"]), dialect="trino")
    for truncation in wrong_unit.find_all(exp.TimestampTrunc):
        truncation.set("unit", exp.Var(this="QUARTER"))
    wrong_unit_decision = validate_plan(
        {
            "sql": wrong_unit.sql(dialect="trino"),
            "analysis_plan": plan.as_dict(),
        },
        package,
    )

    missing_cast = parse_one(str(candidate["sql"]), dialect="trino")
    for cast in tuple(missing_cast.find_all(exp.Cast)):
        if isinstance(cast.this, exp.TimestampTrunc):
            cast.replace(cast.this.copy())
    missing_cast_decision = validate_plan(
        {
            "sql": missing_cast.sql(dialect="trino"),
            "analysis_plan": plan.as_dict(),
        },
        package,
    )

    wrong_field = parse_one(str(candidate["sql"]), dialect="trino")
    for truncation in wrong_field.find_all(exp.TimestampTrunc):
        truncation.set("this", exp.column("active", table="source_view"))
    wrong_field_decision = validate_plan(
        {
            "sql": wrong_field.sql(dialect="trino"),
            "analysis_plan": plan.as_dict(),
        },
        package,
    )

    assert wrong_unit_decision.violation == "ANALYSIS_OPERATION_MISMATCH"
    assert missing_cast_decision.violation == "ANALYSIS_OPERATION_MISMATCH"
    assert wrong_field_decision.violation == "ANALYSIS_OPERATION_MISMATCH"


def _joined_sql(
    join_kind: str = "INNER",
    *,
    join_predicate: str | None = None,
) -> str:
    predicate = join_predicate or "f.customer_id = d.customer_id"
    return f"""
        SELECT SUM(f.amount) AS governed_total
        FROM orbit.ops.event_fact AS f
        {join_kind} JOIN orbit.ops.customer_dim AS d
          ON {predicate}
        WHERE f.occurred_on >= CAST(:window_begin AS DATE)
          AND f.occurred_on < CAST(:window_stop AS DATE)
          AND f.active = :active_flag
        LIMIT 100
    """


def _allow_case(package):
    contracts = deepcopy(package.runtime_contracts)
    contracts["query_policy"]["allowed_functions"].extend(["CASE", "IF"])
    return replace(package, runtime_contracts=contracts)


def _preaggregated_sql() -> str:
    return """
        WITH fact_rollup AS (
            SELECT f.occurred_on,
                   f.customer_id,
                   SUM(f.amount) AS governed_total
            FROM orbit.ops.event_fact AS f
            WHERE f.occurred_on >= CAST(:window_begin AS DATE)
              AND f.occurred_on < CAST(:window_stop AS DATE)
              AND f.active = :active_flag
            GROUP BY f.occurred_on, f.customer_id
        )
        SELECT SUM(p.governed_total) AS governed_total
        FROM fact_rollup AS p
        INNER JOIN orbit.ops.customer_dim AS d
          ON p.customer_id = d.customer_id
        LIMIT 100
    """


@pytest.mark.parametrize("fqn", ["orbit.ops.event_fact", "cobalt.raw.signal_log"])
def test_isomorphic_runtime_schemas_share_the_same_ast_governance(fqn: str) -> None:
    package = _package(fqn)
    plan = {
        "sql": _sql(fqn),
        "declared_assets": [fqn],
        "declared_metrics": ["governed_amount"],
    }

    decision = validate_plan(plan, package)
    apply_guard_decision(plan, decision)

    assert decision.ok, decision
    assert plan["ast_evidence"]["physical_tables"] == [fqn]
    assert ":window_begin" in plan["sql"]
    assert list(parse_one(plan["executable_sql"], read="trino").find_all(exp.Placeholder)) == []
    assert plan["parameters"]["active_flag"]["value"] is True


def test_ast_mutations_fail_the_governed_contract() -> None:
    package = _package()
    base = parse_one(_sql(), read="trino")

    outside_table = base.copy()
    outside_table.find(exp.Table).replace(exp.to_table("outside.secret.records"))

    wrong_aggregation = base.copy()
    total = wrong_aggregation.find(exp.Sum)
    total.replace(exp.Max(this=total.this.copy()))

    missing_filter = base.copy()
    active_predicate = next(
        item
        for item in missing_filter.find_all(exp.EQ)
        if item.find(exp.Column).name == "active"
    )
    active_predicate.replace(exp.true())

    closed_period = base.copy()
    end_predicate = next(
        item
        for item in closed_period.find_all(exp.LT)
        if item.find(exp.Placeholder) is not None
    )
    end_predicate.replace(exp.LTE(this=end_predicate.this.copy(), expression=end_predicate.expression.copy()))

    cases = {
        "ASSET_SCOPE_MISMATCH": outside_table,
        "METRIC_RULE_MISMATCH": wrong_aggregation,
        "REQUIRED_FILTER_MISSING": missing_filter,
        "TIME_RULE_MISMATCH": closed_period,
    }
    for expected, expression in cases.items():
        decision = validate_plan(
            {
                "sql": expression.sql(dialect="trino"),
                "declared_metrics": ["governed_amount"],
            },
            package,
        )
        assert decision.violation == expected


def test_model_lineage_must_match_ast_not_a_self_reported_oracle() -> None:
    decision = validate_plan(
        {
            "sql": _sql(),
            "declared_assets": ["outside.secret.records"],
            "declared_metrics": ["governed_amount"],
        },
        _package(),
    )

    assert decision.violation == "MODEL_LINEAGE_MISMATCH"


def test_binding_uses_server_owned_values_and_rejects_extra_parameters() -> None:
    package = _package()
    package = replace(
        package,
        parameter_bindings=(
            *package.parameter_bindings,
            ContextParameterBinding("unused", "string", "not SQL"),
        ),
    )

    decision = validate_plan(
        {
            "sql": _sql(),
            "declared_assets": ["orbit.ops.event_fact"],
            "declared_metrics": ["governed_amount"],
        },
        package,
    )

    assert decision.violation == "PARAMETER_CONTRACT_MISMATCH"


def test_live_node2_contract_rejects_formula_metadata() -> None:
    package = _package()
    request = {
        "question_id": "arbitrary-request",
        "normalized_question": "Compute the selected governed metric.",
        "resolved_request": {
            "intent": "aggregate",
            "metric_ids": ["governed_amount"],
            "output_metric_ids": ["governed_amount"],
            "dimensions": [],
            "filters": deepcopy(package.runtime_contracts["metric_rules"][0]["required_filters"]),
            "time_bucket": "none",
            "result_limit": None,
        },
        **deepcopy(package.runtime_contracts),
    }
    request["metric_rules"][0]["formula"] = {
        "operator": "add",
        "operands": ["component_a", "component_b"],
    }

    with pytest.raises(ContractError):
        validate_payload("node2_request", request)


def test_clause_scope_prevents_predicate_relocation_bypasses() -> None:
    package = _joined_package()
    cases = {
        "join_in_where": """
            SELECT SUM(f.amount) AS governed_total
            FROM orbit.ops.event_fact AS f
            INNER JOIN orbit.ops.customer_dim AS d ON TRUE
            WHERE f.customer_id = d.customer_id
              AND f.occurred_on >= CAST(:window_begin AS DATE)
              AND f.occurred_on < CAST(:window_stop AS DATE)
              AND f.active = :active_flag
            LIMIT 100
        """,
        "filter_in_join": """
            SELECT SUM(f.amount) AS governed_total
            FROM orbit.ops.event_fact AS f
            INNER JOIN orbit.ops.customer_dim AS d
              ON f.customer_id = d.customer_id AND f.active = :active_flag
            WHERE f.occurred_on >= CAST(:window_begin AS DATE)
              AND f.occurred_on < CAST(:window_stop AS DATE)
            LIMIT 100
        """,
        "time_in_having": """
            SELECT SUM(f.amount) AS governed_total
            FROM orbit.ops.event_fact AS f
            INNER JOIN orbit.ops.customer_dim AS d
              ON f.customer_id = d.customer_id
            WHERE f.occurred_on < CAST(:window_stop AS DATE)
              AND f.active = :active_flag
            HAVING f.occurred_on >= CAST(:window_begin AS DATE)
            LIMIT 100
        """,
    }

    assert validate_plan({"sql": _joined_sql()}, package).ok
    assert validate_plan({"sql": cases["join_in_where"]}, package).violation == (
        "JOIN_GRAPH_MISMATCH"
    )
    assert validate_plan({"sql": cases["filter_in_join"]}, package).violation == (
        "REQUIRED_FILTER_MISSING"
    )
    assert validate_plan({"sql": cases["time_in_having"]}, package).violation == (
        "TIME_RULE_MISMATCH"
    )


@pytest.mark.parametrize(
    "predicate",
    [
        "(e.active = :active_flag OR e.active = :active_flag)",
        "NOT (e.active = :active_flag)",
        "CASE WHEN e.active = :active_flag THEN TRUE ELSE FALSE END",
    ],
    ids=("or", "not", "case"),
)
def test_required_filter_requires_a_top_level_and_conjunct(predicate: str) -> None:
    decision = validate_plan(
        {"sql": _sql(filter_predicate=predicate)},
        _allow_case(_package()),
    )

    assert decision.violation == "REQUIRED_FILTER_MISSING"


@pytest.mark.parametrize(
    "predicate",
    [
        "(e.occurred_on >= CAST(:window_begin AS DATE) OR "
        "e.occurred_on >= CAST(:window_begin AS DATE))",
        "NOT (e.occurred_on >= CAST(:window_begin AS DATE))",
        "CASE WHEN e.occurred_on >= CAST(:window_begin AS DATE) "
        "THEN TRUE ELSE FALSE END",
    ],
    ids=("or", "not", "case"),
)
def test_time_boundary_requires_a_top_level_and_conjunct(predicate: str) -> None:
    decision = validate_plan(
        {"sql": _sql(start_predicate=predicate)},
        _allow_case(_package()),
    )

    assert decision.violation == "TIME_RULE_MISMATCH"


@pytest.mark.parametrize(
    "predicate",
    [
        "(f.customer_id = d.customer_id OR f.customer_id = d.customer_id)",
        "NOT (f.customer_id = d.customer_id)",
        "CASE WHEN f.customer_id = d.customer_id THEN TRUE ELSE FALSE END",
    ],
    ids=("or", "not", "case"),
)
def test_join_predicate_requires_a_top_level_and_conjunct(predicate: str) -> None:
    decision = validate_plan(
        {"sql": _joined_sql(join_predicate=predicate)},
        _allow_case(_joined_package()),
    )

    assert decision.violation == "JOIN_GRAPH_MISMATCH"


def test_parenthesized_and_tree_remains_valid_clause_evidence() -> None:
    sql = """
        SELECT SUM(e.amount) AS governed_total
        FROM orbit.ops.event_fact AS e
        WHERE (
            e.occurred_on >= CAST(:window_begin AS DATE)
            AND (
                e.occurred_on < CAST(:window_stop AS DATE)
                AND e.active = :active_flag
            )
        )
        LIMIT 100
    """

    decision = validate_plan({"sql": sql}, _package())

    assert decision.ok, decision


def test_join_kind_and_post_join_preaggregation_decoys_fail_closed() -> None:
    assert validate_plan(
        {"sql": _joined_sql("LEFT")},
        _joined_package(kind="inner"),
    ).violation == "JOIN_GRAPH_MISMATCH"

    post_join_grouping = _joined_sql().replace(
        "LIMIT 100",
        "GROUP BY f.occurred_on, f.customer_id LIMIT 100",
    )
    decision = validate_plan(
        {"sql": post_join_grouping},
        _joined_package(preaggregation=True),
    )
    assert decision.violation == "GRAIN_VIOLATION"
    assert "direct child scope" in decision.detail


def test_governed_preaggregation_requires_proven_child_scope_lineage() -> None:
    package = _joined_package(preaggregation=True)
    plan = {
        "sql": _preaggregated_sql(),
        "declared_assets": [
            "orbit.ops.event_fact",
            "orbit.ops.customer_dim",
        ],
        "declared_columns": [
            {"asset_fqn": "orbit.ops.event_fact", "column": name}
            for name in ("occurred_on", "customer_id", "amount", "active")
        ] + [
            {"asset_fqn": "orbit.ops.customer_dim", "column": "customer_id"}
        ],
        "declared_joins": ["customer_edge"],
        "declared_metrics": ["governed_amount"],
    }

    accepted = validate_plan(plan, package)

    assert accepted.ok, accepted
    mutations = (
        _preaggregated_sql().replace(
            "GROUP BY f.occurred_on, f.customer_id",
            "GROUP BY f.customer_id",
        ),
        _preaggregated_sql().replace("f.customer_id,\n", ""),
        _preaggregated_sql().replace(
            "SUM(f.amount) AS governed_total",
            "MAX(f.amount) AS governed_total",
        ),
    )
    assert {
        validate_plan({"sql": sql}, package).violation for sql in mutations
    } == {"GRAIN_VIOLATION", "METRIC_RULE_MISMATCH"}


@pytest.mark.parametrize(
    "projection",
    [
        "SUM(e.amount) + 1",
        "MAX(e.amount) + SUM(0)",
        "-SUM(e.amount)",
    ],
)
def test_metric_projection_requires_the_exact_governed_ast_shape(projection: str) -> None:
    sql = _sql().replace("SUM(e.amount)", projection)
    decision = validate_plan({"sql": sql}, _package())

    assert decision.violation == "METRIC_RULE_MISMATCH"


def test_legacy_negative_sum_cannot_be_relabelled_as_plain_sum() -> None:
    package = _package()
    package = replace(
        package,
        metrics=(replace(package.metrics[0], aggregation="negative_sum"),),
    )

    decision = validate_plan({"sql": _sql()}, package)

    assert decision.violation == "METRIC_RULE_MISMATCH"


def test_multiple_selected_column_metrics_share_one_governed_output_scope() -> None:
    package = _package()
    second = replace(
        package.metrics[0],
        id="governed_count",
        field="active",
        aggregation="count",
        result_field="governed_count",
        unit="rows",
    )
    contracts = deepcopy(package.runtime_contracts)
    second_rule = deepcopy(contracts["metric_rules"][0])
    second_rule.update(
        id=second.id,
        source={
            "kind": "column",
            "field": {
                "asset_fqn": second.asset_fqn,
                "column": second.field,
            },
        },
        aggregation="count",
        result_field=second.result_field,
        unit=second.unit,
    )
    contracts["metric_rules"].append(second_rule)
    contracts["query_policy"]["allowed_functions"].append("COUNT")
    package = replace(
        package,
        metrics=(package.metrics[0], second),
        runtime_contracts=contracts,
    )
    sql = _sql().replace(
        "SUM(e.amount) AS governed_total",
        "SUM(e.amount) AS governed_total, COUNT(e.active) AS governed_count",
    )

    accepted = validate_plan({"sql": sql}, package)
    rejected = validate_plan(
        {"sql": sql.replace("COUNT(e.active)", "COUNT(DISTINCT e.active)")},
        package,
    )

    assert accepted.ok, accepted
    assert rejected.violation == "METRIC_RULE_MISMATCH"


def test_ratio_metric_projects_numerator_and_denominator_with_nullif_zero_guard() -> None:
    package = _package()
    numerator = package.metrics[0]
    denominator = replace(
        numerator,
        id="governed_count",
        field="active",
        aggregation="count",
        result_field="governed_count",
        unit="rows",
        required_filters=(),
    )
    ratio = ContextMetric(
        id="governed_ratio",
        asset_fqn="",
        field="",
        aggregation="ratio",
        time_field="",
        required_filters=(),
        result_field="governed_ratio",
        unit="ratio",
        numerator_metric_id="governed_amount",
        denominator_metric_id="governed_count",
        zero_policy="null_on_zero_denominator",
        governance_version=RUNTIME_GOVERNANCE_VERSION_V2,
        allowed_roles=("analyst",),
        contains_pii=False,
        allowed_join_ids=(),
        join_required=False,
        query_strategies=("RAW_APPROVED_DETAIL",),
    )
    contracts = deepcopy(package.runtime_contracts)
    denominator_rule = deepcopy(contracts["metric_rules"][0])
    denominator_rule.update(
        id=denominator.id,
        source={
            "kind": "column",
            "field": {"asset_fqn": denominator.asset_fqn, "column": denominator.field},
        },
        aggregation="count",
        result_field=denominator.result_field,
        unit=denominator.unit,
        required_filters=[],
    )
    contracts["metric_rules"].append(denominator_rule)
    contracts["metric_rules"].append(
        {
            "id": ratio.id,
            "source": {
                "kind": "ratio",
                "numerator_metric_id": "governed_amount",
                "denominator_metric_id": "governed_count",
                "zero_policy": "null_on_zero_denominator",
            },
            "aggregation": "ratio",
            "result_field": ratio.result_field,
            "unit": ratio.unit,
            "time_field": None,
            "dimensions": [],
            "required_filters": [],
        }
    )
    contracts["query_policy"]["allowed_functions"].extend(["COUNT", "NULLIF"])
    package = replace(
        package,
        metrics=(numerator, denominator, ratio),
        runtime_contracts=contracts,
    )
    sql = _sql().replace(
        "SUM(e.amount) AS governed_total",
        "SUM(e.amount) AS governed_total, COUNT(e.active) AS governed_count, "
        "CAST(SUM(e.amount) AS DOUBLE) / NULLIF(COUNT(e.active), 0) AS governed_ratio",
    )

    accepted = validate_plan({"sql": sql}, package)
    swapped = validate_plan(
        {"sql": sql.replace(
            "CAST(SUM(e.amount) AS DOUBLE) / NULLIF(COUNT(e.active), 0) AS governed_ratio",
            "CAST(COUNT(e.active) AS DOUBLE) / NULLIF(SUM(e.amount), 0) AS governed_ratio",
        )},
        package,
    )
    missing_nullif = validate_plan(
        {"sql": sql.replace(
            "CAST(SUM(e.amount) AS DOUBLE) / NULLIF(COUNT(e.active), 0) AS governed_ratio",
            "CAST(SUM(e.amount) AS DOUBLE) / COUNT(e.active) AS governed_ratio",
        )},
        package,
    )
    integer_division = validate_plan(
        {"sql": sql.replace(
            "CAST(SUM(e.amount) AS DOUBLE) / NULLIF(COUNT(e.active), 0) AS governed_ratio",
            "SUM(e.amount) / NULLIF(COUNT(e.active), 0) AS governed_ratio",
        )},
        package,
    )

    assert accepted.ok, accepted
    assert swapped.violation == "METRIC_RULE_MISMATCH"
    assert missing_nullif.violation == "METRIC_RULE_MISMATCH"
    assert integer_division.violation == "METRIC_RULE_MISMATCH"


def _exists_package():
    package = _package()
    exists_metric = replace(
        package.metrics[0],
        id="governed_exists",
        field="active",
        aggregation="exists",
        result_field="governed_exists",
        unit="boolean",
        required_filters=(),
    )
    contracts = deepcopy(package.runtime_contracts)
    exists_rule = deepcopy(contracts["metric_rules"][0])
    exists_rule.update(
        id=exists_metric.id,
        source={
            "kind": "column",
            "field": {"asset_fqn": exists_metric.asset_fqn, "column": exists_metric.field},
        },
        aggregation="exists",
        result_field=exists_metric.result_field,
        unit=exists_metric.unit,
        required_filters=[],
    )
    contracts["metric_rules"].append(exists_rule)
    contracts["query_policy"]["allowed_functions"].append("COUNT")
    return replace(
        package,
        metrics=(package.metrics[0], exists_metric),
        runtime_contracts=contracts,
    )


def test_exists_metric_projects_count_greater_than_zero() -> None:
    package = _exists_package()
    sql = _sql().replace(
        "SUM(e.amount) AS governed_total",
        "SUM(e.amount) AS governed_total, COUNT(e.active) > 0 AS governed_exists",
    )

    accepted = validate_plan({"sql": sql}, package)

    assert accepted.ok, accepted


def test_exists_metric_rejects_a_bare_unfiltered_count() -> None:
    package = _exists_package()
    sql = _sql().replace(
        "SUM(e.amount) AS governed_total",
        "SUM(e.amount) AS governed_total, COUNT(e.active) AS governed_exists",
    )

    rejected = validate_plan({"sql": sql}, package)

    assert rejected.violation == "METRIC_RULE_MISMATCH"


def test_exists_metric_rejects_a_non_zero_threshold() -> None:
    package = _exists_package()
    sql = _sql().replace(
        "SUM(e.amount) AS governed_total",
        "SUM(e.amount) AS governed_total, COUNT(e.active) > 1 AS governed_exists",
    )

    rejected = validate_plan({"sql": sql}, package)

    assert rejected.violation == "METRIC_RULE_MISMATCH"


def _comparison_package():
    package = _package()
    contracts = deepcopy(package.runtime_contracts)
    contracts["time_rules"]["comparison_window"] = {
        "start_parameter": "comparison_begin",
        "end_parameter": "comparison_stop",
    }
    contracts["parameter_contract"]["parameters"].extend(
        [
            {"name": "comparison_begin", "type": "date", "scope": "time"},
            {"name": "comparison_stop", "type": "date", "scope": "time"},
        ]
    )
    return replace(
        package,
        runtime_contracts=contracts,
        parameter_bindings=(
            *package.parameter_bindings,
            ContextParameterBinding("comparison_begin", "date", "2026-06-01"),
            ContextParameterBinding("comparison_stop", "date", "2026-07-01"),
        ),
    )


_COMPARISON_SQL = """
    SELECT
      SUM(e.amount) FILTER (
        WHERE e.occurred_on >= CAST(:window_begin AS DATE) AND e.occurred_on < CAST(:window_stop AS DATE)
      ) AS governed_total,
      SUM(e.amount) FILTER (
        WHERE e.occurred_on >= CAST(:comparison_begin AS DATE) AND e.occurred_on < CAST(:comparison_stop AS DATE)
      ) AS governed_total__comparison
    FROM orbit.ops.event_fact AS e
    WHERE e.active = :active_flag
    LIMIT 100
"""


def test_comparison_window_projects_metric_twice_with_filter_predicates() -> None:
    package = _comparison_package()

    accepted = validate_plan({"sql": _COMPARISON_SQL}, package)

    assert accepted.ok, accepted


def test_comparison_window_rejects_a_bare_unfiltered_projection() -> None:
    package = _comparison_package()
    sql = _COMPARISON_SQL.replace(
        "SUM(e.amount) FILTER (\n"
        "        WHERE e.occurred_on >= CAST(:comparison_begin AS DATE) AND e.occurred_on < CAST(:comparison_stop AS DATE)\n"
        "      ) AS governed_total__comparison",
        "SUM(e.amount) AS governed_total__comparison",
    )

    rejected = validate_plan({"sql": sql}, package)

    assert rejected.violation == "METRIC_RULE_MISMATCH"


def test_comparison_window_rejects_swapped_primary_and_comparison_predicates() -> None:
    package = _comparison_package()
    swapped_sql = """
        SELECT
          SUM(e.amount) FILTER (
            WHERE e.occurred_on >= CAST(:comparison_begin AS DATE) AND e.occurred_on < CAST(:comparison_stop AS DATE)
          ) AS governed_total,
          SUM(e.amount) FILTER (
            WHERE e.occurred_on >= CAST(:window_begin AS DATE) AND e.occurred_on < CAST(:window_stop AS DATE)
          ) AS governed_total__comparison
        FROM orbit.ops.event_fact AS e
        WHERE e.active = :active_flag
        LIMIT 100
    """

    rejected = validate_plan({"sql": swapped_sql}, package)

    assert rejected.violation == "TIME_RULE_MISMATCH"


def test_comparison_window_declared_but_unused_keeps_single_window_shape() -> None:
    package = _comparison_package()
    package = replace(
        package,
        parameter_bindings=tuple(
            item
            for item in package.parameter_bindings
            if item.name not in {"comparison_begin", "comparison_stop"}
        ),
    )

    accepted = validate_plan({"sql": _sql()}, package)

    assert accepted.ok, accepted


def test_exists_metric_and_comparison_window_together_are_rejected() -> None:
    package = _comparison_package()
    exists_metric = replace(
        package.metrics[0],
        id="governed_exists",
        field="active",
        aggregation="exists",
        result_field="governed_exists",
        unit="boolean",
        required_filters=(),
    )
    contracts = deepcopy(package.runtime_contracts)
    exists_rule = deepcopy(contracts["metric_rules"][0])
    exists_rule.update(
        id=exists_metric.id,
        source={
            "kind": "column",
            "field": {"asset_fqn": exists_metric.asset_fqn, "column": exists_metric.field},
        },
        aggregation="exists",
        result_field=exists_metric.result_field,
        unit=exists_metric.unit,
        required_filters=[],
    )
    contracts["metric_rules"].append(exists_rule)
    contracts["query_policy"]["allowed_functions"].append("COUNT")
    package = replace(
        package,
        metrics=(package.metrics[0], exists_metric),
        runtime_contracts=contracts,
    )
    sql = _COMPARISON_SQL.replace(
        "AS governed_total__comparison",
        "AS governed_total__comparison,\n      COUNT(e.active) > 0 AS governed_exists",
    )

    rejected = validate_plan({"sql": sql}, package)

    assert rejected.violation == "METRIC_RULE_MISMATCH"
    assert rejected.detail.endswith("exists")
