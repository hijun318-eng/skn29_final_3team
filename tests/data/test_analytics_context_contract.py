import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads(
    (ROOT / "src/data/analytics_context_contract.i4.v2.json").read_text(encoding="utf-8")
)
VIEW_CONTRACT = json.loads(
    (ROOT / CONTRACT["view_contract"]).read_text(encoding="utf-8")
)


def _asset_columns():
    return {
        **{view["fqn"]: set(view["columns"]) for view in VIEW_CONTRACT["views"]},
        **{asset["fqn"]: set(asset["columns"]) for asset in CONTRACT["raw_assets"]},
    }


def test_raw_allowlist_is_exact_and_bounded():
    assets = {asset["fqn"]: asset for asset in CONTRACT["raw_assets"]}
    assert set(assets) == {
        "crm.dbo.crm_members",
        "crm.dbo.crm_member_grade_history",
        "crm.dbo.crm_point_transactions",
        "crm.dbo.crm_customer_map",
        "pms.public.pms_stays",
        "pms.public.pms_reservations",
        "pms.public.pms_guests",
    }
    assert all(asset["columns"] for asset in assets.values())
    assert sum(len(asset["columns"]) for asset in assets.values()) <= 60
    assert all(
        ("crm.crm_db.dbo." in asset["urn"] if fqn.startswith("crm.") else "pms.pms_db.public." in asset["urn"])
        for fqn, asset in assets.items()
    )


def test_only_crm_and_approved_join_can_use_raw_assets():
    allowed_uses = {"crm_only", "approved_pms_crm_join"}
    assert set(CONTRACT["selection_policy"]["raw_allowed_for"]) == allowed_uses
    assert all(set(asset["uses"]) <= allowed_uses for asset in CONTRACT["raw_assets"])
    assert CONTRACT["selection_policy"]["default"] == "serving_views"


def test_pms_crm_join_matches_frozen_source_registry():
    source_registry = json.loads(
        (ROOT / "src/data/source_registry.v1.json").read_text(encoding="utf-8")
    )
    expected = next(
        join
        for join in source_registry["approved_joins"]
        if join["join_id"] == "pms_stay_to_crm_membership_grade_event_time_v1"
    )
    actual = CONTRACT["approved_joins"]
    assert len(actual) == 1
    assert actual[0]["id"] == expected["join_id"]
    assert actual[0]["cardinality"] == expected["cardinality"]
    assert actual[0]["event_time_field"] == expected["event_time_field"]
    assert len(actual[0]["assets"]) == 5


def test_metric_registry_is_versioned_and_references_approved_columns():
    assert CONTRACT["contract_version"] == "I4-CONTEXT-v2.2.0-DRAFT"
    assert CONTRACT["metric_registry_version"] == "I4-METRIC-v1.1.0-DRAFT"
    metrics = CONTRACT["metrics"]
    assert len({metric["id"] for metric in metrics}) == len(metrics)

    asset_columns = _asset_columns()
    for metric in metrics:
        columns = asset_columns[metric["asset_fqn"]]
        assert metric["field"] in columns
        assert metric["time_field"] in columns
        for required_filter in metric.get("required_filters", []):
            assert set(required_filter) == {"field", "operator", "value"}
            assert required_filter["field"] in columns
            assert required_filter["operator"] == "eq"
            assert isinstance(required_filter["value"], (str, bool))


def test_metric_registry_adds_only_the_three_approved_single_asset_metrics():
    metrics = {metric["id"]: metric for metric in CONTRACT["metrics"]}
    assert set(metrics) == {
        "recognized_room_revenue",
        "expired_points",
        "fnb_net_revenue",
        "facility_revenue",
        "actual_attendees",
    }
    assert len({metric["asset_fqn"] for metric in metrics.values()}) == len(metrics)

    expected = {
        "fnb_net_revenue": (
            "serving.analytics.fnb_daypart_metrics",
            "fnb_net_revenue",
            "business_date",
        ),
        "facility_revenue": (
            "serving.analytics.facility_daily_metrics",
            "facility_revenue",
            "business_date",
        ),
        "actual_attendees": (
            "serving.analytics.banquet_monthly_metrics",
            "actual_attendees",
            "year_month",
        ),
    }
    for metric_id, (asset_fqn, field, time_field) in expected.items():
        metric = metrics[metric_id]
        assert metric["asset_fqn"] == asset_fqn
        assert metric["field"] == field
        assert metric["aggregation"] == "sum"
        assert metric["time_field"] == time_field


def test_expired_points_preserves_transaction_and_forecast_filters():
    metric = next(metric for metric in CONTRACT["metrics"] if metric["id"] == "expired_points")
    assert metric == {
        "id": "expired_points",
        "asset_fqn": "crm.dbo.crm_point_transactions",
        "field": "points_delta",
        "aggregation": "negative_sum",
        "time_field": "event_at",
        "required_filters": [
            {"field": "txn_type", "operator": "eq", "value": "EXPIRE"},
            {"field": "is_forecast", "operator": "eq", "value": False},
        ],
    }


def test_view_metrics_preserve_actual_non_forecast_filters_without_sql_predicates():
    view_fqns = {view["fqn"] for view in VIEW_CONTRACT["views"]}
    view_metrics = [metric for metric in CONTRACT["metrics"] if metric["asset_fqn"] in view_fqns]
    assert view_metrics
    expected = [
        {"field": "data_period_status", "operator": "eq", "value": "ACTUAL"},
        {"field": "is_forecast", "operator": "eq", "value": False},
    ]
    assert all(metric["required_filters"] == expected for metric in view_metrics)
    assert "predicate" not in json.dumps(CONTRACT).lower()
