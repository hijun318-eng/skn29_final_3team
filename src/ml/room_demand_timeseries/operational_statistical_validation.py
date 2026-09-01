"""후보 모델의 기준선 개선이 우연인지 paired 시계열 bootstrap으로 검증한다."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd


class PairedBaselineValidator:
    """같은 cutoff 행의 오차를 7일 이동 블록으로 재표집한다."""

    def __init__(
        self,
        *,
        samples: int = 500,
        block_days: int = 7,
        random_seed: int = 20260901,
    ) -> None:
        if samples < 100:
            raise ValueError("bootstrap samples must be at least 100")
        if block_days < 1:
            raise ValueError("bootstrap block days must be positive")
        self.samples = samples
        self.block_days = block_days
        self.random_seed = random_seed

    def validate(
        self,
        frame: pd.DataFrame,
        candidate: Iterable[float],
        baseline: Iterable[float],
        *,
        actual_column: str = "target_rooms_sold",
        cutoff_column: str = "cutoff_date",
    ) -> dict[str, Any]:
        """개선량 신뢰구간과 cutoff 단위 승·무·패를 반환한다."""

        actual = frame[actual_column].to_numpy(dtype=float)
        candidate_values = np.asarray(candidate, dtype=float).reshape(-1)
        baseline_values = np.asarray(baseline, dtype=float).reshape(-1)
        if not len(actual) or candidate_values.shape != actual.shape:
            raise ValueError("candidate predictions do not match evaluation rows")
        if baseline_values.shape != actual.shape:
            raise ValueError("baseline predictions do not match evaluation rows")
        values = np.column_stack([actual, candidate_values, baseline_values])
        if not np.isfinite(values).all():
            raise ValueError("paired validation contains a non-finite value")
        daily = pd.DataFrame(
            {
                "cutoff": pd.to_datetime(frame[cutoff_column], errors="raise"),
                "actual_abs": np.abs(actual),
                "candidate_error": np.abs(candidate_values - actual),
                "baseline_error": np.abs(baseline_values - actual),
                "rows": 1.0,
            }
        ).groupby("cutoff", sort=True).sum()
        if daily.empty:
            raise ValueError("paired validation has no cutoff rows")
        point = self._improvement(daily.sum().to_numpy(dtype=float))
        bootstrap = self._bootstrap(daily.to_numpy(dtype=float))
        difference = daily["baseline_error"] - daily["candidate_error"]
        tolerance = 1e-12
        return {
            "method": "paired_moving_block_bootstrap_by_cutoff_date",
            "samples": self.samples,
            "block_days": min(self.block_days, len(daily)),
            "cutoff_days": int(len(daily)),
            "point_estimate": point,
            "ci95": {
                key: [
                    float(np.quantile([row[key] for row in bootstrap], 0.025)),
                    float(np.quantile([row[key] for row in bootstrap], 0.975)),
                ]
                for key in point
            },
            "candidate_win_rate_by_cutoff": float((difference > tolerance).mean()),
            "tie_rate_by_cutoff": float((difference.abs() <= tolerance).mean()),
            "candidate_loss_rate_by_cutoff": float((difference < -tolerance).mean()),
            "statistically_better": bool(
                np.quantile(
                    [row["wape_absolute_improvement"] for row in bootstrap],
                    0.025,
                )
                > 0.0
            ),
        }

    def _bootstrap(self, daily: np.ndarray) -> list[dict[str, float]]:
        block_days = min(self.block_days, len(daily))
        block_count = int(np.ceil(len(daily) / block_days))
        max_start = len(daily) - block_days + 1
        rng = np.random.default_rng(self.random_seed)
        output: list[dict[str, float]] = []
        for _ in range(self.samples):
            starts = rng.integers(0, max_start, size=block_count)
            indices = np.concatenate(
                [np.arange(start, start + block_days) for start in starts]
            )[: len(daily)]
            output.append(self._improvement(daily[indices].sum(axis=0)))
        return output

    @staticmethod
    def _improvement(totals: np.ndarray) -> dict[str, float]:
        actual_abs, candidate_error, baseline_error, rows = totals
        wape_absolute = (
            (baseline_error - candidate_error) / actual_abs
            if actual_abs > 0.0
            else 0.0
        )
        relative = (
            (baseline_error - candidate_error) / baseline_error
            if baseline_error > 0.0
            else 0.0
        )
        return {
            "wape_absolute_improvement": float(wape_absolute),
            "wape_relative_improvement": float(relative),
            "mae_improvement_rooms": float(
                (baseline_error - candidate_error) / rows
            ),
        }
