from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import FEATURES, NUMERIC_FEATURES, ProjectConfig


@dataclass
class DatasetBundle:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    inference: pd.DataFrame
    profile: dict


class ReservationDatasetBuilder:
    def __init__(self, config: ProjectConfig):
        self.config = config

    def build(self) -> DatasetBundle:
        if not self.config.source_snapshot_id or not self.config.source_extracted_at:
            raise ValueError(
                "source lineage is required: set ANSWERVICE_ML_SOURCE_SNAPSHOT_ID "
                "and ANSWERVICE_ML_SOURCE_EXTRACTED_AT"
            )
        reservations = pd.read_csv(self.config.reservation_csv, low_memory=False)
        guests = pd.read_csv(self.config.guest_csv, low_memory=False)
        if "outcome_recorded_at" not in reservations.columns:
            raise ValueError(
                "PMS source must contain outcome_recorded_at for point-in-time label validation"
            )
        reservations["checkin_date"] = pd.to_datetime(reservations["checkin_date"])
        reservations["checkout_date"] = pd.to_datetime(reservations["checkout_date"])
        reservations["booked_at"] = pd.to_datetime(
            reservations["booked_at"], utc=True
        ).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
        reservations["outcome_recorded_at"] = pd.to_datetime(
            reservations["outcome_recorded_at"], utc=True, errors="coerce"
        ).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
        reservations["prediction_cutoff_at"] = (
            reservations["checkin_date"] - pd.Timedelta(days=1)
        ) + pd.Timedelta(hours=18)
        source_status = reservations["reservation_status"].value_counts().to_dict()

        frame = reservations.merge(
            guests[["guest_id", "country_group"]], on="guest_id", how="left"
        )
        frame = self._add_features(frame)
        frame[NUMERIC_FEATURES] = frame[NUMERIC_FEATURES].astype("float64")
        if int(source_status.get("NO_SHOW", 0)) == 0:
            raise ValueError(
                "PMS source contains zero NO_SHOW outcomes; source-label training is blocked"
            )

        eligible = frame[
            (~frame["is_forecast"].astype(bool))
            & frame["reservation_status"].isin(
                ["CHECKED_OUT", "CHECKED_IN", "COMPLETED", "NO_SHOW"]
            )
            & (frame["booked_at"] <= frame["prediction_cutoff_at"])
            & (frame["outcome_recorded_at"] > frame["prediction_cutoff_at"])
        ].copy()
        eligible["is_no_show"] = eligible["reservation_status"].eq("NO_SHOW").astype(int)
        eligible["label_source"] = self.config.label_rule_version

        test_end = pd.Timestamp(self.config.test_end)
        train = eligible[eligible["checkin_date"] <= self.config.train_end].copy()
        validation = eligible[
            (eligible["checkin_date"] > self.config.train_end)
            & (eligible["checkin_date"] <= self.config.validation_end)
        ].copy()
        test = eligible[
            (eligible["checkin_date"] > self.config.validation_end)
            & (eligible["checkin_date"] <= test_end)
        ].copy()
        inference = frame[
            frame["is_forecast"].astype(bool)
            & (frame["checkin_date"] > test_end)
            & (frame["booked_at"] <= frame["prediction_cutoff_at"])
        ].copy()

        columns = [
            "reservation_id",
            "guest_id",
            "checkin_date",
            "prediction_cutoff_at",
            *FEATURES,
            "is_synthetic",
        ]
        labeled_columns = [*columns, "label_source", "is_no_show"]
        profile = {
            "source_rows": int(len(reservations)),
            "source_status_counts": {str(k): int(v) for k, v in source_status.items()},
            "source_no_show_rows": int(source_status.get("NO_SHOW", 0)),
            "eligible_labeled_rows": int(len(eligible)),
            "excluded_cancelled_rows": int(source_status.get("CANCELLED", 0)),
            "label_rule_version": self.config.label_rule_version,
            "source_snapshot_id": self.config.source_snapshot_id,
            "source_extracted_at": self.config.source_extracted_at,
            "split_rows": {
                "TRAIN": int(len(train)),
                "VALIDATION": int(len(validation)),
                "TEST": int(len(test)),
                "INFERENCE": int(len(inference)),
            },
            "positive_rates": {
                "TRAIN": float(train["is_no_show"].mean()),
                "VALIDATION": float(validation["is_no_show"].mean()),
                "TEST": float(test["is_no_show"].mean()),
            },
        }
        return DatasetBundle(
            train[labeled_columns],
            validation[labeled_columns],
            test[labeled_columns],
            inference[columns],
            profile,
        )

    def _add_features(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        result["lead_time_days"] = (
            result["checkin_date"] - result["booked_at"].dt.normalize()
        ).dt.days.clip(lower=0)
        result["length_of_stay"] = (
            result["checkout_date"] - result["checkin_date"]
        ).dt.days.clip(lower=1)
        result["discount_ratio"] = np.where(
            result["gross_room_amount"] > 0,
            result["discount_amount"] / result["gross_room_amount"],
            0.0,
        )
        result["arrival_month"] = result["checkin_date"].dt.month
        result["arrival_day_of_week"] = result["checkin_date"].dt.dayofweek
        result["arrival_weekend_flag"] = (
            result["arrival_day_of_week"] >= 5
        ).astype(int)
        counts = (
            result.groupby(["guest_id", "checkin_date"]).size().rename("daily_count")
        )
        history = counts.groupby(level=0).cumsum() - counts
        result = result.merge(
            history.rename("previous_booking_count").reset_index(),
            on=["guest_id", "checkin_date"],
            how="left",
        )
        result["country_group"] = result["country_group"].fillna("UNKNOWN")
        return result
