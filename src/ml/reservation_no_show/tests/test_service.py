from __future__ import annotations

import unittest
import json
import shutil
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from no_show_ml.config import ProjectConfig
from no_show_ml.service import NoShowToolService, ToolRequest


class NoShowToolServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = ProjectConfig.default()
        cls.service = NoShowToolService(cls.config)
        frame = pd.read_csv(cls.config.inference_csv, low_memory=False)
        cls.row = frame.iloc[0]
        cls.feature_as_of = pd.Timestamp(
            cls.row["prediction_cutoff_at"]
        ).tz_localize("Asia/Seoul").isoformat()

    def request(self, **changes) -> ToolRequest:
        values = {
            "reservation_id": str(self.row["reservation_id"]),
            "feature_as_of": self.feature_as_of,
            "feature_set_version": self.config.feature_set_version,
            "input_schema_version": self.service.input_schema_version,
        }
        values.update(changes)
        return ToolRequest(**values)

    def test_success_contract(self) -> None:
        result = self.service.execute(self.request())
        self.assertEqual("SUCCESS", result["prediction_status"])
        self.assertIn(result["risk_level"], ["LOW", "HIGH"])
        self.assertEqual("TOP_15_PERCENT_DAILY_COHORT", result["ranking_policy"])
        self.assertGreater(result["risk_rank"], 0)
        self.assertLessEqual(result["risk_rank"], result["cohort_size"])
        self.assertTrue(result["is_synthetic"])
        self.assertIn("모델 예측", result["display_label"])
        self.assertTrue(result["execution_id"].startswith("mlrun-"))

    def test_packaged_fixture_is_usable(self) -> None:
        fixture = self.config.project_dir / "fixtures" / "reservation_no_show_inference.csv"
        result = NoShowToolService(self.config, fixture).execute(self.request())
        self.assertEqual("SUCCESS", result["prediction_status"])

    def test_same_fixture_has_same_probability(self) -> None:
        first = self.service.execute(self.request())
        second = self.service.execute(self.request())
        self.assertEqual(first["no_show_probability"], second["no_show_probability"])
        self.assertNotEqual(first["execution_id"], second["execution_id"])

    def test_feature_not_found(self) -> None:
        result = self.service.execute(self.request(reservation_id="RES-NOT-FOUND"))
        self.assertEqual("FEATURE_NOT_FOUND", result["prediction_status"])
        self.assertIsNone(result["no_show_probability"])

    def test_feature_version_mismatch(self) -> None:
        result = self.service.execute(
            self.request(feature_set_version="invalid-feature-version")
        )
        self.assertEqual("SCHEMA_MISMATCH", result["prediction_status"])

    def test_input_schema_version_mismatch(self) -> None:
        result = self.service.execute(
            self.request(input_schema_version="invalid-input-version")
        )
        self.assertEqual("SCHEMA_MISMATCH", result["prediction_status"])

    def test_feature_cutoff_mismatch(self) -> None:
        result = self.service.execute(
            self.request(feature_as_of="2026-01-01T18:00:00+09:00")
        )
        self.assertEqual("INVALID_INPUT", result["prediction_status"])

    def test_invalid_timestamp(self) -> None:
        result = self.service.execute(self.request(feature_as_of="not-a-timestamp"))
        self.assertEqual("INVALID_INPUT", result["prediction_status"])

    def test_timezone_is_required(self) -> None:
        result = self.service.execute(
            self.request(feature_as_of=str(self.row["prediction_cutoff_at"]))
        )
        self.assertEqual("INVALID_INPUT", result["prediction_status"])

    def test_duplicate_reservation_feature_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            frame = pd.read_csv(self.config.inference_csv, low_memory=False)
            duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
            path = Path(directory) / "duplicate.csv"
            duplicate.to_csv(path, index=False)
            result = NoShowToolService(self.config, path).execute(self.request())
        self.assertEqual("INVALID_INPUT", result["prediction_status"])
        self.assertNotIn("unique", result["error_message"])

    def test_missing_feature_column_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            frame = pd.read_csv(self.config.inference_csv, low_memory=False).drop(
                columns=["lead_time_days"]
            )
            path = Path(directory) / "missing.csv"
            frame.to_csv(path, index=False)
            result = NoShowToolService(self.config, path).execute(self.request())
        self.assertEqual("INVALID_INPUT", result["prediction_status"])

    def test_null_feature_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            frame = pd.read_csv(self.config.inference_csv, low_memory=False)
            frame.loc[0, "lead_time_days"] = None
            path = Path(directory) / "null.csv"
            frame.to_csv(path, index=False)
            result = NoShowToolService(self.config, path).execute(self.request())
        self.assertEqual("INVALID_INPUT", result["prediction_status"])

    def test_daily_ranking_artifact_is_consistent(self) -> None:
        ranking = pd.read_csv(
            self.config.artifacts_dir / "inference_predictions.csv", low_memory=False
        )
        for _, cohort in ranking.groupby("prediction_cutoff_at"):
            expected_high = -(-len(cohort) * 15 // 100)
            self.assertEqual(len(cohort), int(cohort["cohort_size"].iloc[0]))
            self.assertEqual(expected_high, int(cohort["priority_flag"].sum()))
            self.assertEqual(set(range(1, len(cohort) + 1)), set(cohort["risk_rank"]))

    def test_onnx_artifact_hash_mismatch_stops_startup(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_dir = root / "artifacts"
            model_dir = artifact_dir / "models"
            model_dir.mkdir(parents=True)
            metadata = json.loads(
                (self.config.artifacts_dir / "model_metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            metadata["onnx_sha256"] = "0" * 64
            (artifact_dir / "model_metadata.json").write_text(
                json.dumps(metadata), encoding="utf-8"
            )
            shutil.copy2(
                self.config.model_dir / "reservation_no_show_model.onnx",
                model_dir / "reservation_no_show_model.onnx",
            )
            broken = replace(
                self.config, artifacts_dir=artifact_dir, model_dir=model_dir
            )
            with self.assertRaisesRegex(RuntimeError, "integrity check failed"):
                NoShowToolService(broken)


if __name__ == "__main__":
    unittest.main()
