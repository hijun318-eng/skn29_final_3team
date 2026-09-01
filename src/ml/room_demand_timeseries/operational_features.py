"""목표일 기준 이력과 시점 보존 예약·행사·공사 신호를 결합한다."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .contracts import IDENTITY_COLUMNS, LABEL_COLUMNS, SplitWindow
from .features import TimeSeriesFeatureBuilder
from .operational_contracts import (
    OPERATIONAL_FEATURE_COLUMNS,
    OPERATIONAL_MAX_HORIZON,
    POINT_IN_TIME_SIGNAL_FEATURES,
    SIGNAL_IDENTITY_COLUMNS,
    SIGNAL_REQUIRED_COLUMNS,
    TARGET_CAPACITY_COLUMN,
    TARGET_HISTORY_FEATURES,
)
from .operational_governance import OperationalDataGate


class OperationalFeatureBuilder:
    """기존 과거 특징에 목표일별 이력과 cutoff 시점 미래 신호를 엄격히 결합한다."""

    def __init__(self) -> None:
        self._historical = TimeSeriesFeatureBuilder()

    @staticmethod
    def validate_signals(signals: pd.DataFrame) -> pd.DataFrame:
        """신호 표의 grain·날짜·수치 범위를 검증하고 정규화된 복사본을 반환한다."""

        missing = sorted(set(SIGNAL_REQUIRED_COLUMNS) - set(signals.columns))
        if missing:
            raise ValueError(f"point-in-time signals missing columns: {missing}")
        frame = signals[SIGNAL_REQUIRED_COLUMNS].copy()
        frame["property_id"] = frame["property_id"].astype(str).str.upper()
        frame["room_type_code"] = frame["room_type_code"].astype(str)
        for column in ("cutoff_date", "target_date"):
            frame[column] = pd.to_datetime(frame[column])
        for column in POINT_IN_TIME_SIGNAL_FEATURES + ["horizon_days"]:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        if int(frame.duplicated(SIGNAL_IDENTITY_COLUMNS).sum()):
            raise ValueError("duplicate point-in-time signal detected")
        expected_horizon = (frame["target_date"] - frame["cutoff_date"]).dt.days
        if not expected_horizon.equals(frame["horizon_days"].astype(int)):
            raise ValueError("signal target date and horizon are inconsistent")
        numeric = frame[POINT_IN_TIME_SIGNAL_FEATURES].to_numpy(dtype=float)
        if not np.isfinite(numeric).all():
            raise ValueError("point-in-time signals contain non-finite values")
        if not frame["horizon_days"].between(1, OPERATIONAL_MAX_HORIZON).all():
            raise ValueError("point-in-time signal horizon is unsupported")
        if (frame[TARGET_CAPACITY_COLUMN] <= 0).any():
            raise ValueError("target sellable rooms must be positive")
        non_negative = [
            column
            for column in POINT_IN_TIME_SIGNAL_FEATURES
            if column not in {"booking_pickup_acceleration", "net_booking_pickup_7d"}
        ]
        if (frame[non_negative] < 0).any().any():
            raise ValueError("point-in-time signal count is negative")
        frame, provenance = OperationalDataGate.validate_signal_provenance(frame)
        result = frame.sort_values(SIGNAL_IDENTITY_COLUMNS).reset_index(drop=True)
        result.attrs["signal_provenance"] = provenance.__dict__
        return result

    @staticmethod
    def _target_history(samples: pd.DataFrame, facts: pd.DataFrame) -> pd.DataFrame:
        """각 목표일에서 7일 단위로 거슬러 올라간 실제 객실 수를 조회한다."""

        result = samples.copy()
        history = facts.copy()
        history["property_id"] = history["property_id"].astype(str).str.upper()
        history["business_date"] = pd.to_datetime(history["business_date"])
        series = history.set_index(
            ["property_id", "room_type_code", "business_date"]
        )["rooms_sold"].astype(float)
        lag_columns: list[str] = []
        for lag in range(7, 85, 7):
            column = f"_target_lag_{lag}"
            keys = pd.MultiIndex.from_arrays(
                [
                    result["property_id"].astype(str).str.upper(),
                    result["room_type_code"].astype(str),
                    pd.to_datetime(result["target_date"]) - pd.Timedelta(days=lag),
                ]
            )
            result[column] = series.reindex(keys).to_numpy()
            lag_columns.append(column)
        for lag in (7, 14, 21, 28):
            result[f"target_rooms_sold_lag_{lag}"] = result[f"_target_lag_{lag}"]
        result["target_same_weekday_mean_4w"] = result[lag_columns[:4]].mean(axis=1)
        result["target_same_weekday_mean_8w"] = result[lag_columns[:8]].mean(axis=1)
        result["target_same_weekday_mean_12w"] = result[lag_columns].mean(axis=1)
        return result.drop(columns=lag_columns)

    def _merge(
        self,
        samples: pd.DataFrame,
        facts: pd.DataFrame,
        signals: pd.DataFrame,
        *,
        require_labels: bool,
    ) -> pd.DataFrame:
        normalized = self.validate_signals(signals)
        working = samples.copy()
        working["property_id"] = working["property_id"].astype(str).str.upper()
        result = working.merge(
            normalized,
            on=SIGNAL_IDENTITY_COLUMNS,
            how="left",
            validate="one_to_one",
        )
        if result[POINT_IN_TIME_SIGNAL_FEATURES].isna().any().any():
            raise ValueError("point-in-time signals do not cover every sample")
        result = self._target_history(result, facts)
        if result[TARGET_HISTORY_FEATURES].isna().any().any():
            raise ValueError("target-date history is incomplete")
        if require_labels:
            invalid = result["target_rooms_sold"] > result[TARGET_CAPACITY_COLUMN]
            if invalid.any():
                raise ValueError("target rooms sold exceed target sellable rooms")
            result["target_occupancy_rate"] = (
                result["target_rooms_sold"] / result[TARGET_CAPACITY_COLUMN]
            )
        columns = list(
            dict.fromkeys(
                IDENTITY_COLUMNS
                + OPERATIONAL_FEATURE_COLUMNS
                + (LABEL_COLUMNS if require_labels else [])
                + ["dataset_split", "is_synthetic"]
            )
        )
        return result[columns].sort_values(IDENTITY_COLUMNS).reset_index(drop=True)

    def build_labeled(
        self,
        facts: pd.DataFrame,
        signals: pd.DataFrame,
        window: SplitWindow,
    ) -> pd.DataFrame:
        """지정 cutoff 범위의 label 표본과 동일 grain 신호를 결합한다."""

        samples = self._historical.build_labeled(facts, window)
        samples = samples.loc[
            samples["horizon_days"] <= OPERATIONAL_MAX_HORIZON
        ].copy()
        scoped = signals.loc[
            pd.to_datetime(signals["cutoff_date"]).between(
                pd.Timestamp(window.cutoff_start), pd.Timestamp(window.cutoff_end)
            )
        ].copy()
        return self._merge(samples, facts, scoped, require_labels=True)

    def build_inference(
        self,
        facts: pd.DataFrame,
        signals: pd.DataFrame,
        cutoff_date: str,
        forecast_start: str,
        forecast_end: str,
    ) -> pd.DataFrame:
        """한 기준일의 목표일별 신호가 모두 존재할 때만 추론 특징을 반환한다."""

        samples = self._historical.build_inference(
            facts,
            cutoff_date=cutoff_date,
            forecast_start=forecast_start,
            forecast_end=forecast_end,
        )
        return self._merge(samples, facts, signals, require_labels=False)
