from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .contracts import FEATURE_COLUMNS, MODEL_VERSION
from .evaluation_metrics import evaluate_model, selection_score
from .modeling import TimeSeriesDemandModel, build_pipeline


CANDIDATES = (
    {
        "name": "global_residual_4w_squared_leaf31",
        "scope": "global",
        "loss": "squared_error",
        "target_mode": "residual_rate",
        "learning_rate": 0.045,
        "max_iter": 360,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 40,
        "l2_regularization": 2.0,
        "random_state": 20260826,
    },
    {
        "name": "horizon_residual_12w_squared_leaf31",
        "scope": "horizon",
        "loss": "squared_error",
        "target_mode": "residual_rate_12w",
        "learning_rate": 0.04,
        "max_iter": 360,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 25,
        "l2_regularization": 1.0,
        "random_state": 20260826,
    },
    {
        "name": "property_horizon_residual_12w_squared_leaf15",
        "scope": "property_horizon",
        "loss": "squared_error",
        "target_mode": "residual_rate_12w",
        "learning_rate": 0.04,
        "max_iter": 360,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 15,
        "l2_regularization": 1.0,
        "random_state": 20260826,
    },
    {
        "name": "horizon_rooms_poisson_leaf31",
        "scope": "horizon",
        "loss": "poisson",
        "target_mode": "rooms_sold",
        "learning_rate": 0.04,
        "max_iter": 420,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 25,
        "l2_regularization": 1.0,
        "random_state": 20260826,
    },
)
BLEND_WEIGHTS = (0.5, 0.75, 1.0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TimeSeriesTrainer:
    @staticmethod
    def target_values(frame: pd.DataFrame, target_mode: str) -> np.ndarray:
        target = frame["target_rooms_sold"].astype(float).to_numpy()
        if target_mode == "occupancy_rate":
            return frame["target_occupancy_rate"].astype(float).to_numpy()
        if target_mode == "log_rooms_sold":
            return np.log1p(target)
        if target_mode in {"residual_rate", "residual_rate_12w"}:
            baseline_column = (
                "same_weekday_mean_12w"
                if target_mode == "residual_rate_12w"
                else "same_weekday_mean_4w"
            )
            return (
                target - frame[baseline_column].astype(float).to_numpy()
            ) / frame["physical_rooms"].astype(float).to_numpy()
        return target

    @staticmethod
    def validation_halves(
        validation: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        calibration = validation.loc[
            validation["cutoff_date"] <= pd.Timestamp("2024-06-30")
        ].copy()
        selection = validation.loc[
            validation["cutoff_date"] > pd.Timestamp("2024-06-30")
        ].copy()
        if calibration.empty or selection.empty:
            raise ValueError("validation calibration/selection split is empty")
        return calibration, selection

    @staticmethod
    def calibrate_offsets(
        model: TimeSeriesDemandModel,
        frame: pd.DataFrame,
    ) -> dict[str, float]:
        prediction = model.predict_raw(frame)
        residuals = frame[["property_id", "room_type_code"]].copy()
        residuals["residual"] = (
            frame["target_rooms_sold"].astype(float).to_numpy() - prediction
        )
        offsets = {}
        for keys, subset in residuals.groupby(
            ["property_id", "room_type_code"], sort=True
        ):
            key = TimeSeriesDemandModel.series_key(*keys)
            offsets[key] = float(subset["residual"].median())
        return offsets

    def fit_candidate(
        self,
        frame: pd.DataFrame,
        config: dict[str, Any],
    ) -> TimeSeriesDemandModel:
        target = self.target_values(frame, str(config["target_mode"]))
        if config["scope"] == "global":
            pipeline = build_pipeline(config)
            pipeline.fit(frame[FEATURE_COLUMNS], target)
            return TimeSeriesDemandModel(
                pipeline=pipeline,
                blend_weight=1.0,
                model_version=MODEL_VERSION,
                target_mode=str(config["target_mode"]),
            )
        pipelines = {}
        group_columns = {
            "series": ["property_id", "room_type_code"],
            "horizon": ["horizon_days"],
            "property_horizon": ["property_id", "horizon_days"],
        }[str(config["scope"])]
        for keys, subset in frame.groupby(group_columns, sort=False):
            pipeline = build_pipeline(config)
            target = self.target_values(subset, str(config["target_mode"]))
            pipeline.fit(subset[FEATURE_COLUMNS], target)
            key = TimeSeriesDemandModel.group_key(keys)
            pipelines[key] = pipeline
        return TimeSeriesDemandModel(
            pipeline=None,
            pipelines=pipelines,
            target_mode=str(config["target_mode"]),
            blend_weight=1.0,
            model_version=MODEL_VERSION,
            pipeline_scope=str(config["scope"]),
        )

    def select(
        self,
        train: pd.DataFrame,
        validation: pd.DataFrame,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        trials: list[dict[str, Any]] = []
        for config in CANDIDATES:
            candidate = self.fit_candidate(train, config)
            for weight in BLEND_WEIGHTS:
                model = TimeSeriesDemandModel(
                    pipeline=candidate.pipeline,
                    pipelines=candidate.pipelines,
                    target_mode=candidate.target_mode,
                    blend_weight=weight,
                    model_version=MODEL_VERSION,
                    pipeline_scope=candidate.pipeline_scope,
                )
                report, _ = evaluate_model(model, validation)
                trials.append(
                    {
                        "config": config,
                        "blend_weight": weight,
                        "selection_score": selection_score(report),
                        "report": report,
                    }
                )
        selected = min(trials, key=lambda trial: trial["selection_score"])
        return selected, trials

    def fit_final(
        self,
        train: pd.DataFrame,
        validation: pd.DataFrame,
        selected: dict[str, Any],
    ) -> TimeSeriesDemandModel:
        combined = pd.concat([train, validation], ignore_index=True)
        model = self.fit_candidate(combined, selected["config"])
        model.blend_weight = float(selected["blend_weight"])
        return model


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trainer-dir", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    args = parser.parse_args()

    train = pd.read_csv(
        args.trainer_dir / "train.csv.gz",
        parse_dates=["cutoff_date", "target_date"],
    )
    validation = pd.read_csv(
        args.trainer_dir / "validation.csv.gz",
        parse_dates=["cutoff_date", "target_date"],
    )
    trainer = TimeSeriesTrainer()
    selected, trials = trainer.select(train, validation)
    model = trainer.fit_final(train, validation, selected)
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.artifact_dir / "model.joblib"
    joblib.dump(model, model_path)
    dataset_manifest = json.loads(
        args.dataset_manifest.read_text(encoding="utf-8")
    )
    manifest = {
        "model_version": MODEL_VERSION,
        "model_type": "historical-only-direct-multi-horizon-hgbr",
        "max_horizon": 10,
        "feature_columns": FEATURE_COLUMNS,
        "selected_config": selected["config"],
        "blend_weight": selected["blend_weight"],
        "validation_selection": selected["report"],
        "training_rows": int(len(train) + len(validation)),
        "training_splits": ["TRAIN", "VALIDATION"],
        "selection_splits": ["TRAIN", "VALIDATION"],
        "selection_metric": "ROLLING_ORIGIN_VALIDATION_WAPE",
        "trainer_input_files": sorted(
            path.name for path in args.trainer_dir.iterdir() if path.is_file()
        ),
        "test_input_paths_exposed": False,
        "test_seen_by_trainer": False,
        "september_observed_values_used": False,
        "source_dataset_sha256": dataset_manifest["source_sha256"],
        "dataset_file_sha256": dataset_manifest["file_sha256"],
        "artifact_sha256": sha256(model_path),
        "synthetic_training_data": dataset_manifest["source_audit"][
            "synthetic_only"
        ],
    }
    (args.artifact_dir / "model_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.artifact_dir / "selection_trials.json").write_text(
        json.dumps(trials, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
