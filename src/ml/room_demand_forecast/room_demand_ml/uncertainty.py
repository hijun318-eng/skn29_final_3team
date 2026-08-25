from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IntervalEvaluation:
    target_coverage: float
    actual_coverage: float
    mean_width: float
    row_count: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "target_coverage": self.target_coverage,
            "actual_coverage": self.actual_coverage,
            "mean_width": self.mean_width,
            "row_count": self.row_count,
        }


class PredictionIntervalCalibrator:
    GROUP_COLUMNS = ["room_type_code", "horizon_days"]

    def __init__(self, target_coverage: float = 0.95) -> None:
        if not 0 < target_coverage < 1:
            raise ValueError("target_coverage는 0과 1 사이여야 합니다.")
        self.target_coverage = target_coverage
        self._margins: pd.DataFrame | None = None

    def fit(
        self,
        frame: pd.DataFrame,
        actual: np.ndarray,
        prediction: np.ndarray,
    ) -> "PredictionIntervalCalibrator":
        work = frame[self.GROUP_COLUMNS].copy()
        work["absolute_error"] = np.abs(
            np.asarray(actual, dtype=float) - np.asarray(prediction, dtype=float)
        )
        self._margins = (
            work.groupby(self.GROUP_COLUMNS, as_index=False)["absolute_error"]
            .quantile(self.target_coverage, interpolation="higher")
            .rename(columns={"absolute_error": "margin_rooms"})
        )
        return self

    def bounds(
        self,
        frame: pd.DataFrame,
        prediction: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        if self._margins is None:
            raise RuntimeError("예측구간 보정기를 먼저 fit해야 합니다.")
        matched = frame[self.GROUP_COLUMNS + ["available_room_nights"]].merge(
            self._margins,
            on=self.GROUP_COLUMNS,
            how="left",
            validate="many_to_one",
            sort=False,
        )
        if matched["margin_rooms"].isna().any():
            raise ValueError("예측구간 margin이 없는 그룹이 있습니다.")
        center = np.asarray(prediction, dtype=float)
        margin = matched["margin_rooms"].to_numpy(dtype=float)
        capacity = matched["available_room_nights"].to_numpy(dtype=float)
        lower = np.maximum(np.floor(center - margin), 0).astype(int)
        upper = np.minimum(np.ceil(center + margin), capacity).astype(int)
        return lower, upper

    def evaluate(
        self,
        actual: np.ndarray,
        lower: np.ndarray,
        upper: np.ndarray,
    ) -> IntervalEvaluation:
        actual_values = np.asarray(actual, dtype=float)
        lower_values = np.asarray(lower, dtype=float)
        upper_values = np.asarray(upper, dtype=float)
        covered = (actual_values >= lower_values) & (actual_values <= upper_values)
        return IntervalEvaluation(
            target_coverage=self.target_coverage,
            actual_coverage=float(covered.mean()),
            mean_width=float((upper_values - lower_values).mean()),
            row_count=len(actual_values),
        )

    def margins(self) -> pd.DataFrame:
        if self._margins is None:
            raise RuntimeError("예측구간 보정기를 먼저 fit해야 합니다.")
        return self._margins.copy()
