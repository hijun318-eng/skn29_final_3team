from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectConfig:
    project_dir: Path
    repo_dir: Path
    source_dir: Path
    raw_dir: Path
    artifacts_dir: Path
    model_dir: Path
    source_snapshot_id: str | None = None
    source_extracted_at: str | None = None
    seed: int = 20260804
    feature_set_version: str = "reservation-no-show-feature-v1.0"
    model_version: str = "reservation-no-show-v1.0"
    label_rule_version: str = "PMS_RESERVATION_STATUS_V1"
    train_end: str = "2024-12-31"
    validation_end: str = "2025-12-31"
    test_end: str = "2026-07-28"

    @classmethod
    def default(cls) -> "ProjectConfig":
        project_dir = Path(__file__).resolve().parents[1]
        repo_dir = project_dir.parents[2]
        default_source_dir = (
            repo_dir / "exports" / "synthetic_db_export_20260803_dev_e023b06" / "full"
        )
        source_dir = Path(
            os.getenv("ANSWERVICE_ML_SOURCE_DIR", str(default_source_dir))
        ).resolve()
        artifacts_dir = project_dir / "artifacts"
        return cls(
            project_dir=project_dir,
            repo_dir=repo_dir,
            source_dir=source_dir,
            raw_dir=repo_dir / "data" / "raw" / "reservation_no_show",
            artifacts_dir=artifacts_dir,
            model_dir=artifacts_dir / "models",
            source_snapshot_id=os.getenv("ANSWERVICE_ML_SOURCE_SNAPSHOT_ID"),
            source_extracted_at=os.getenv("ANSWERVICE_ML_SOURCE_EXTRACTED_AT"),
        )

    @property
    def reservation_csv(self) -> Path:
        return self.source_dir / "pms__pms__public__pms_reservations.csv"

    @property
    def guest_csv(self) -> Path:
        return self.source_dir / "pms__pms__public__pms_guests.csv"

    @property
    def inference_csv(self) -> Path:
        return self.raw_dir / "reservation_no_show_inference.csv"


NUMERIC_FEATURES = [
    "lead_time_days",
    "length_of_stay",
    "adult_count",
    "child_count",
    "quoted_room_rate",
    "booked_amount",
    "discount_ratio",
    "previous_booking_count",
    "arrival_month",
    "arrival_day_of_week",
    "arrival_weekend_flag",
]

CATEGORICAL_FEATURES = [
    "room_type_code",
    "rate_plan_code",
    "market_segment",
    "booking_channel",
    "country_group",
]

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
BANNED_FEATURES = [
    "is_no_show",
    "reservation_status",
    "stay_status",
    "qa_simulated_no_show",
    "actual_checkin_at",
    "actual_checkout_at",
    "cancelled_at",
    "cancellation_reason_code",
    "refund_amount",
    "cancellation_fee",
    "source_updated_at",
]
