"""Query Planner가 하드코딩 없이 asset 카탈로그와 grain만으로 3경로를 결정하는지 검증."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.context.builder import ContextMetric, ContextPackage
from app.services.context.query_planner import (
    RAW_APPROVED_DETAIL,
    VIEW_COMPOSE,
    VIEW_REUSE,
    determine_query_strategy,
)


def _package(metrics: tuple[ContextMetric, ...]) -> ContextPackage:
    return ContextPackage(
        context_release="context-runtime-1",
        policy_version="policy-runtime-1",
        time_version="calendar-runtime-1",
        entitlement_hash="entitled-user",
        assets=(),
        dataset_count=0,
        column_count=0,
        token_count=0,
        token_limit=1000,
        package_hash="hash",
        approved_join_ids=(),
        metrics=metrics,
    )


def test_single_served_view_is_view_reuse() -> None:
    metrics = (
        ContextMetric(
            id="occupancy_rate",
            asset_fqn="serving.analytics_v4_3.room_monthly_kpi",
            field="occupancy_rate",
            aggregation="average",
            time_field="month_start",
            required_filters=(),
        ),
    )
    contracts = {
        "schema_context": {
            "assets": [
                {
                    "fqn": "serving.analytics_v4_3.room_monthly_kpi",
                    "grain": {"kind": "periodic", "keys": ["month_start", "hotel_code"]},
                }
            ]
        }
    }
    assert determine_query_strategy(_package(metrics), contracts) == VIEW_REUSE


def test_single_served_row_grain_uses_approved_detail_path() -> None:
    metrics = (
        ContextMetric(
            id="average_value",
            asset_fqn="serving.sample.observation_detail",
            field="observed_value",
            aggregation="average",
            time_field="observed_on",
            required_filters=(),
        ),
    )
    contracts = {
        "schema_context": {
            "assets": [
                {
                    "fqn": "serving.sample.observation_detail",
                    "grain": {"kind": "row", "keys": ["observation_id"]},
                }
            ]
        }
    }

    assert determine_query_strategy(_package(metrics), contracts) == RAW_APPROVED_DETAIL


def test_missing_grain_metadata_fails_closed_to_detail_path() -> None:
    metrics = (
        ContextMetric(
            id="total_value",
            asset_fqn="serving.sample.daily_values",
            field="value",
            aggregation="sum",
            time_field="observed_on",
            required_filters=(),
        ),
    )

    assert (
        determine_query_strategy(
            _package(metrics),
            {"schema_context": {"assets": []}},
        )
        == RAW_APPROVED_DETAIL
    )


def test_two_served_views_same_grain_is_view_compose() -> None:
    metrics = (
        ContextMetric(
            id="occupancy_rate",
            asset_fqn="serving.analytics_v4_3.room_daily",
            field="occupancy_rate",
            aggregation="average",
            time_field="business_date",
            required_filters=(),
        ),
        ContextMetric(
            id="fnb_revenue",
            asset_fqn="serving.analytics_v4_3.fnb_daily",
            field="net_revenue_krw",
            aggregation="sum",
            time_field="business_date",
            required_filters=(),
        ),
    )
    contracts = {
        "schema_context": {
            "assets": [
                {
                    "fqn": "serving.analytics_v4_3.room_daily",
                    "grain": {"kind": "periodic", "keys": ["business_date", "hotel_code"]},
                },
                {
                    "fqn": "serving.analytics_v4_3.fnb_daily",
                    "grain": {"kind": "periodic", "keys": ["hotel_code", "business_date"]},
                },
            ]
        }
    }
    assert determine_query_strategy(_package(metrics), contracts) == VIEW_COMPOSE


def test_two_served_views_different_grain_falls_back_to_raw() -> None:
    metrics = (
        ContextMetric(
            id="occupancy_rate",
            asset_fqn="serving.analytics_v4_3.room_daily",
            field="occupancy_rate",
            aggregation="average",
            time_field="business_date",
            required_filters=(),
        ),
        ContextMetric(
            id="voc_rating",
            asset_fqn="serving.analytics_v4_3.voc_review_detail",
            field="rating",
            aggregation="average",
            time_field="review_date",
            required_filters=(),
        ),
    )
    contracts = {
        "schema_context": {
            "assets": [
                {
                    "fqn": "serving.analytics_v4_3.room_daily",
                    "grain": {"kind": "periodic", "keys": ["business_date", "hotel_code"]},
                },
                {
                    "fqn": "serving.analytics_v4_3.voc_review_detail",
                    "grain": {"kind": "row", "keys": ["review_id"]},
                },
            ]
        }
    }
    assert determine_query_strategy(_package(metrics), contracts) == RAW_APPROVED_DETAIL


def test_non_served_source_asset_is_raw_approved_detail() -> None:
    metrics = (
        ContextMetric(
            id="stayed_gold_members",
            asset_fqn="pms.walkerhill_v4_3.guest_reservations",
            field="room_revenue_krw",
            aggregation="sum",
            time_field="checkout_at",
            required_filters=(),
        ),
    )
    contracts = {
        "schema_context": {
            "assets": [
                {
                    "fqn": "pms.walkerhill_v4_3.guest_reservations",
                    "grain": {"kind": "row", "keys": ["reservation_id"]},
                }
            ]
        }
    }
    assert determine_query_strategy(_package(metrics), contracts) == RAW_APPROVED_DETAIL


def test_ratio_metric_resolves_strategy_from_referenced_base_metrics() -> None:
    metrics = (
        ContextMetric(
            id="occupied_room_nights",
            asset_fqn="serving.analytics_v4_3.room_daily",
            field="occupied_room_nights",
            aggregation="sum",
            time_field="business_date",
            required_filters=(),
        ),
        ContextMetric(
            id="available_room_nights",
            asset_fqn="serving.analytics_v4_3.room_daily",
            field="available_room_nights",
            aggregation="sum",
            time_field="business_date",
            required_filters=(),
        ),
        ContextMetric(
            id="occupancy_rate_ratio",
            asset_fqn="",
            field="",
            aggregation="ratio",
            time_field="",
            required_filters=(),
            numerator_metric_id="occupied_room_nights",
            denominator_metric_id="available_room_nights",
            zero_policy="null_on_zero_denominator",
        ),
    )
    contracts = {
        "schema_context": {
            "assets": [
                {
                    "fqn": "serving.analytics_v4_3.room_daily",
                    "grain": {"kind": "periodic", "keys": ["business_date", "hotel_code"]},
                }
            ]
        }
    }
    assert determine_query_strategy(_package(metrics), contracts) == VIEW_REUSE


def test_no_metrics_fails_closed() -> None:
    with pytest.raises(ValueError):
        determine_query_strategy(_package(()), {"schema_context": {"assets": []}})
