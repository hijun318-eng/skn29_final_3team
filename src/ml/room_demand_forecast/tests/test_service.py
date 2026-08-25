from __future__ import annotations

import unittest
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from room_demand_ml.config import DEFAULT_FORECAST_FIXTURE, DEFAULT_OUTPUT_DIR
from room_demand_ml.service import ForecastRequest, RoomDemandForecastService


class RoomDemandForecastServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RoomDemandForecastService(
            forecast_path=DEFAULT_FORECAST_FIXTURE
        )
        self.request = ForecastRequest(
            property_id="SYNTHETIC_HOTEL_001",
            feature_as_of="2026-07-28",
            feature_set_version=self.service.feature_set_version,
            input_schema_version=self.service.input_schema_version,
        )

    def test_success_returns_7_days_and_28_rows(self) -> None:
        result = self.service.execute(self.request)
        self.assertEqual("SUCCESS", result["forecast_status"])
        self.assertEqual(7, result["forecast_days"])
        self.assertEqual(28, result["forecast_row_count"])
        self.assertTrue(result["is_synthetic"])
        expected = pd.read_csv(DEFAULT_OUTPUT_DIR / "forecast_predictions.csv")
        actual = [row["predicted_rooms_sold"] for row in result["predictions"]]
        expected_values = (
            expected.sort_values(["target_date", "room_type_code"])[
                "predicted_rooms_sold"
            ]
            .astype(int)
            .tolist()
        )
        self.assertEqual(expected_values, actual)

    def test_packaged_fixture_is_usable(self) -> None:
        result = RoomDemandForecastService(
            forecast_path=DEFAULT_FORECAST_FIXTURE
        ).execute(self.request)
        self.assertEqual("SUCCESS", result["forecast_status"])
        self.assertEqual(28, result["forecast_row_count"])

    def test_unknown_property_is_explicit(self) -> None:
        request = ForecastRequest(**{**self.request.__dict__, "property_id": "UNKNOWN"})
        self.assertEqual("FEATURE_NOT_FOUND", self.service.execute(request)["forecast_status"])

    def test_cutoff_mismatch_is_rejected(self) -> None:
        request = ForecastRequest(**{**self.request.__dict__, "feature_as_of": "2026-07-27"})
        self.assertEqual("INVALID_INPUT", self.service.execute(request)["forecast_status"])

    def test_schema_mismatch_is_rejected(self) -> None:
        request = ForecastRequest(
            **{**self.request.__dict__, "input_schema_version": "wrong"}
        )
        self.assertEqual("INVALID_INPUT", self.service.execute(request)["forecast_status"])

    def test_timestamp_is_not_accepted_as_feature_date(self) -> None:
        request = ForecastRequest(
            **{**self.request.__dict__, "feature_as_of": "2026-07-28T00:00:00"}
        )
        self.assertEqual("INVALID_INPUT", self.service.execute(request)["forecast_status"])

    def test_incomplete_forecast_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "incomplete.csv"
            pd.read_csv(DEFAULT_FORECAST_FIXTURE).iloc[:-1].to_csv(path, index=False)
            result = RoomDemandForecastService(forecast_path=path).execute(self.request)
        self.assertEqual("INVALID_INPUT", result["forecast_status"])

    def test_duplicate_forecast_key_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.csv"
            frame = pd.read_csv(DEFAULT_FORECAST_FIXTURE)
            pd.concat([frame, frame.iloc[[0]]], ignore_index=True).to_csv(path, index=False)
            result = RoomDemandForecastService(forecast_path=path).execute(self.request)
        self.assertEqual("INVALID_INPUT", result["forecast_status"])

    def test_model_artifact_hash_mismatch_stops_startup(self) -> None:
        with TemporaryDirectory() as directory:
            artifact_dir = Path(directory)
            metadata = json.loads(
                (DEFAULT_OUTPUT_DIR / "room_demand_model_metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            metadata["model_sha256"] = "0" * 64
            (artifact_dir / "room_demand_model_metadata.json").write_text(
                json.dumps(metadata), encoding="utf-8"
            )
            shutil.copy2(
                DEFAULT_OUTPUT_DIR / "room_demand_model.joblib",
                artifact_dir / "room_demand_model.joblib",
            )
            with self.assertRaisesRegex(RuntimeError, "integrity check failed"):
                RoomDemandForecastService(artifact_dir=artifact_dir)


if __name__ == "__main__":
    unittest.main()
