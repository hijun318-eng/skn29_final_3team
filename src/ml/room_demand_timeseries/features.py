from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .calendar_features import KNOWN_HOLIDAY_DATES
from .contracts import (
    FEATURE_COLUMNS,
    IDENTITY_COLUMNS,
    LABEL_COLUMNS,
    MAX_HORIZON,
    SplitWindow,
)


RAW_REQUIRED_COLUMNS = {
    "property_id",
    "business_date",
    "room_type_code",
    "physical_rooms",
    "available_room_nights",
    "rooms_sold",
    "daily_adr",
    "cancellation_rate",
    "is_synthetic",
}


@dataclass(frozen=True)
class DataAudit:
    rows: int
    min_date: str
    max_date: str
    properties: list[str]
    room_types: list[str]
    duplicate_rows: int
    missing_dates: int
    invalid_target_rows: int
    synthetic_only: bool


class TimeSeriesFeatureBuilder:
    """Build point-in-time samples using observations at or before cutoff."""

    def load_daily_facts(self, path: Path) -> tuple[pd.DataFrame, DataAudit]:
        frame = pd.read_csv(path)
        missing = sorted(RAW_REQUIRED_COLUMNS - set(frame.columns))
        if missing:
            raise ValueError(f"daily facts missing columns: {missing}")
        frame["business_date"] = pd.to_datetime(frame["business_date"])
        frame = frame.sort_values(
            ["property_id", "room_type_code", "business_date"]
        ).reset_index(drop=True)
        key = ["property_id", "room_type_code", "business_date"]
        duplicates = int(frame.duplicated(key).sum())
        missing_dates = 0
        for _, group in frame.groupby(key[:2], sort=False):
            gaps = group["business_date"].diff().dropna().dt.days
            missing_dates += int((gaps != 1).sum())
        invalid_target = int(
            (
                (frame["rooms_sold"] < 0)
                | (frame["rooms_sold"] > frame["physical_rooms"])
            ).sum()
        )
        audit = DataAudit(
            rows=int(len(frame)),
            min_date=frame["business_date"].min().date().isoformat(),
            max_date=frame["business_date"].max().date().isoformat(),
            properties=sorted(frame["property_id"].astype(str).unique()),
            room_types=sorted(frame["room_type_code"].astype(str).unique()),
            duplicate_rows=duplicates,
            missing_dates=missing_dates,
            invalid_target_rows=invalid_target,
            synthetic_only=bool(frame["is_synthetic"].astype(bool).all()),
        )
        if duplicates or missing_dates or invalid_target:
            raise ValueError(f"daily facts audit failed: {audit}")
        return frame, audit

    def build_labeled(
        self,
        facts: pd.DataFrame,
        window: SplitWindow,
    ) -> pd.DataFrame:
        samples: list[pd.DataFrame] = []
        for _, group in facts.groupby(
            ["property_id", "room_type_code"], sort=False
        ):
            base = self._cutoff_features(group)
            for horizon in range(1, MAX_HORIZON + 1):
                sample = base.copy()
                sample["horizon_days"] = horizon
                sample["target_date"] = (
                    sample["cutoff_date"] + pd.to_timedelta(horizon, unit="D")
                )
                sample["target_rooms_sold"] = group["rooms_sold"].shift(
                    -horizon
                ).to_numpy()
                sample["target_occupancy_rate"] = (
                    sample["target_rooms_sold"] / sample["physical_rooms"]
                )
                samples.append(self._add_calendar_features(sample))
        result = pd.concat(samples, ignore_index=True)
        start = pd.Timestamp(window.cutoff_start)
        end = pd.Timestamp(window.cutoff_end)
        result = result.loc[
            result["cutoff_date"].between(start, end)
        ].copy()
        result = result.dropna(subset=FEATURE_COLUMNS + LABEL_COLUMNS)
        result["dataset_split"] = window.name
        self.validate_samples(result, require_labels=True)
        columns = list(
            dict.fromkeys(
                IDENTITY_COLUMNS
                + FEATURE_COLUMNS
                + LABEL_COLUMNS
                + ["dataset_split", "is_synthetic"]
            )
        )
        return result[columns].sort_values(IDENTITY_COLUMNS).reset_index(drop=True)

    def build_inference(
        self,
        facts: pd.DataFrame,
        cutoff_date: str,
        forecast_start: str,
        forecast_end: str,
    ) -> pd.DataFrame:
        cutoff = pd.Timestamp(cutoff_date)
        start = pd.Timestamp(forecast_start)
        end = pd.Timestamp(forecast_end)
        if start <= cutoff or end < start:
            raise ValueError("forecast range must be after cutoff")
        horizons = range((start - cutoff).days, (end - cutoff).days + 1)
        if min(horizons) < 1 or max(horizons) > MAX_HORIZON:
            raise ValueError(f"forecast range exceeds D+{MAX_HORIZON}")
        samples: list[pd.DataFrame] = []
        for _, group in facts.groupby(
            ["property_id", "room_type_code"], sort=False
        ):
            base = self._cutoff_features(group)
            base = base.loc[base["cutoff_date"] == cutoff]
            if len(base) != 1:
                raise ValueError(
                    "cutoff is not available for every property-room type"
                )
            for horizon in horizons:
                sample = base.copy()
                sample["horizon_days"] = horizon
                sample["target_date"] = cutoff + pd.Timedelta(days=horizon)
                samples.append(self._add_calendar_features(sample))
        result = pd.concat(samples, ignore_index=True)
        result = result.dropna(subset=FEATURE_COLUMNS)
        result["dataset_split"] = "INFERENCE"
        self.validate_samples(result, require_labels=False)
        columns = list(
            dict.fromkeys(
                IDENTITY_COLUMNS
                + FEATURE_COLUMNS
                + ["dataset_split", "is_synthetic"]
            )
        )
        return result[columns].sort_values(IDENTITY_COLUMNS).reset_index(drop=True)

    def validate_samples(
        self,
        frame: pd.DataFrame,
        *,
        require_labels: bool,
    ) -> None:
        if frame.empty:
            raise ValueError("generated dataset is empty")
        expected_horizon = (
            frame["target_date"] - frame["cutoff_date"]
        ).dt.days
        if not expected_horizon.equals(frame["horizon_days"].astype(int)):
            raise ValueError("target date and horizon are inconsistent")
        if int(frame.duplicated(IDENTITY_COLUMNS).sum()):
            raise ValueError("duplicate point-in-time sample detected")
        if require_labels:
            invalid = (
                (frame["target_rooms_sold"] < 0)
                | (frame["target_rooms_sold"] > frame["physical_rooms"])
            )
            if int(invalid.sum()):
                raise ValueError("label violates physical room capacity")
        elif any(column in frame for column in LABEL_COLUMNS):
            raise ValueError("inference dataset must not contain labels")

    def _cutoff_features(self, group: pd.DataFrame) -> pd.DataFrame:
        group = group.sort_values("business_date").reset_index(drop=True)
        sold = group["rooms_sold"].astype(float)
        physical = group["physical_rooms"].astype(float)
        output = pd.DataFrame(
            {
                "property_id": group["property_id"].astype(str),
                "room_type_code": group["room_type_code"].astype(str),
                "cutoff_date": group["business_date"],
                "physical_rooms": physical,
                "cutoff_rooms_sold": sold,
                "cutoff_available_room_nights": group[
                    "available_room_nights"
                ].astype(float),
                "cutoff_adr": group["daily_adr"].astype(float),
                "cutoff_cancellation_rate": group[
                    "cancellation_rate"
                ].astype(float),
                "is_synthetic": group["is_synthetic"].astype(bool),
            }
        )
        output["cutoff_available_ratio"] = (
            output["cutoff_available_room_nights"] / physical
        )
        output["cutoff_occupancy_rate"] = sold / physical
        for lag in (1, 7, 14, 21, 28, 364, 365, 371):
            output[f"rooms_sold_lag_{lag}"] = sold.shift(lag)
        for days in (7, 14, 28, 56):
            output[f"rolling_mean_{days}"] = sold.rolling(
                days, min_periods=days
            ).mean()
        output["rolling_std_28"] = sold.rolling(
            28, min_periods=28
        ).std(ddof=0)
        output["same_weekday_mean_4w"] = pd.concat(
            [sold.shift(days) for days in (7, 14, 21, 28)], axis=1
        ).mean(axis=1)
        output["same_weekday_mean_8w"] = pd.concat(
            [sold.shift(days) for days in range(7, 57, 7)], axis=1
        ).mean(axis=1)
        output["same_weekday_mean_12w"] = pd.concat(
            [sold.shift(days) for days in range(7, 85, 7)], axis=1
        ).mean(axis=1)
        output["annual_same_weekday_mean"] = pd.concat(
            [sold.shift(days) for days in (364, 371)], axis=1
        ).mean(axis=1)
        output["trend_7_28"] = (
            output["rolling_mean_7"] - output["rolling_mean_28"]
        ) / physical
        output["adr_lag_7"] = group["daily_adr"].astype(float).shift(7)
        output["cancellation_rate_mean_28"] = group[
            "cancellation_rate"
        ].astype(float).rolling(28, min_periods=28).mean()
        return output

    @staticmethod
    def _add_calendar_features(frame: pd.DataFrame) -> pd.DataFrame:
        target = pd.to_datetime(frame["target_date"])
        result = frame.copy()
        result["target_day_of_week"] = target.dt.dayofweek
        result["target_month"] = target.dt.month
        result["target_week_of_year"] = target.dt.isocalendar().week.astype(int)
        result["target_day_of_year"] = target.dt.dayofyear
        result["target_year"] = target.dt.year
        result["target_is_weekend"] = (target.dt.dayofweek >= 5).astype(int)
        result["target_is_public_holiday"] = target.isin(
            KNOWN_HOLIDAY_DATES
        ).astype(int)
        result["target_is_holiday_eve"] = (
            target + pd.Timedelta(days=1)
        ).isin(KNOWN_HOLIDAY_DATES).astype(int)
        result["target_is_month_start"] = target.dt.is_month_start.astype(int)
        result["target_is_month_end"] = target.dt.is_month_end.astype(int)
        result["target_dow_sin"] = np.sin(2 * np.pi * target.dt.dayofweek / 7)
        result["target_dow_cos"] = np.cos(2 * np.pi * target.dt.dayofweek / 7)
        result["target_year_sin"] = np.sin(2 * np.pi * target.dt.dayofyear / 365.25)
        result["target_year_cos"] = np.cos(2 * np.pi * target.dt.dayofyear / 365.25)
        return result


def sample_hash_columns() -> Iterable[str]:
    return IDENTITY_COLUMNS + FEATURE_COLUMNS + LABEL_COLUMNS
