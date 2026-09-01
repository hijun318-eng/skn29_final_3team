from __future__ import annotations

import numpy as np
import pandas as pd

from src.ml.room_demand_timeseries.operational_contracts import (
    OPERATIONAL_MODEL_VERSION,
)
from src.ml.room_demand_timeseries.build_operational_dataset import (
    build_development_dataset,
)
from src.ml.room_demand_timeseries.operational_evaluation import BASELINE_NAME
from src.ml.room_demand_timeseries.operational_modeling import OperationalDemandModel
from src.ml.room_demand_timeseries.operational_submission_evaluation import (
    OperationalSubmissionEvaluator,
    SubmissionSplitValidator,
)


class _BookingRatioPipeline:
    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return frame["booking_on_hand_ratio"].to_numpy(dtype=float)


def _frame(start: str, days: int = 14) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for offset in range(days):
        cutoff = pd.Timestamp(start) + pd.Timedelta(offset, unit="D")
        for horizon in range(1, 8):
            target = 40.0 + offset % 3 + horizon
            rows.append(
                {
                    "property_id": "GRAND",
                    "room_type_code": "G_DELUXE",
                    "cutoff_date": cutoff,
                    "target_date": cutoff + pd.Timedelta(horizon, unit="D"),
                    "horizon_days": horizon,
                    "target_sellable_rooms": 100.0,
                    "target_rooms_sold": target,
                    "target_same_weekday_mean_4w": target - 5.0,
                    "booking_on_hand": target - 1.0,
                    "booking_on_hand_ratio": (target - 1.0) / 100.0,
                }
            )
    return pd.DataFrame(rows)


def _model() -> OperationalDemandModel:
    return OperationalDemandModel(
        pipeline=_BookingRatioPipeline(),  # type: ignore[arg-type]
        model_version=OPERATIONAL_MODEL_VERSION,
        feature_columns=["booking_on_hand_ratio"],
        interval_quantiles={
            horizon: {"q80": 2.0, "q95": 3.0} for horizon in range(1, 8)
        },
    )


def test_submission_split_purges_labels_not_known_at_next_cutoff() -> None:
    raw = {
        "TRAIN": _frame("2026-01-01"),
        "VALIDATION": _frame("2026-01-15"),
        "TEST": _frame("2026-02-01"),
    }

    purged, receipt = SubmissionSplitValidator.purge_label_overlap(raw)
    contract = SubmissionSplitValidator.validate(purged)

    assert receipt["removed_rows"]["TRAIN"] == 49
    assert receipt["removed_rows"]["VALIDATION"] == 28
    assert contract["splits"]["TRAIN"]["target_end"] == "2026-01-14"
    assert contract["splits"]["VALIDATION"]["target_end"] == "2026-01-31"


def test_development_dataset_never_contains_test_rows() -> None:
    datasets = {
        "TRAIN": pd.DataFrame({"split": ["TRAIN"]}),
        "VALIDATION": pd.DataFrame({"split": ["VALIDATION"]}),
        "TEST": pd.DataFrame({"split": ["TEST"]}),
    }

    development = build_development_dataset(datasets)

    assert development["split"].tolist() == ["TRAIN", "VALIDATION"]


def test_submission_evaluation_records_every_required_objective_metric() -> None:
    datasets = {
        "TRAIN": _frame("2026-01-01", days=7),
        "VALIDATION": _frame("2026-02-01", days=7),
        "TEST": _frame("2026-03-01", days=7),
    }
    report, predictions = OperationalSubmissionEvaluator(
        bootstrap_samples=100,
        inference_requests=100,
        inference_warmups=2,
    ).evaluate(
        _model(),
        _model(),
        datasets,
        learning_curve=[{"training_fraction": 1.0, "training_rows": 49}],
        data_is_synthetic=True,
        purge_report={"method": "unit-test", "removed_rows": {}},
    )

    test = report["split_reports"]["TEST"]
    assert report["baseline"]["name"] == BASELINE_NAME
    assert len(test["group_metrics"]["horizon"]) == 7
    assert len(test["group_metrics"]["room_type"]) == 1
    assert test["paired_target_date_bootstrap"]["date_column"] == "target_date"
    assert test["paired_target_date_bootstrap"]["ci95"]
    assert test["residual_diagnostics"]["residual_quantiles_rooms"]["p95"] == -1.0
    assert test["metrics"]["absolute_error_p95"] == 1.0
    assert test["inference_benchmark"]["measurements"] == 100
    assert test["inference_benchmark"]["p99_ms"] >= 0.0
    assert report["actual_pms_evaluation"]["status"] == "NOT_AVAILABLE"
    assert report["production_eligible"] is False
    assert len(predictions["TEST"]) == 49
