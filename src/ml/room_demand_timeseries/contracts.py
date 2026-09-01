from __future__ import annotations

from dataclasses import dataclass


MODEL_VERSION = "room-demand-timeseries-hgbr-v2.6.0"
MAX_HORIZON = 10

CATEGORICAL_FEATURES = [
    "property_id",
    "room_type_code",
]

NUMERIC_FEATURES = [
    "horizon_days",
    "physical_rooms",
    "cutoff_rooms_sold",
    "cutoff_available_room_nights",
    "cutoff_available_ratio",
    "cutoff_occupancy_rate",
    "rooms_sold_lag_1",
    "rooms_sold_lag_7",
    "rooms_sold_lag_14",
    "rooms_sold_lag_21",
    "rooms_sold_lag_28",
    "rooms_sold_lag_364",
    "rooms_sold_lag_365",
    "rooms_sold_lag_371",
    "rolling_mean_7",
    "rolling_mean_14",
    "rolling_mean_28",
    "rolling_mean_56",
    "rolling_std_28",
    "same_weekday_mean_4w",
    "same_weekday_mean_8w",
    "same_weekday_mean_12w",
    "annual_same_weekday_mean",
    "trend_7_28",
    "cutoff_adr",
    "adr_lag_7",
    "cutoff_cancellation_rate",
    "cancellation_rate_mean_28",
    "target_day_of_week",
    "target_month",
    "target_week_of_year",
    "target_day_of_year",
    "target_year",
    "target_is_weekend",
    "target_is_public_holiday",
    "target_is_holiday_eve",
    "target_is_month_start",
    "target_is_month_end",
    "target_dow_sin",
    "target_dow_cos",
    "target_year_sin",
    "target_year_cos",
]

FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES
IDENTITY_COLUMNS = [
    "property_id",
    "room_type_code",
    "cutoff_date",
    "target_date",
    "horizon_days",
]
LABEL_COLUMNS = ["target_rooms_sold", "target_occupancy_rate"]


@dataclass(frozen=True)
class SplitWindow:
    name: str
    cutoff_start: str
    cutoff_end: str


SPLIT_WINDOWS = (
    SplitWindow("TRAIN", "2018-01-01", "2023-12-21"),
    SplitWindow("VALIDATION", "2024-01-01", "2024-12-21"),
    SplitWindow("TEST_A", "2025-01-01", "2025-12-21"),
    SplitWindow("TEST_B", "2026-01-01", "2026-08-21"),
)
