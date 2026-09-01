"""운영형 HGBR 후보 선택·구간 보정·객실유형 승인 범위를 학습한다."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .operational_contracts import (
    EXPLAINABLE_FEATURES,
    OPERATIONAL_FEATURE_COLUMNS,
    OPERATIONAL_MODEL_VERSION,
)
from .operational_evaluation import evaluate_operational_model
from .operational_modeling import OperationalDemandModel, build_operational_pipeline


CANDIDATES = (
    {
        "name": "balanced_leaf31",
        "loss": "squared_error",
        "learning_rate": 0.045,
        "max_iter": 420,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 30,
        "l2_regularization": 1.5,
        "random_state": 20260901,
    },
    {
        "name": "robust_leaf31",
        "loss": "absolute_error",
        "learning_rate": 0.04,
        "max_iter": 460,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 35,
        "l2_regularization": 2.0,
        "random_state": 20260901,
    },
    {
        "name": "detailed_leaf63",
        "loss": "squared_error",
        "learning_rate": 0.035,
        "max_iter": 500,
        "max_leaf_nodes": 63,
        "min_samples_leaf": 25,
        "l2_regularization": 2.5,
        "random_state": 20260901,
    },
)


def sha256(path: Path) -> str:
    """모델 파일의 고정 배포 식별용 SHA-256을 계산한다."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class OperationalTrainer:
    """후보를 시간 분리 검증하고 불확실성과 승인 가능한 세그먼트를 고정한다."""

    def __init__(
        self,
        feature_columns: list[str] | None = None,
        model_version: str = OPERATIONAL_MODEL_VERSION,
    ) -> None:
        self.feature_columns = list(feature_columns or OPERATIONAL_FEATURE_COLUMNS)
        self.model_version = model_version

    @staticmethod
    def _target(frame: pd.DataFrame) -> np.ndarray:
        return frame["target_occupancy_rate"].astype(float).to_numpy()

    def fit_candidate(
        self,
        frame: pd.DataFrame,
        config: dict[str, Any],
    ) -> OperationalDemandModel:
        """지정 설정으로 객실 점유율 후보 모델 하나를 학습한다."""

        pipeline = build_operational_pipeline(config, self.feature_columns)
        pipeline.fit(frame[self.feature_columns], self._target(frame))
        return OperationalDemandModel(
            pipeline=pipeline,
            model_version=self.model_version,
            feature_columns=self.feature_columns,
        )

    @staticmethod
    def _selection_score(report: dict[str, Any]) -> float:
        high = report["worst_high_volume_room_type_wape"] or 0.0
        low = report["worst_low_volume_room_type_mae"] or 0.0
        return float(
            report["metrics"]["wape"]
            + 0.15 * high
            + 0.01 * low
            + (0.05 if not report["all_horizons_better_than_baseline"] else 0.0)
            + (0.05 if not report["all_properties_better_than_baseline"] else 0.0)
        )

    def select(
        self,
        train: pd.DataFrame,
        validation: pd.DataFrame,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """시간 분리 검증 점수가 가장 낮은 후보와 전체 시험 결과를 반환한다."""

        trials = []
        for config in CANDIDATES:
            model = self.fit_candidate(train, config)
            report, _ = evaluate_operational_model(model, validation)
            trials.append(
                {
                    "config": config,
                    "score": self._selection_score(report),
                    "report": report,
                }
            )
        return min(trials, key=lambda item: item["score"]), trials

    @staticmethod
    def calibrate_intervals(
        model: OperationalDemandModel,
        validation: pd.DataFrame,
    ) -> dict[int, dict[str, float]]:
        """검증 잔차로 예측 기간별 80%·95% 오차 범위를 보정한다."""

        prediction = model.predict(validation)
        actual = validation["target_rooms_sold"].astype(float).to_numpy()
        residual = np.abs(actual - prediction)
        calibrated = validation[["horizon_days"]].copy()
        calibrated["absolute_error"] = residual
        return {
            int(horizon): {
                "q80": float(np.quantile(group["absolute_error"], 0.80)),
                "q95": float(np.quantile(group["absolute_error"], 0.95)),
            }
            for horizon, group in calibrated.groupby("horizon_days", sort=True)
        }

    @staticmethod
    def quality_scope(groups: dict[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
        """객실 유형별 오차·기준선 조건을 적용해 승인 범위를 만든다."""

        scope = {}
        for row in groups["room_type"].to_dict(orient="records"):
            high_volume = float(row["actual_mean"]) >= 10.0
            threshold_pass = (
                float(row["wape"]) <= 0.30
                if high_volume
                else float(row["mae"]) <= 3.0
            )
            key = f"{row['property_id']}|{row['room_type_code']}"
            scope[key] = {
                "status": (
                    "APPROVED"
                    if bool(row["better_than_baseline"]) and threshold_pass
                    else "NOT_APPROVED"
                ),
                "volume_class": "HIGH" if high_volume else "LOW",
                "wape": float(row["wape"]),
                "mae": float(row["mae"]),
                "baseline_wape": float(row["baseline_wape"]),
                "baseline_mae": float(row["baseline_mae"]),
            }
        return scope

    def fit_final(
        self,
        train: pd.DataFrame,
        validation: pd.DataFrame,
        selected: dict[str, Any],
    ) -> tuple[OperationalDemandModel, dict[str, Any]]:
        """선정 후보를 재학습하고 범위·영향 기준·유형별 승인을 결합한다."""

        calibration_model = self.fit_candidate(train, selected["config"])
        intervals = self.calibrate_intervals(calibration_model, validation)
        validation_report, validation_groups = evaluate_operational_model(
            calibration_model, validation
        )
        combined = pd.concat([train, validation], ignore_index=True)
        final = self.fit_candidate(combined, selected["config"])
        final.interval_quantiles = intervals
        final.reference_values = {
            feature: float(combined[feature].median())
            for feature in EXPLAINABLE_FEATURES
            if feature in self.feature_columns
        }
        final.quality_scope = self.quality_scope(validation_groups)
        return final, validation_report


def main() -> None:
    """학습·검증 자료에서 최종 후보와 선택 증거를 저장한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    args = parser.parse_args()
    parse_dates = ["cutoff_date", "target_date"]
    train = pd.read_csv(args.train, parse_dates=parse_dates)
    validation = pd.read_csv(args.validation, parse_dates=parse_dates)
    trainer = OperationalTrainer()
    selected, trials = trainer.select(train, validation)
    model, validation_report = trainer.fit_final(train, validation, selected)
    args.artifact_dir.mkdir(parents=True, exist_ok=False)
    model_path = args.artifact_dir / "model.joblib"
    joblib.dump(model, model_path)
    dataset = json.loads(args.dataset_manifest.read_text(encoding="utf-8"))
    manifest = {
        "model_version": OPERATIONAL_MODEL_VERSION,
        "model_type": "operational-point-in-time-hgbr",
        "feature_profile": "point_in_time_demand_v1",
        "max_horizon": 7,
        "feature_columns": model.selected_feature_columns(),
        "selected_config": selected["config"],
        "validation": validation_report,
        "quality_scope": model.quality_scope,
        "interval_quantiles": model.interval_quantiles,
        "training_rows": int(len(train) + len(validation)),
        "source_dataset_sha256": dataset["source_sha256"],
        "signal_dataset_sha256": dataset["signal_sha256"],
        "artifact_sha256": sha256(model_path),
        "synthetic_training_data": bool(dataset["synthetic_only"]),
        "production_approved": False,
    }
    for name, payload in {
        "model_manifest.json": manifest,
        "selection_trials.json": trials,
    }.items():
        (args.artifact_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
