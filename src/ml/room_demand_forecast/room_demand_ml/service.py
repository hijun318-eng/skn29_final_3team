from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .config import (
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT_DIR,
    FEATURES,
    FILE_NAMES,
    NUMERIC_FEATURES,
)
from .data import DatasetRepository
from .metrics import apply_capacity_clip


@dataclass(frozen=True)
class ForecastRequest:
    property_id: str
    feature_as_of: str
    feature_set_version: str
    input_schema_version: str


class RoomDemandForecastService:
    feature_set_version = "room-demand-feature-v1.0"
    input_schema_version = "room-demand-forecast-input-v1.0"
    model_version = "room-demand-xgb-v1.0"

    def __init__(
        self,
        artifact_dir: Path = DEFAULT_OUTPUT_DIR,
        forecast_path: Path | None = None,
    ):
        self.artifact_dir = artifact_dir
        self.metadata = json.loads(
            (artifact_dir / "room_demand_model_metadata.json").read_text(encoding="utf-8")
        )
        model_path = artifact_dir / "room_demand_model.joblib"
        expected_hash = self.metadata.get("model_sha256")
        actual_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if not expected_hash or actual_hash != expected_hash:
            raise RuntimeError("room demand model artifact integrity check failed")
        self.model_bundle = joblib.load(model_path)
        raw_forecast = DEFAULT_DATA_DIR / FILE_NAMES["forecast"]
        selected_forecast = forecast_path or raw_forecast
        if not selected_forecast.is_file():
            raise FileNotFoundError(
                f"room demand forecast feature file is required: {selected_forecast}"
            )
        self.forecast = DatasetRepository._prepare_types(
            pd.read_csv(selected_forecast, low_memory=False)
        )
        self.margins = pd.read_csv(artifact_dir / "prediction_interval_margins.csv")

    def execute_arguments(self, arguments: dict) -> dict:
        return self.execute(ForecastRequest(**arguments))

    def execute(self, request: ForecastRequest) -> dict:
        started = time.perf_counter()
        base = {
            "property_id": request.property_id,
            "feature_as_of": request.feature_as_of,
            "model_name": self.metadata["model_name"],
            "model_version": self.model_version,
            "feature_set_version": self.feature_set_version,
            "input_schema_version": self.input_schema_version,
            "execution_id": f"mlrun-{uuid.uuid4()}",
        }
        try:
            self._validate(request)
            selected = self.forecast.loc[
                self.forecast["property_id"].eq(request.property_id)
                & self.forecast["prediction_cutoff_date"].eq(
                    pd.Timestamp(request.feature_as_of)
                )
            ].sort_values(["target_date", "room_type_code"])
            if selected.empty:
                raise LookupError("property forecast not found")
            self._validate_forecast_rows(selected)
            result_frame = self._predict(selected)
            rows = json.loads(result_frame.to_json(orient="records", date_format="iso"))
            result = {
                **base,
                "forecast_status": "SUCCESS",
                "forecast_days": 7,
                "forecast_row_count": len(rows),
                "predictions": rows,
                "error_message": None,
                "is_synthetic": bool(self.metadata["is_synthetic"]),
                "display_label": "모델 예측 · 합성 데이터 기반 예측",
            }
        except LookupError as error:
            result = self._error(base, "FEATURE_NOT_FOUND", error)
        except (TypeError, ValueError) as error:
            result = self._error(base, "INVALID_INPUT", error)
        except Exception as error:  # pragma: no cover - service boundary
            result = self._error(base, "MODEL_ERROR", error)
        result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return result

    def _validate(self, request: ForecastRequest) -> None:
        if not request.property_id.strip():
            raise ValueError("property_id is required")
        if request.feature_set_version != self.feature_set_version:
            raise ValueError("feature_set_version mismatch")
        if request.input_schema_version != self.input_schema_version:
            raise ValueError("input_schema_version mismatch")
        try:
            feature_date = date.fromisoformat(request.feature_as_of)
        except (TypeError, ValueError) as error:
            raise ValueError("feature_as_of must be ISO date") from error
        if feature_date.isoformat() != self.metadata["as_of_date"]:
            raise ValueError("feature_as_of does not match forecast cutoff")

    def _validate_forecast_rows(self, frame: pd.DataFrame) -> None:
        keys = ["target_date", "room_type_code", "horizon_days"]
        if frame.duplicated(keys).any():
            raise ValueError("forecast features contain duplicate keys")
        expected_room_types = set(
            self.model_bundle["categorical_training_values"]["room_type_code"]
        )
        expected_pairs = {
            (room_type, horizon)
            for room_type in expected_room_types
            for horizon in range(1, 8)
        }
        actual_pairs = set(
            zip(frame["room_type_code"].astype(str), frame["horizon_days"].astype(int))
        )
        if actual_pairs != expected_pairs:
            raise ValueError("forecast features must contain every room type for horizons 1-7")

    def _predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        preprocessor = self.model_bundle["preprocessor"]
        model = self.model_bundle["model"]
        raw = np.asarray(model.predict(preprocessor.transform(frame[FEATURES])), dtype=float)
        clipped = apply_capacity_clip(raw, frame["available_room_nights"])
        matched = frame[["room_type_code", "horizon_days", "available_room_nights"]].merge(
            self.margins,
            on=["room_type_code", "horizon_days"],
            how="left",
            validate="many_to_one",
            sort=False,
        )
        if matched["margin_rooms"].isna().any():
            raise ValueError("prediction interval margin missing")
        margin = matched["margin_rooms"].to_numpy(dtype=float)
        capacity = matched["available_room_nights"].to_numpy(dtype=float)
        output = frame[["target_date", "room_type_code", "horizon_days", "available_room_nights"]].copy()
        output["predicted_rooms_sold"] = clipped
        output["prediction_lower_rooms_sold"] = np.maximum(
            np.floor(clipped - margin), 0
        ).astype(int)
        output["prediction_upper_rooms_sold"] = np.minimum(
            np.ceil(clipped + margin), capacity
        ).astype(int)
        warnings = [self._range_warnings(row) for _, row in frame.iterrows()]
        output["input_range_warning"] = [bool(value) for value in warnings]
        output["out_of_range_features"] = [",".join(value) for value in warnings]
        return output

    def _range_warnings(self, row: pd.Series) -> list[str]:
        ranges = self.model_bundle["numeric_training_ranges"]
        return [
            feature
            for feature in NUMERIC_FEATURES
            if float(row[feature]) < float(ranges[feature]["min"])
            or float(row[feature]) > float(ranges[feature]["max"])
        ]

    @staticmethod
    def _error(base: dict, status: str, error: Exception) -> dict:
        return {
            **base,
            "forecast_status": status,
            "forecast_days": 7,
            "forecast_row_count": 0,
            "predictions": [],
            "error_message": {
                "FEATURE_NOT_FOUND": "requested forecast features were not found",
                "INVALID_INPUT": "request input or forecast feature set is invalid",
                "MODEL_ERROR": "model execution failed",
            }.get(status, "model execution failed"),
            "is_synthetic": True,
            "display_label": "모델 예측 오류",
        }
