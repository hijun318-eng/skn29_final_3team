from __future__ import annotations

import numpy as np
import pandas as pd

from src.ml.room_demand_timeseries.operational_contracts import (
    OBSERVED_SIGNAL_SOURCE_KIND,
    OPERATIONAL_MODEL_VERSION,
)
from src.ml.room_demand_timeseries.operational_modeling import OperationalDemandModel
from src.ml.room_demand_timeseries.operational_self_evaluation import (
    OperationalSelfEvaluator,
)


class _BookingRatioPipeline:
    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return frame["booking_on_hand_ratio"].to_numpy(dtype=float)


def _split(start: str, days: int = 30) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for offset in range(days):
        cutoff = pd.Timestamp(start) + pd.Timedelta(offset, unit="D")
        cutoff_end = (
            cutoff.tz_localize("Asia/Seoul").tz_convert("UTC")
            + pd.Timedelta(1, unit="D")
        )
        for horizon in range(1, 8):
            target = 40.0 + offset % 5 + horizon
            rows.append(
                {
                    "property_id": "GRAND",
                    "room_type_code": "G_DELUXE",
                    "cutoff_date": cutoff,
                    "target_date": cutoff + pd.Timedelta(horizon, unit="D"),
                    "horizon_days": horizon,
                    "target_sellable_rooms": 100.0,
                    "target_rooms_sold": target,
                    "target_occupancy_rate": target / 100.0,
                    "target_same_weekday_mean_4w": target - 5.0,
                    "booking_on_hand": target - 1.0,
                    "booking_on_hand_ratio": (target - 1.0) / 100.0,
                    "reservation_as_of_at": cutoff_end - pd.Timedelta(3, unit="h"),
                    "capacity_as_of_at": cutoff_end - pd.Timedelta(2, unit="h"),
                    "event_as_of_at": cutoff_end - pd.Timedelta(1, unit="h"),
                    "signal_source_kind": OBSERVED_SIGNAL_SOURCE_KIND,
                    "signal_is_synthetic": False,
                }
            )
    return pd.DataFrame(rows)


def test_self_evaluation_covers_splits_groups_intervals_and_generalization() -> None:
    model = OperationalDemandModel(
        pipeline=_BookingRatioPipeline(),  # type: ignore[arg-type]
        model_version=OPERATIONAL_MODEL_VERSION,
        feature_columns=["booking_on_hand_ratio"],
        interval_quantiles={
            horizon: {"q80": 2.0, "q95": 3.0} for horizon in range(1, 8)
        },
    )
    datasets = {
        "TRAIN": _split("2023-01-01"),
        "VALIDATION": _split("2024-01-01"),
        "TEST_A": _split("2025-01-01"),
        "TEST_B": _split("2026-01-01"),
    }

    report = OperationalSelfEvaluator(
        bootstrap_samples=100,
        inference_repeats=2,
    ).evaluate(model, datasets, data_is_synthetic=False)

    assert report["technical_validation_passed"] is True
    assert report["production_eligible"] is True
    assert report["split_reports"]["TEST_B"]["metrics"]["mae"] == 1.0
    assert len(report["split_reports"]["TEST_B"]["group_metrics"]["horizon"]) == 7
    assert report["split_reports"]["TEST_B"]["prediction_intervals"]["95"][
        "empirical_coverage"
    ] == 1.0
    assert report["generalization"]["TEST_B"]["wape_absolute_gap"] == 0.0


def test_self_evaluation_never_marks_synthetic_data_production_eligible() -> None:
    model = OperationalDemandModel(
        pipeline=_BookingRatioPipeline(),  # type: ignore[arg-type]
        model_version=OPERATIONAL_MODEL_VERSION,
        feature_columns=["booking_on_hand_ratio"],
        interval_quantiles={
            horizon: {"q80": 2.0, "q95": 3.0} for horizon in range(1, 8)
        },
    )
    datasets = {
        "TRAIN": _split("2023-01-01"),
        "VALIDATION": _split("2024-01-01"),
        "TEST_A": _split("2025-01-01"),
        "TEST_B": _split("2026-01-01"),
    }

    report = OperationalSelfEvaluator(
        bootstrap_samples=100,
        inference_repeats=1,
    ).evaluate(model, datasets, data_is_synthetic=True)

    assert report["technical_validation_passed"] is True
    assert report["production_eligible"] is False
    assert report["limitations"]
