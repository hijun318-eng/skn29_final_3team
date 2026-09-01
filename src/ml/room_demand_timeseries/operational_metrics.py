"""운영 객실 수요 예측의 공통 지표·잔차·구간·지연시간 계산기다."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd


METRIC_CONTRACT_VERSION = "room-demand-operational-metrics-v1"


class DemandMetricSuite:
    """모든 평가 경로가 동일한 정의와 예외 처리를 사용하게 한다."""

    @staticmethod
    def _vectors(*values: Iterable[float]) -> list[np.ndarray]:
        arrays = [np.asarray(value, dtype=float).reshape(-1) for value in values]
        if not arrays or not len(arrays[0]):
            raise ValueError("metric input must not be empty")
        if any(array.shape != arrays[0].shape for array in arrays[1:]):
            raise ValueError("metric inputs must have the same shape")
        if any(not np.isfinite(array).all() for array in arrays):
            raise ValueError("metric input contains a non-finite value")
        return arrays

    @staticmethod
    def _safe_ratio(numerator: float, denominator: float) -> float | None:
        return float(numerator / denominator) if denominator > 0.0 else None

    @classmethod
    def point_metrics(
        cls,
        actual: Iterable[float],
        prediction: Iterable[float],
        baseline: Iterable[float] | None = None,
    ) -> dict[str, float | int | None]:
        """MAE·RMSE·WAPE 중심의 JSON-safe 점 예측 지표를 계산한다."""

        arrays = cls._vectors(actual, prediction)
        actual_values, predicted_values = arrays
        error = predicted_values - actual_values
        absolute_error = np.abs(error)
        actual_denominator = float(np.abs(actual_values).sum())
        smape_denominator = np.abs(actual_values) + np.abs(predicted_values)
        valid_smape = smape_denominator > 0.0
        centered = actual_values - actual_values.mean()
        total_variance = float(np.square(centered).sum())
        quantiles = np.quantile(absolute_error, [0.50, 0.75, 0.90, 0.95, 0.99])
        baseline_mae: float | None = None
        if baseline is not None:
            baseline_values = cls._vectors(actual_values, baseline)[1]
            baseline_mae = float(np.abs(actual_values - baseline_values).mean())
        return {
            "rows": int(len(actual_values)),
            "actual_total": float(actual_values.sum()),
            "actual_mean": float(actual_values.mean()),
            "mae": float(absolute_error.mean()),
            "rmse": float(np.sqrt(np.square(error).mean())),
            "wape": cls._safe_ratio(float(absolute_error.sum()), actual_denominator),
            "r2": (
                float(1.0 - np.square(error).sum() / total_variance)
                if len(actual_values) >= 2 and total_variance > 0.0
                else None
            ),
            "bias_rooms": float(error.mean()),
            "bias": cls._safe_ratio(float(error.sum()), actual_denominator),
            "smape": (
                float(
                    np.mean(
                        2.0
                        * absolute_error[valid_smape]
                        / smape_denominator[valid_smape]
                    )
                )
                if valid_smape.any()
                else None
            ),
            "mase": (
                float(absolute_error.mean() / baseline_mae)
                if baseline_mae is not None and baseline_mae > 0.0
                else None
            ),
            "absolute_error_p50": float(quantiles[0]),
            "absolute_error_p75": float(quantiles[1]),
            "absolute_error_p90": float(quantiles[2]),
            "absolute_error_p95": float(quantiles[3]),
            "absolute_error_p99": float(quantiles[4]),
            "absolute_error_max": float(absolute_error.max()),
            "within_1_room_rate": float((absolute_error <= 1.0).mean()),
            "within_3_rooms_rate": float((absolute_error <= 3.0).mean()),
            "within_5_rooms_rate": float((absolute_error <= 5.0).mean()),
            "under_prediction_rate": float((error < 0.0).mean()),
            "over_prediction_rate": float((error > 0.0).mean()),
            "exact_prediction_rate": float(np.isclose(error, 0.0).mean()),
        }

    @classmethod
    def compare(
        cls,
        actual: Iterable[float],
        candidate: Iterable[float],
        baseline: Iterable[float],
    ) -> dict[str, Any]:
        """후보와 기준선의 절대·상대 개선을 같은 행에서 계산한다."""

        actual_values, candidate_values, baseline_values = cls._vectors(
            actual, candidate, baseline
        )
        candidate_metrics = cls.point_metrics(
            actual_values, candidate_values, baseline_values
        )
        baseline_metrics = cls.point_metrics(actual_values, baseline_values)
        relative: dict[str, float | None] = {}
        absolute: dict[str, float] = {}
        for metric in ("mae", "rmse", "wape"):
            candidate_value = candidate_metrics[metric]
            baseline_value = baseline_metrics[metric]
            if candidate_value is None or baseline_value is None:
                relative[metric] = None
                absolute[metric] = 0.0
                continue
            relative[metric] = cls._safe_ratio(
                float(baseline_value) - float(candidate_value),
                float(baseline_value),
            )
            absolute[metric] = float(baseline_value) - float(candidate_value)
        return {
            "candidate_metrics": candidate_metrics,
            "baseline_metrics": baseline_metrics,
            "relative_improvement": relative,
            "absolute_reduction": absolute,
            "better_on_all_primary_metrics": all(
                absolute[metric] > 0.0 for metric in ("mae", "rmse", "wape")
            ),
        }

    @classmethod
    def interval_metrics(
        cls,
        actual: Iterable[float],
        lower: Iterable[float],
        upper: Iterable[float],
        *,
        nominal_coverage: float,
        capacity: Iterable[float] | None = None,
    ) -> dict[str, float | int]:
        """예측구간 포함률·폭·Winkler 점수를 계산한다."""

        actual_values, lower_values, upper_values = cls._vectors(actual, lower, upper)
        if not 0.0 < nominal_coverage < 1.0:
            raise ValueError("nominal coverage must be between zero and one")
        if (lower_values > upper_values).any():
            raise ValueError("prediction interval lower bound exceeds upper bound")
        width = upper_values - lower_values
        below = actual_values < lower_values
        above = actual_values > upper_values
        alpha = 1.0 - nominal_coverage
        score = width.copy()
        score[below] += (2.0 / alpha) * (lower_values[below] - actual_values[below])
        score[above] += (2.0 / alpha) * (actual_values[above] - upper_values[above])
        normalized_width: float | None = None
        if capacity is not None:
            capacity_values = cls._vectors(actual_values, capacity)[1]
            if (capacity_values <= 0.0).any():
                raise ValueError("interval capacity must be positive")
            normalized_width = float(np.mean(width / capacity_values))
        coverage = float((~below & ~above).mean())
        return {
            "rows": int(len(actual_values)),
            "nominal_coverage": float(nominal_coverage),
            "empirical_coverage": coverage,
            "absolute_calibration_error": float(abs(coverage - nominal_coverage)),
            "below_interval_rate": float(below.mean()),
            "above_interval_rate": float(above.mean()),
            "mean_width_rooms": float(width.mean()),
            "median_width_rooms": float(np.median(width)),
            "normalized_mean_width": normalized_width,
            "mean_interval_score": float(score.mean()),
        }

    @classmethod
    def latency_metrics(cls, latency_ms: Iterable[float]) -> dict[str, float | int]:
        """실제 요청 단위 추론 지연의 평균과 상위 분위수를 계산한다."""

        values = cls._vectors(latency_ms)[0]
        if (values < 0.0).any():
            raise ValueError("inference latency must not be negative")
        quantiles = np.quantile(values, [0.50, 0.95, 0.99])
        return {
            "measurements": int(len(values)),
            "mean_ms": float(values.mean()),
            "p50_ms": float(quantiles[0]),
            "p95_ms": float(quantiles[1]),
            "p99_ms": float(quantiles[2]),
            "max_ms": float(values.max()),
        }

    @classmethod
    def residual_diagnostics(
        cls,
        frame: pd.DataFrame,
        *,
        actual_column: str,
        prediction_column: str,
    ) -> dict[str, float | int | None]:
        """편향, 극단오차와 시계열 잔차 자기상관을 진단한다."""

        actual, prediction = cls._vectors(
            frame[actual_column], frame[prediction_column]
        )
        residual = prediction - actual
        centered = residual - residual.mean()
        standard_deviation = float(residual.std(ddof=0))
        residual_quantiles = np.quantile(
            residual, [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
        )
        absolute_quantiles = np.quantile(
            np.abs(residual), [0.50, 0.75, 0.90, 0.95, 0.99]
        )
        skewness = (
            float(np.mean((centered / standard_deviation) ** 3))
            if standard_deviation > 0.0
            else None
        )
        sorted_frame = frame.assign(_residual=residual).sort_values(
            [
                "property_id",
                "room_type_code",
                "horizon_days",
                "cutoff_date",
                "target_date",
            ]
        )
        return {
            "rows": int(len(residual)),
            "residual_mean_rooms": float(residual.mean()),
            "residual_standard_deviation_rooms": standard_deviation,
            "residual_skewness": skewness,
            "residual_quantiles_rooms": {
                name: float(value)
                for name, value in zip(
                    ("p01", "p05", "p10", "p25", "p50", "p75", "p90", "p95", "p99"),
                    residual_quantiles,
                )
            },
            "absolute_error_quantiles_rooms": {
                name: float(value)
                for name, value in zip(
                    ("p50", "p75", "p90", "p95", "p99"),
                    absolute_quantiles,
                )
            },
            "residual_lag_1_autocorrelation": cls._grouped_autocorrelation(
                sorted_frame, 1
            ),
            "residual_lag_7_autocorrelation": cls._grouped_autocorrelation(
                sorted_frame, 7
            ),
            "absolute_error_actual_correlation": cls._correlation(
                np.abs(residual), actual
            ),
        }

    @staticmethod
    def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
        if len(left) < 2 or float(left.std()) == 0.0 or float(right.std()) == 0.0:
            return None
        return float(np.corrcoef(left, right)[0, 1])

    @classmethod
    def _grouped_autocorrelation(
        cls, frame: pd.DataFrame, lag: int
    ) -> float | None:
        earlier: list[np.ndarray] = []
        later: list[np.ndarray] = []
        for _, group in frame.groupby(
            ["property_id", "room_type_code", "horizon_days"], sort=True
        ):
            values = group["_residual"].to_numpy(dtype=float)
            if len(values) > lag:
                earlier.append(values[:-lag])
                later.append(values[lag:])
        if not earlier:
            return None
        return cls._correlation(np.concatenate(earlier), np.concatenate(later))
