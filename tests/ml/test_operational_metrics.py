from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml.room_demand_timeseries.operational_metrics import DemandMetricSuite
from src.ml.room_demand_timeseries.operational_statistical_validation import (
    PairedBaselineValidator,
)


def test_point_metrics_keep_undefined_wape_and_r2_out_of_json_nan() -> None:
    metrics = DemandMetricSuite.point_metrics([0.0, 0.0], [1.0, 0.0])

    assert metrics["mae"] == 0.5
    assert metrics["rmse"] == pytest.approx(np.sqrt(0.5))
    assert metrics["wape"] is None
    assert metrics["r2"] is None
    assert metrics["bias"] is None


def test_comparison_reports_primary_metric_improvement_and_mase() -> None:
    comparison = DemandMetricSuite.compare(
        [10.0, 20.0, 30.0],
        [11.0, 19.0, 31.0],
        [14.0, 16.0, 34.0],
    )

    assert comparison["better_on_all_primary_metrics"] is True
    assert comparison["relative_improvement"]["mae"] == pytest.approx(0.75)
    assert comparison["candidate_metrics"]["mase"] == pytest.approx(0.25)


def test_interval_and_latency_metrics_reject_invalid_operational_evidence() -> None:
    interval = DemandMetricSuite.interval_metrics(
        [10.0, 20.0],
        [9.0, 18.0],
        [11.0, 22.0],
        nominal_coverage=0.80,
        capacity=[100.0, 100.0],
    )

    assert interval["empirical_coverage"] == 1.0
    assert interval["normalized_mean_width"] == pytest.approx(0.03)
    with pytest.raises(ValueError, match="lower bound exceeds"):
        DemandMetricSuite.interval_metrics(
            [10.0], [11.0], [9.0], nominal_coverage=0.80
        )
    with pytest.raises(ValueError, match="must not be negative"):
        DemandMetricSuite.latency_metrics([1.0, -1.0])


def test_paired_moving_block_bootstrap_is_positive_and_reproducible() -> None:
    frame = pd.DataFrame(
        {
            "cutoff_date": pd.date_range("2026-01-01", periods=28, freq="D"),
            "target_rooms_sold": np.linspace(20.0, 47.0, 28),
        }
    )
    actual = frame["target_rooms_sold"].to_numpy()
    validator = PairedBaselineValidator(samples=100, random_seed=7)
    first = validator.validate(frame, actual + 1.0, actual + 4.0)
    second = validator.validate(frame, actual + 1.0, actual + 4.0)

    assert first == second
    assert first["statistically_better"] is True
    assert first["candidate_win_rate_by_cutoff"] == 1.0
    assert first["ci95"]["mae_improvement_rooms"][0] > 0.0
