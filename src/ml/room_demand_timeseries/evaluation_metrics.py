from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from .modeling import TimeSeriesDemandModel

BASELINE_COLUMNS = {
    "last_observation": "cutoff_rooms_sold",
    "seasonal_same_weekday_4w": "same_weekday_mean_4w",
    "seasonal_same_weekday_12w": "same_weekday_mean_12w",
}

def metric_record(
    actual: np.ndarray,
    prediction: np.ndarray,
    baseline: np.ndarray,
) -> dict[str, float | int]:
    actual = np.asarray(actual, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    baseline = np.asarray(baseline, dtype=float)
    absolute_error = np.abs(actual - prediction)
    denominator = float(np.abs(actual).sum())
    baseline_mae = float(np.abs(actual - baseline).mean())
    quantiles = np.quantile(absolute_error, [0.50, 0.75, 0.90, 0.95, 0.99])
    return {
        "rows": int(len(actual)),
        "actual_total": float(actual.sum()),
        "actual_mean": float(actual.mean()),
        "wape": float(absolute_error.sum() / denominator) if denominator else 0.0,
        "mae": float(mean_absolute_error(actual, prediction)),
        "rmse": float(mean_squared_error(actual, prediction) ** 0.5),
        "bias": float((prediction - actual).sum() / denominator) if denominator else 0.0,
        "mase": float(absolute_error.mean() / baseline_mae) if baseline_mae else 0.0,
        "r2": float(r2_score(actual, prediction)),
        "absolute_error_p50": float(quantiles[0]),
        "absolute_error_p75": float(quantiles[1]),
        "absolute_error_p90": float(quantiles[2]),
        "absolute_error_p95": float(quantiles[3]),
        "absolute_error_p99": float(quantiles[4]),
        "absolute_error_max": float(absolute_error.max()),
        "within_1_room_rate": float((absolute_error <= 1.0).mean()),
        "within_3_rooms_rate": float((absolute_error <= 3.0).mean()),
        "within_5_rooms_rate": float((absolute_error <= 5.0).mean()),
    }


def _baseline_predictions(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    capacity = frame["physical_rooms"].astype(float).to_numpy()
    return {
        name: np.clip(frame[column].astype(float).to_numpy(), 0.0, capacity)
        for name, column in BASELINE_COLUMNS.items()
    }


def _bootstrap_improvement(
    frame: pd.DataFrame,
    actual: np.ndarray,
    prediction: np.ndarray,
    baseline: np.ndarray,
    samples: int,
) -> dict[str, Any]:
    daily = pd.DataFrame(
        {
            "target_date": pd.to_datetime(frame["target_date"]),
            "actual_abs": np.abs(actual),
            "model_abs_error": np.abs(actual - prediction),
            "baseline_abs_error": np.abs(actual - baseline),
        }
    ).groupby("target_date", sort=True).agg(
        actual_abs=("actual_abs", "sum"),
        model_abs_error=("model_abs_error", "sum"),
        baseline_abs_error=("baseline_abs_error", "sum"),
        rows=("actual_abs", "size"),
    )
    block_days = min(7, len(daily))
    block_count = int(np.ceil(len(daily) / block_days))
    rng = np.random.default_rng(20260826)
    relative_wape: list[float] = []
    mae_delta: list[float] = []
    values = daily.to_numpy(dtype=float)
    max_start = len(values) - block_days + 1
    for _ in range(samples):
        starts = rng.integers(0, max_start, size=block_count)
        indices = np.concatenate(
            [np.arange(start, start + block_days) for start in starts]
        )[: len(values)]
        sample = values[indices].sum(axis=0)
        _, model_error, baseline_error, rows = sample
        relative_wape.append(1.0 - model_error / baseline_error)
        mae_delta.append((baseline_error - model_error) / rows)
    wape_ci = np.quantile(relative_wape, [0.025, 0.975])
    mae_ci = np.quantile(mae_delta, [0.025, 0.975])
    return {
        "method": "moving_block_bootstrap_by_target_date",
        "samples": samples,
        "block_days": block_days,
        "wape_relative_improvement_ci95": [float(wape_ci[0]), float(wape_ci[1])],
        "mae_improvement_rooms_ci95": [float(mae_ci[0]), float(mae_ci[1])],
        "statistically_uncertain": bool(wape_ci[0] <= 0.0 or mae_ci[0] <= 0.0),
    }


def evaluate_model(
    model: TimeSeriesDemandModel,
    frame: pd.DataFrame,
    bootstrap_samples: int = 0,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    actual = frame["target_rooms_sold"].astype(float).to_numpy()
    baselines = _baseline_predictions(frame)
    baseline_metrics = {
        name: metric_record(actual, values, values)
        for name, values in baselines.items()
    }
    best_baseline_name = min(
        baseline_metrics, key=lambda name: baseline_metrics[name]["wape"]
    )
    baseline = baselines[best_baseline_name]
    raw = model.predict_raw(frame)
    prediction = model.predict(frame)
    overall = metric_record(actual, prediction, baseline)
    best_baseline_metrics = baseline_metrics[best_baseline_name]
    groups: dict[str, pd.DataFrame] = {}
    for name, columns in {
        "horizon": ["horizon_days"],
        "property": ["property_id"],
        "room_type": ["property_id", "room_type_code"],
        "month": ["target_month"],
        "weekend": ["target_is_weekend"],
        "holiday": ["target_is_public_holiday"],
    }.items():
        records: list[dict[str, Any]] = []
        for keys, subset in frame.assign(
            prediction=prediction,
            baseline_prediction=baseline,
        ).groupby(columns, sort=True):
            key_values = keys if isinstance(keys, tuple) else (keys,)
            record = dict(zip(columns, key_values))
            model_metrics = metric_record(
                subset["target_rooms_sold"].to_numpy(),
                subset["prediction"].to_numpy(),
                subset["baseline_prediction"].to_numpy(),
            )
            grouped_baseline = metric_record(
                subset["target_rooms_sold"].to_numpy(),
                subset["baseline_prediction"].to_numpy(),
                subset["baseline_prediction"].to_numpy(),
            )
            record.update(model_metrics)
            record.update(
                {
                    "baseline_wape": grouped_baseline["wape"],
                    "baseline_mae": grouped_baseline["mae"],
                    "baseline_rmse": grouped_baseline["rmse"],
                    "baseline_wape_improvement": (
                        1.0 - model_metrics["wape"] / grouped_baseline["wape"]
                    ),
                }
            )
            records.append(record)
        groups[name] = pd.DataFrame(records)
    capacity = frame["physical_rooms"].astype(float).to_numpy()
    focus_horizons = groups["horizon"].loc[
        groups["horizon"]["horizon_days"] <= 7
    ]
    report = {
        "metrics": overall,
        "baseline_metrics_by_name": baseline_metrics,
        "best_baseline_name": best_baseline_name,
        "baseline_metrics": best_baseline_metrics,
        "baseline_improvement": float(
            1.0 - overall["wape"] / best_baseline_metrics["wape"]
        ),
        "best_baseline_improvement": {
            metric: float(1.0 - overall[metric] / best_baseline_metrics[metric])
            for metric in ("mae", "rmse", "wape")
        },
        "improved_horizons_d1_d7": int(
            (focus_horizons["baseline_wape_improvement"] > 0.0).sum()
        ),
        "max_horizon_relative_degradation_d1_d7": float(
            (-focus_horizons["baseline_wape_improvement"]).max()
        ),
        "worst_room_type_wape": float(groups["room_type"]["wape"].max()),
        "worst_high_volume_room_type_wape": float(
            groups["room_type"].loc[
                groups["room_type"]["actual_mean"] >= 10.0, "wape"
            ].max()
        ),
        "worst_low_volume_room_type_mae": float(
            groups["room_type"].loc[
                groups["room_type"]["actual_mean"] < 10.0, "mae"
            ].max()
        ),
        "horizon_10_wape": float(
            groups["horizon"].loc[
                groups["horizon"]["horizon_days"] == 10, "wape"
            ].iloc[0]
        ),
        "raw_negative": int((raw < 0).sum()),
        "raw_above_capacity": int((raw > capacity).sum()),
        "clipped_negative": int((prediction < 0).sum()),
        "clipped_above_capacity": int((prediction > capacity).sum()),
    }
    if bootstrap_samples:
        report["bootstrap"] = _bootstrap_improvement(
            frame, actual, prediction, baseline, bootstrap_samples
        )
    return report, groups


def selection_score(report: dict[str, Any]) -> float:
    return float(
        report["metrics"]["wape"]
        + 0.05 * report["worst_high_volume_room_type_wape"]
        + 0.005 * report["worst_low_volume_room_type_mae"]
        + 0.10 * report["horizon_10_wape"]
    )
