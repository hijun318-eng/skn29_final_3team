from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from app.services.analysis.logical_plan import (
    AnalysisPlanError,
    build_analysis_plan,
)
from app.services.analysis.typed_sql_compiler import compile_typed_sql
from app.services.context.builder import (
    ContextAsset,
    ContextBuildError,
    ContextMetric,
    ContextRequiredFilter,
)
from app.services.context.contract import GovernedJoin
from app.services.context.query_planner import RAW_APPROVED_DETAIL
from app.services.context.runtime_contracts import time_selection_mode
from app.services.sql_guard import validate_plan
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V2
from tests.backend.test_pipeline_sql_guard import _joined_package


FACT = "orbit.ops.event_fact"
DIMENSION = "orbit.ops.customer_dim"


def _dimension_join_package(*, preaggregation: bool):
    package = _joined_package(preaggregation=preaggregation)
    contracts = deepcopy(package.runtime_contracts)
    contracts["metric_rules"][0]["dimensions"] = [
        {"asset_fqn": DIMENSION, "column": "segment"}
    ]
    return replace(package, runtime_contracts=contracts)


@pytest.mark.parametrize(
    ("preaggregation", "expected_plan"),
    ((False, "DIRECT_JOIN"), (True, "PREAGGREGATE")),
)
def test_typed_join_compiler_matches_the_server_fanout_plan(
    preaggregation: bool,
    expected_plan: str,
) -> None:
    package = _dimension_join_package(preaggregation=preaggregation)
    plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_amount",
            "analysis_operation": "breakdown",
            "period_relationship": "single",
            "dimension_fields": [
                {"asset_fqn": DIMENSION, "column": "segment"}
            ],
        },
        package,
    )

    assert [item.plan for item in plan.joins] == [expected_plan]
    candidate = compile_typed_sql(plan, package)
    assert candidate is not None
    candidate["analysis_plan"] = plan.as_dict()

    accepted = validate_plan(candidate, package)

    assert accepted.ok, accepted
    assert accepted.ast_evidence is not None
    assert accepted.ast_evidence["fanout_plans"][0]["plan"] == expected_plan
    if preaggregation:
        assert "many_preaggregated" in str(candidate["sql"])


def _semi_join_package():
    package = _joined_package()
    edge = package.join_graph[0]
    metric = ContextMetric(
        id="governed_budget",
        asset_fqn=DIMENSION,
        field="budget",
        aggregation="sum",
        time_field="occurred_on",
        required_filters=(),
        result_field="governed_budget_total",
        unit="credits",
        governance_version=RUNTIME_GOVERNANCE_VERSION_V2,
        allowed_roles=("analyst",),
        contains_pii=False,
        allowed_join_ids=(edge.id,),
        join_required=True,
        query_strategies=(RAW_APPROVED_DETAIL,),
    )
    fact, dimension = package.assets
    fact = replace(
        fact,
        metrics=(),
        required_filters=(ContextRequiredFilter("active", "eq", True),),
    )
    dimension = replace(
        dimension,
        columns=(*dimension.columns, "budget", "occurred_on"),
        column_types=(
            *dimension.column_types,
            ("budget", "double"),
            ("occurred_on", "date"),
        ),
        metrics=(metric,),
    )
    contracts = deepcopy(package.runtime_contracts)
    contracts["schema_context"]["assets"][1]["columns"].extend(
        [
            {
                "name": "budget",
                "native_type": "double",
                "nullable": False,
                "role": "measure",
            },
            {
                "name": "occurred_on",
                "native_type": "date",
                "nullable": False,
                "role": "time",
            },
        ]
    )
    contracts["metric_rules"] = [
        {
            "id": metric.id,
            "source": {
                "kind": "column",
                "field": {"asset_fqn": DIMENSION, "column": "budget"},
            },
            "aggregation": "sum",
            "result_field": metric.result_field,
            "unit": metric.unit,
            "time_field": {
                "asset_fqn": DIMENSION,
                "column": "occurred_on",
            },
            "dimensions": [],
            "required_filters": [],
        }
    ]
    contracts["filter_rules"] = [
        {
            "field": {"asset_fqn": FACT, "column": "active"},
            "operator": "eq",
            "parameter": "active_flag",
        }
    ]
    contracts["time_rules"]["fields"] = [
        {
            "field": {"asset_fqn": DIMENSION, "column": "occurred_on"},
            "native_type": "date",
            "bucket": "day",
            "timezone_mode": "preserve",
        }
    ]
    return replace(
        package,
        assets=(fact, dimension),
        metrics=(metric,),
        required_filters=(ContextRequiredFilter("active", "eq", True),),
        runtime_contracts=contracts,
        query_strategy=RAW_APPROVED_DETAIL,
    )


def test_filter_only_many_side_compiles_to_a_guarded_correlated_exists() -> None:
    package = _semi_join_package()
    plan = build_analysis_plan(
        {
            "selected_metric_id": "governed_budget",
            "analysis_operation": "aggregate",
            "period_relationship": "single",
            "filter_fields": [
                {
                    "asset_fqn": FACT,
                    "column": "active",
                    "operator": "eq",
                    "value_text": "true",
                }
            ],
        },
        package,
    )

    assert [item.plan for item in plan.joins] == ["SEMI_JOIN"]
    candidate = compile_typed_sql(plan, package)
    assert candidate is not None
    assert "EXISTS" in str(candidate["sql"])
    candidate["analysis_plan"] = plan.as_dict()

    accepted = validate_plan(candidate, package)

    assert accepted.ok, accepted
    assert accepted.ast_evidence is not None
    assert accepted.ast_evidence["join_count"] == 0
    assert accepted.ast_evidence["fanout_plans"][0]["plan"] == "SEMI_JOIN"


def test_filter_only_many_side_without_a_bound_filter_fails_closed() -> None:
    package = _semi_join_package()

    with pytest.raises(AnalysisPlanError, match="파라미터"):
        build_analysis_plan(
            {
                "selected_metric_id": "governed_budget",
                "analysis_operation": "aggregate",
                "period_relationship": "single",
                "filter_fields": [
                    {
                        "asset_fqn": FACT,
                        "column": "active",
                        "operator": "neq",
                        "value_text": "false",
                    }
                ],
            },
            package,
        )


def test_optional_join_permission_does_not_force_a_single_asset_query() -> None:
    package = _dimension_join_package(preaggregation=False)
    metric = replace(package.metrics[0], join_required=False)
    fact, dimension = package.assets
    package = replace(
        package,
        assets=(replace(fact, metrics=(metric,)), dimension),
        metrics=(metric,),
    )

    single_asset = build_analysis_plan(
        {
            "selected_metric_id": metric.id,
            "analysis_operation": "aggregate",
            "period_relationship": "single",
        },
        package,
    )
    joined = build_analysis_plan(
        {
            "selected_metric_id": metric.id,
            "analysis_operation": "breakdown",
            "period_relationship": "single",
            "dimension_fields": [
                {"asset_fqn": DIMENSION, "column": "segment"}
            ],
        },
        package,
    )

    assert single_asset.joins == ()
    assert [item.plan for item in joined.joins] == ["DIRECT_JOIN"]


def test_equal_length_join_paths_fail_closed_instead_of_picking_an_edge_order() -> None:
    package = _dimension_join_package(preaggregation=False)
    fact, dimension = package.assets
    middle_assets = tuple(
        ContextAsset(
            urn=f"urn:test:orbit.ops.customer_bridge_{suffix}",
            fqn=f"orbit.ops.customer_bridge_{suffix}",
            columns=("customer_id",),
            column_types=(("customer_id", "varchar"),),
            metric_registry_required=True,
        )
        for suffix in ("a", "b")
    )
    edges = tuple(
        GovernedJoin(
            id=edge_id,
            left=left,
            right=right,
            kind="inner",
            cardinality="many_to_one",
            equality_conditions=((f"{left}.customer_id", f"{right}.customer_id"),),
            temporal_conditions=(),
            preaggregation_required=False,
            preaggregation_grain=(),
            preaggregation_keys=(),
        )
        for edge_id, left, right in (
            ("path_a_left", FACT, middle_assets[0].fqn),
            ("path_a_right", middle_assets[0].fqn, DIMENSION),
            ("path_b_left", FACT, middle_assets[1].fqn),
            ("path_b_right", middle_assets[1].fqn, DIMENSION),
        )
    )
    metric = replace(
        package.metrics[0],
        allowed_join_ids=tuple(edge.id for edge in edges),
    )
    contracts = deepcopy(package.runtime_contracts)
    contracts["schema_context"]["assets"].extend(
        {
            "urn": asset.urn,
            "fqn": asset.fqn,
            "grain": {"kind": "row", "keys": ["customer_id"]},
            "columns": [
                {
                    "name": "customer_id",
                    "native_type": "varchar",
                    "nullable": False,
                    "role": "identifier",
                }
            ],
        }
        for asset in middle_assets
    )
    contracts["join_graph"] = {"edges": [edge.as_dict() for edge in edges]}
    package = replace(
        package,
        assets=(replace(fact, metrics=(metric,)), dimension, *middle_assets),
        metrics=(metric,),
        join_graph=edges,
        runtime_contracts=contracts,
    )

    with pytest.raises(AnalysisPlanError, match="복수 최단 JOIN 경로"):
        build_analysis_plan(
            {
                "selected_metric_id": metric.id,
                "analysis_operation": "breakdown",
                "period_relationship": "single",
                "dimension_fields": [
                    {"asset_fqn": DIMENSION, "column": "segment"}
                ],
            },
            package,
        )


def _count_distinct_preaggregation_package(*, field: str):
    package = _dimension_join_package(preaggregation=True)
    metric = replace(
        package.metrics[0],
        field=field,
        aggregation="count_distinct",
        result_field="governed_distinct_total",
    )
    fact, dimension = package.assets
    contracts = deepcopy(package.runtime_contracts)
    contracts["schema_context"]["assets"][0]["grain"] = {
        "kind": "row",
        "keys": ["customer_id"],
    }
    contracts["metric_rules"][0].update(
        source={
            "kind": "column",
            "field": {"asset_fqn": FACT, "column": field},
        },
        aggregation="count_distinct",
        result_field=metric.result_field,
    )
    contracts["query_policy"]["allowed_functions"].append("COUNT")
    return replace(
        package,
        assets=(replace(fact, metrics=(metric,)), dimension),
        metrics=(metric,),
        runtime_contracts=contracts,
    )


def test_count_distinct_preaggregation_rollup_requires_a_single_release_key() -> None:
    safe_package = _count_distinct_preaggregation_package(field="customer_id")
    unsafe_package = _count_distinct_preaggregation_package(field="active")

    def decision(package):
        plan = build_analysis_plan(
            {
                "selected_metric_id": package.metrics[0].id,
                "analysis_operation": "breakdown",
                "period_relationship": "single",
                "dimension_fields": [
                    {"asset_fqn": DIMENSION, "column": "segment"}
                ],
            },
            package,
        )
        candidate = compile_typed_sql(plan, package)
        assert candidate is not None
        candidate["analysis_plan"] = plan.as_dict()
        return validate_plan(candidate, package)

    accepted = decision(safe_package)
    rejected = decision(unsafe_package)

    assert accepted.ok, accepted
    assert rejected.violation == "METRIC_RULE_MISMATCH"


def test_multi_asset_mixed_time_modes_fail_before_sql_compilation() -> None:
    range_metadata = {
        "mode": "range",
        "calendar_id": "gregorian-kr",
        "start_parameter": "start_date",
        "end_parameter": "end_date",
        "fields": [],
    }
    snapshot_metadata = {
        "mode": "latest_snapshot",
        "calendar_id": "gregorian-kr",
        "selection": "max_source_value_lt_as_of",
        "as_of_parameter": "as_of_date",
        "fields": [],
    }

    with pytest.raises(ContextBuildError, match="동일한 time_metadata"):
        time_selection_mode(
            [
                {"time_metadata": range_metadata},
                {"time_metadata": snapshot_metadata},
            ]
        )
