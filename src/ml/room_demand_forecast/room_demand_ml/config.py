from __future__ import annotations

from pathlib import Path


SEED = 20260803
LABEL = "rooms_sold"
KEY_COLUMNS = ["property_id", "target_date", "room_type_code", "horizon_days"]

CATEGORICAL_FEATURES = [
    "room_type_code",
    "target_season_code",
    "weather_scenario_code",
]

NUMERIC_FEATURES = [
    "horizon_days",
    "available_room_nights",
    "inventory_plan_known",
    "booking_on_hand",
    "cancelled_on_hand",
    "booking_on_hand_ratio",
    "rooms_sold_cutoff_lag_1",
    "rooms_sold_cutoff_lag_7",
    "rooms_sold_cutoff_lag_14",
    "rooms_sold_cutoff_rolling_mean_7",
    "rooms_sold_cutoff_rolling_mean_28",
    "adr_cutoff_lag_7",
    "cancellation_rate_cutoff_lag_28",
    "target_day_of_week",
    "target_month",
    "target_is_weekend",
    "target_is_month_start",
    "target_is_month_end",
    "target_is_public_holiday",
    "target_is_holiday_eve",
    "domestic_travel_index",
    "inbound_travel_index",
    "event_demand_index",
]

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
BOOLEAN_FEATURES = [
    "inventory_plan_known",
    "target_is_weekend",
    "target_is_month_start",
    "target_is_month_end",
    "target_is_public_holiday",
    "target_is_holiday_eve",
]
CRITICAL_RUNTIME_FEATURES = [
    "booking_on_hand",
    "booking_on_hand_ratio",
    "cancelled_on_hand",
]

FILE_NAMES = {
    "train": "room_demand_train.csv",
    "validation": "room_demand_validation.csv",
    "test": "room_demand_test.csv",
    "forecast": "room_demand_forecast_features.csv",
    "hidden_qa": "room_demand_hidden_label_qa.csv",
    "manifest": "generation_manifest.csv",
}

EXPECTED_SPLITS = {
    "train": ("TRAIN", "2022-01-01", "2024-12-31"),
    "validation": ("VALIDATION", "2025-01-01", "2025-12-31"),
    "test": ("TEST", "2026-01-01", "2026-07-28"),
    "forecast": ("FORECAST", "2026-07-29", "2026-12-31"),
}

PROJECT_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_DIR = PROJECT_DIR.parents[2]
DEFAULT_DATA_DIR = REPOSITORY_DIR / "data" / "raw" / "room_demand"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "artifacts"
DEFAULT_FORECAST_FIXTURE = PROJECT_DIR / "fixtures" / "room_demand_forecast_features.csv"
