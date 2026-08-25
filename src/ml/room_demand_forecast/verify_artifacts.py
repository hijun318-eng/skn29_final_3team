from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd


class ArtifactVerifier:
    REQUIRED = {
        "data_quality_checks.csv",
        "validation_metrics.csv",
        "validation_group_metrics.csv",
        "model_selection.json",
        "test_metrics.csv",
        "test_group_metrics.csv",
        "test_predictions.csv",
        "forecast_predictions.csv",
        "feature_importance.csv",
        "room_demand_feature_contract.json",
        "room_demand_model_metadata.json",
        "room_demand_model.joblib",
        "prediction_interval_metrics.json",
        "prediction_interval_margins.csv",
        "feature_ablation_metrics.csv",
        "feature_range_audit.csv",
        "hidden_qa_audit.json",
        "input_file_hashes.csv",
        "risk_audit_summary.json",
        "risk_register.csv",
    }

    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = artifact_dir

    def verify(self) -> dict[str, object]:
        missing = sorted(name for name in self.REQUIRED if not (self.artifact_dir / name).is_file())
        if missing:
            raise FileNotFoundError(f"산출물 누락: {missing}")

        quality = pd.read_csv(self.artifact_dir / "data_quality_checks.csv")
        failed_checks = quality.loc[quality["status"].ne("PASS"), "check"].tolist()
        if failed_checks:
            raise ValueError(f"데이터 품질검사 실패: {failed_checks}")

        selection = self._read_json("model_selection.json")
        if selection["status"] != "PASS":
            raise ValueError("모델 선정 상태가 PASS가 아닙니다.")

        test_predictions = pd.read_csv(self.artifact_dir / "test_predictions.csv")
        forecast = pd.read_csv(self.artifact_dir / "forecast_predictions.csv")
        invalid_test = int(
            (
                (test_predictions["predicted_rooms_sold"] < 0)
                | (test_predictions["predicted_rooms_sold"] > test_predictions["available_room_nights"])
            ).sum()
        )
        invalid_forecast = int(
            (
                (forecast["predicted_rooms_sold"] < 0)
                | (forecast["predicted_rooms_sold"] > forecast["available_room_nights"])
            ).sum()
        )
        if invalid_test or invalid_forecast:
            raise ValueError(f"예측 범위 위반: test={invalid_test}, forecast={invalid_forecast}")
        if len(forecast) != 28 or set(forecast["prediction_cutoff_date"]) != {"2026-07-28"}:
            raise ValueError("현재 기준 FORECAST는 cutoff 2026-07-28의 28행이어야 합니다.")

        interval_columns = {
            "prediction_lower_rooms_sold",
            "prediction_upper_rooms_sold",
        }
        for name, frame in (("test", test_predictions), ("forecast", forecast)):
            if not interval_columns.issubset(frame.columns):
                raise ValueError(f"{name}: 예측구간 컬럼이 없습니다.")
            invalid_interval = int(
                (
                    (frame["prediction_lower_rooms_sold"] < 0)
                    | (frame["prediction_lower_rooms_sold"] > frame["predicted_rooms_sold"])
                    | (frame["prediction_upper_rooms_sold"] < frame["predicted_rooms_sold"])
                    | (frame["prediction_upper_rooms_sold"] > frame["available_room_nights"])
                ).sum()
            )
            if invalid_interval:
                raise ValueError(f"{name}: 잘못된 예측구간 {invalid_interval}건")

        interval_metrics = self._read_json("prediction_interval_metrics.json")
        if interval_metrics["actual_coverage"] < 0.90:
            raise ValueError("TEST 예측구간 포함률이 최소 기준 90%보다 낮습니다.")

        contract = self._read_json("room_demand_feature_contract.json")
        metadata = self._read_json("room_demand_model_metadata.json")
        model_bundle = joblib.load(self.artifact_dir / "room_demand_model.joblib")
        if contract["feature_count"] != 26 or contract["hidden_qa_used"] is not False:
            raise ValueError("Feature 또는 숨은 QA 사용 계약이 올바르지 않습니다.")
        if model_bundle["model_name"] != metadata["model_name"]:
            raise ValueError("저장 모델과 메타데이터의 모델명이 다릅니다.")
        if not model_bundle.get("numeric_training_ranges"):
            raise ValueError("저장 모델에 학습 범위 계약이 없습니다.")
        if not model_bundle.get("critical_runtime_features"):
            raise ValueError("저장 모델에 필수 실시간 Feature 계약이 없습니다.")
        if not {"input_range_warning", "out_of_range_features"}.issubset(forecast.columns):
            raise ValueError("FORECAST에 입력 범위 경고가 없습니다.")
        warning_without_feature = forecast[
            forecast["input_range_warning"]
            & forecast["out_of_range_features"].fillna("").eq("")
        ]
        if not warning_without_feature.empty:
            raise ValueError("입력 범위 경고의 Feature 근거가 누락됐습니다.")

        hidden_audit = self._read_json("hidden_qa_audit.json")
        if hidden_audit["model_selection_use"] is not False:
            raise ValueError("숨은 QA 정답이 모델 선정에 사용된 것으로 기록됐습니다.")
        risk_summary = self._read_json("risk_audit_summary.json")
        if risk_summary["time_contract"]["status"] != "PASS":
            raise ValueError("Point-in-time 계약검사가 실패했습니다.")

        result = {
            "status": "PASS",
            "quality_checks": len(quality),
            "selected_model": metadata["model_name"],
            "test_rows": len(test_predictions),
            "forecast_rows": len(forecast),
            "feature_count": contract["feature_count"],
            "model_load": "PASS",
            "prediction_interval_coverage": interval_metrics["actual_coverage"],
            "hidden_qa_wape": hidden_audit["wape"],
            "risk_status": risk_summary["status"],
        }
        (self.artifact_dir / "verification_summary.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result

    def _read_json(self, name: str) -> dict:
        return json.loads((self.artifact_dir / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    result = ArtifactVerifier(Path(__file__).resolve().parent / "artifacts").verify()
    print(json.dumps(result, ensure_ascii=False, indent=2))
