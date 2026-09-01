"""동일 기준 모델 비교를 위한 시간 split·행 grain 계약을 검증한다."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from .contracts import SPLIT_WINDOWS
from .operational_contracts import OPERATIONAL_MAX_HORIZON


IDENTITY_COLUMNS = [
    "property_id",
    "room_type_code",
    "cutoff_date",
    "target_date",
    "horizon_days",
]


class AlignedSplitValidator:
    """네 split의 시간 독립성, D+1~D+7 완전성, 시리즈 일관성을 확인한다."""

    @staticmethod
    def validate(datasets: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
        """네 split의 시간·grain·horizon·시리즈 계약을 실패 차단형으로 검증한다."""

        expected = {window.name: window for window in SPLIT_WINDOWS}
        if set(datasets) != set(expected):
            raise ValueError(
                "aligned comparison requires TRAIN, VALIDATION, TEST_A, TEST_B"
            )
        summary: dict[str, Any] = {}
        all_identities: set[tuple[object, ...]] = set()
        common_series: set[tuple[str, str]] | None = None
        expected_horizons = list(range(1, OPERATIONAL_MAX_HORIZON + 1))
        for name, window in expected.items():
            frame = datasets[name]
            if frame.empty:
                raise ValueError(f"aligned split {name} is empty")
            missing = sorted(set(IDENTITY_COLUMNS) - set(frame.columns))
            if missing:
                raise ValueError(f"aligned split {name} missing columns: {missing}")
            if frame.duplicated(IDENTITY_COLUMNS).any():
                raise ValueError(f"aligned split {name} has duplicate prediction grain")
            cutoffs = pd.to_datetime(frame["cutoff_date"], errors="raise")
            targets = pd.to_datetime(frame["target_date"], errors="raise")
            if not cutoffs.between(window.cutoff_start, window.cutoff_end).all():
                raise ValueError(f"aligned split {name} exceeds its cutoff window")
            horizons = frame["horizon_days"].astype(int)
            if sorted(horizons.unique().tolist()) != expected_horizons:
                raise ValueError(f"aligned split {name} has unsupported horizons")
            if not ((targets - cutoffs).dt.days == horizons).all():
                raise ValueError(f"aligned split {name} target and horizon are inconsistent")
            grouped = frame.assign(_horizon=horizons).groupby(
                ["cutoff_date", "property_id", "room_type_code"], sort=True
            )["_horizon"]
            if any(sorted(values.tolist()) != expected_horizons for _, values in grouped):
                raise ValueError(f"aligned split {name} has incomplete D+1 through D+7")
            series = set(
                frame[["property_id", "room_type_code"]]
                .astype(str)
                .itertuples(index=False, name=None)
            )
            if common_series is not None and series != common_series:
                raise ValueError("aligned split series coverage is inconsistent")
            common_series = series
            identities = set(
                frame[IDENTITY_COLUMNS].itertuples(index=False, name=None)
            )
            if all_identities.intersection(identities):
                raise ValueError("aligned split identity overlap detected")
            all_identities.update(identities)
            summary[name] = {
                "rows": int(len(frame)),
                "cutoff_start": str(cutoffs.min().date()),
                "cutoff_end": str(cutoffs.max().date()),
                "cutoff_days": int(cutoffs.nunique()),
                "series_count": int(len(series)),
                "horizons": expected_horizons,
            }
        return {
            "contract": "2018-2023_train__2024_validation__2025_test_a__2026_test_b",
            "max_horizon": OPERATIONAL_MAX_HORIZON,
            "splits": summary,
        }
