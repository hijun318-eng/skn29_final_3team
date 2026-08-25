from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .config import CATEGORICAL_FEATURES, CRITICAL_RUNTIME_FEATURES, FEATURES, KEY_COLUMNS, LABEL, NUMERIC_FEATURES, REPOSITORY_DIR, SEED
from .data import DataContractValidator, DatasetRepository
from .metrics import apply_capacity_clip, build_actual_lookup, grouped_metrics, metric_record, seasonal_naive
from .modeling import ModelRun, ModelTrainer
from .uncertainty import PredictionIntervalCalibrator


@dataclass(frozen=True)
class PipelineOptions:
    data_dir: Path
    output_dir: Path
    as_of_date: str = "2026-07-28"
    n_estimators: int = 3000
    early_stopping_rounds: int = 100
    validate_only: bool = False
    phase: str = "all"
    protocol_version: str = "v2"
    source_snapshot_id: str | None = None


class RoomDemandPipeline:
    def __init__(self, options: PipelineOptions) -> None:
        self.options = options

    def run(self) -> dict[str, Any]:
        output = self.options.output_dir
        output.mkdir(parents=True, exist_ok=True)

        self.bundle = DatasetRepository(self.options.data_dir).load()
        self.preprocessor = ModelTrainer.make_preprocessor()
        self.validation_summary = self._run_data_contract_validation()

        self.x_train = self.preprocessor.fit_transform(self.bundle.train[FEATURES])
        self.y_train = self.bundle.train[LABEL].to_numpy(float)

        self.x_validation = self.preprocessor.transform(self.bundle.validation[FEATURES])
        self.y_validation = self.bundle.validation[LABEL].to_numpy(float)

        self.x_test = self.preprocessor.transform(self.bundle.test[FEATURES])
        self.y_test = self.bundle.test[LABEL].to_numpy(float)

        if self.options.validate_only:
            return {
                "status": "VALIDATE_ONLY",
                "phase": "validate-only",
                "protocol_version": self.options.protocol_version,
                "validation_only": True,
                "artifacts_dir": str(output),
                "validation_contract": self.validation_summary,
            }

        phase = self.options.phase
        if phase in ("baseline", "all"):
            self._run_baseline()

        if phase in ("tune", "all"):
            self._run_tune()

        if phase in ("finalize", "all"):
            self._run_finalize()

        if phase in ("test", "all"):
            self.metadata = self._run_test()
        else:
            self.metadata = {}

        return {
            "status": "COMPLETED",
            "phase": phase,
            "protocol_version": self.options.protocol_version,
            "artifacts_dir": str(output),
            "metadata": self.metadata
        }

    def _run_data_contract_validation(self) -> dict[str, Any]:
        output = self.options.output_dir
        validator = DataContractValidator()
        checks = validator.validate(self.bundle)
        quality = validator.to_frame(checks)
        quality.to_csv(output / "data_quality_checks.csv", index=False)

        pass_count = int((quality["status"] == "PASS").sum())
        fail_count = int((quality["status"] == "FAIL").sum())
        fail_critical = int(((quality["status"] == "FAIL") & (quality["severity"] == "Critical")).sum())
        summary = {
            "status": "PASS" if fail_count == 0 else "FAIL",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "check_count": int(len(quality)),
            "pass_count": pass_count,
            "fail_count": fail_count,
            "critical_fail_count": int(fail_critical),
            "validation_only": self.options.validate_only,
            "phase": self.options.phase,
        }
        self._save_json(output / "data_contract_summary.json", summary)
        self._save_profile(self.bundle, checks)
        return summary

    def _run_baseline(self):
        output = self.options.output_dir
        trainer = ModelTrainer(self.options.n_estimators, self.options.early_stopping_rounds)

        runs = trainer.train(self.x_train, self.y_train, self.x_validation, self.y_validation)
        validation_history = build_actual_lookup(self.bundle.train, self.bundle.validation)
        baseline_raw = seasonal_naive(self.bundle.validation, validation_history)
        validation_predictions = {run.name: np.asarray(run.model.predict(self.x_validation), dtype=float) for run in runs}

        validation_metrics, validation_groups = self._evaluate_candidates(
            self.bundle.validation, self.y_validation, baseline_raw, validation_predictions, runs, "VALIDATION"
        )

        validation_metrics.to_csv(output / "baseline_candidate_metrics.csv", index=False)
        pd.DataFrame(validation_groups).to_csv(output / "validation_group_metrics.csv", index=False)

        names = [run.name for run in runs]
        with open(output / "top2_selection.json", "w", encoding="utf-8") as f:
            json.dump({
                "top2_names": names,
                "selection_reason": "Top 2 models evaluated from trainer"
            }, f, indent=2)

    def _run_tune(self):
        output = self.options.output_dir
        top2_data = self._load_top2_candidates()
        trials: list[dict[str, Any]] = []
        trainer = ModelTrainer(self.options.n_estimators, self.options.early_stopping_rounds)

        for candidate_name in top2_data:
            for index, params in enumerate(self._tuning_param_sets(candidate_name), start=1):
                trial_id = f"{candidate_name}:tuned_{index}"
                fit_start = datetime.now(timezone.utc)
                try:
                    model = self._build_tuned_model(candidate_name, params)
                    if candidate_name == "XGBRegressor":
                        model.fit(
                            self.x_train,
                            self.y_train,
                            eval_set=[(self.x_validation, self.y_validation)],
                            verbose=False,
                        )
                        best_iteration = int(getattr(model, "best_iteration", 0) or 0)
                    elif candidate_name == "LGBMRegressor":
                        model.fit(
                            self.x_train,
                            self.y_train,
                            eval_set=[(self.x_validation, self.y_validation)],
                            eval_metric="mae",
                            verbose=False,
                        )
                        best_iteration = int(getattr(model, "best_iteration", 0) or 0)
                    else:
                        model.fit(self.x_train, self.y_train)
                        best_iteration = 0

                    elapsed = (datetime.now(timezone.utc) - fit_start).total_seconds()
                    pred_validation_raw = np.asarray(model.predict(self.x_validation), dtype=float)
                    pred_validation_clipped = apply_capacity_clip(
                        pred_validation_raw, self.bundle.validation["available_room_nights"]
                    )
                    metric_record_row = metric_record(
                        candidate_name,
                        "VALIDATION",
                        "clipped",
                        self.y_validation,
                        pred_validation_clipped,
                    )
                    trials.append({
                        "trial_id": trial_id,
                        "model": candidate_name,
                        "configuration": json.dumps(params, sort_keys=True, default=str),
                        "fit_seconds": float(elapsed),
                        "best_iteration": best_iteration,
                        "seed": SEED,
                        "trial_seed": SEED,
                        "split": "VALIDATION",
                        "model_version": "room-demand-regression-v1",
                        "status": "success",
                        "validation_clipped_wape": metric_record_row["wape"],
                        "validation_clipped_mae": metric_record_row["mae"],
                        "validation_clipped_rmse": metric_record_row["rmse"],
                        "validation_clipped_r2": metric_record_row["r2"],
                    })
                except Exception as error:  # pragma: no cover - runtime safety
                    trials.append({
                        "trial_id": trial_id,
                        "model": candidate_name,
                        "configuration": json.dumps(params, sort_keys=True, default=str),
                        "split": "VALIDATION",
                        "status": "failed",
                        "error": str(error),
                    })

        tuning_results = pd.DataFrame(trials)
        tuning_results = tuning_results[tuning_results["status"].eq("success")].copy()
        if tuning_results.empty:
            failure_count = len(trials)
            raise ValueError(f"No successful tuning trial. Failures: {failure_count}")
        tuning_results = tuning_results.sort_values(
            by=["validation_clipped_wape", "validation_clipped_rmse"]
        )
        tuning_results.to_csv(output / "top2_tuning_trials.csv", index=False)
        tuning_results.head(2).to_csv(output / "top2_tuning_trials_summary.csv", index=False)
        self._save_json(
            output / "top2_tuning_summary.json",
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "candidate_count": len(tuning_results),
                "top2_candidates": top2_data,
                "best_trial_id": str(tuning_results.iloc[0]["trial_id"]),
            },
        )

    def _run_finalize(self):
        output = self.options.output_dir
        trials = pd.read_csv(output / "top2_tuning_trials.csv")
        if trials.empty:
            raise ValueError("No tuning trials available for finalize")
        if "status" in trials.columns:
            trials = trials[trials["status"].eq("success")]
        if trials.empty:
            raise ValueError("No successful tuning trials available for finalize")
        ordered = trials.sort_values(
            by=["validation_clipped_wape", "validation_clipped_rmse"], ascending=[True, True]
        )
        best = ordered.iloc[0]
        final_model = str(best["model"])
        with open(output / "final_model_selection.json", "w", encoding="utf-8") as f:
            json.dump({
                "final_model": final_model,
                "selection_reason": "Selected by lowest VALIDATION clipped WAPE",
                "selection_time": datetime.now(timezone.utc).isoformat(),
                "best_trial_id": str(best["trial_id"]),
                "validation_clipped_wape": float(best["validation_clipped_wape"]),
                "validation_clipped_mae": float(best["validation_clipped_mae"]),
                "validation_clipped_r2": float(best["validation_clipped_r2"]),
            }, f, indent=2)

    def _run_test(self):
        output = self.options.output_dir
        with open(output / "final_model_selection.json", "r", encoding="utf-8") as f:
            final = json.load(f)

        final_model = final["final_model"]

        # Refit models from baseline setup to preserve deterministic feature handling.
        trainer = ModelTrainer(self.options.n_estimators, self.options.early_stopping_rounds)
        runs = trainer.train(self.x_train, self.y_train, self.x_validation, self.y_validation)
        selected = next(r for r in runs if r.name == final_model)

        test_history = build_actual_lookup(self.bundle.train, self.bundle.validation, self.bundle.test)
        test_baseline = seasonal_naive(self.bundle.test, test_history)
        test_raw = np.asarray(selected.model.predict(self.x_test), dtype=float)

        validation_raw = np.asarray(selected.model.predict(self.x_validation), dtype=float)
        validation_selected = apply_capacity_clip(validation_raw, self.bundle.validation["available_room_nights"])

        calibrator = PredictionIntervalCalibrator().fit(
            self.bundle.validation, self.y_validation, validation_selected
        )
        test_metrics, test_groups = self._evaluate_selected(
            self.bundle.test, self.y_test, test_baseline, test_raw, selected.name, "TEST"
        )
        test_metrics.to_csv(output / "test_metrics.csv", index=False)
        pd.DataFrame(test_groups).to_csv(output / "test_group_metrics.csv", index=False)

        test_clipped = apply_capacity_clip(test_raw, self.bundle.test["available_room_nights"])
        test_lower, test_upper = calibrator.bounds(self.bundle.test, test_clipped)
        self._save_test_predictions(
            self.bundle.test, selected.name, test_raw, test_clipped, test_lower, test_upper
        )

        interval_evaluation = calibrator.evaluate(self.y_test, test_lower, test_upper)
        interval_payload = interval_evaluation.to_dict()
        self._save_json(output / "prediction_interval_metrics.json", interval_payload)
        calibrator.margins().to_csv(output / "prediction_interval_margins.csv", index=False)

        self._save_model_artifacts(self.bundle, self.preprocessor, selected)

        model_path = output / "room_demand_model.joblib"
        model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()

        forecast_count = self._save_forecast(
            self.bundle.forecast, self.bundle.train, self.preprocessor, selected, calibrator
        )
        metadata = self._metadata(
            self.bundle, selected, forecast_count, interval_payload, model_sha256
        )
        self._save_json(output / "room_demand_model_metadata.json", metadata)
        self._save_json(output / "run_summary.json", metadata)
        return metadata

    def _evaluate_candidates(
        self,
        frame: pd.DataFrame,
        actual: np.ndarray,
        baseline_raw: np.ndarray,
        predictions: dict[str, np.ndarray],
        runs: list[ModelRun],
        split: str,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        rows: list[dict[str, Any]] = []
        groups: list[dict[str, Any]] = []
        candidates = [("Seasonal Naive", baseline_raw, None)] + [(run.name, predictions[run.name], run) for run in runs]
        for name, raw, run in candidates:
            clipped = apply_capacity_clip(raw, frame["available_room_nights"])
            for prediction_type, values in (("raw", raw), ("clipped", clipped)):
                record = metric_record(name, split, prediction_type, actual, values)
                if run:
                    record.update(fit_seconds=run.fit_seconds, best_iteration=run.best_iteration)
                rows.append(record)
                groups.extend(grouped_metrics(frame, actual, values, name, split, prediction_type))
        return pd.DataFrame(rows), groups

    def _evaluate_selected(
        self,
        frame: pd.DataFrame,
        actual: np.ndarray,
        baseline_raw: np.ndarray,
        model_raw: np.ndarray,
        model_name: str,
        split: str,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        rows: list[dict[str, Any]] = []
        groups: list[dict[str, Any]] = []
        for name, raw in (("Seasonal Naive", baseline_raw), (model_name, model_raw)):
            clipped = apply_capacity_clip(raw, frame["available_room_nights"])
            for prediction_type, values in (("raw", raw), ("clipped", clipped)):
                rows.append(metric_record(name, split, prediction_type, actual, values))
                groups.extend(grouped_metrics(frame, actual, values, name, split, prediction_type))
        return pd.DataFrame(rows), groups

    @staticmethod
    def _select_model(metrics: pd.DataFrame, runs: list[ModelRun]) -> ModelRun:
        names = [run.name for run in runs]
        ranked = metrics[metrics["prediction_type"].eq("clipped") & metrics["model"].isin(names)].sort_values(["wape", "mae", "rmse"])
        return next(run for run in runs if run.name == ranked.iloc[0]["model"])

    @staticmethod
    def _selection_payload(metrics: pd.DataFrame, selected: ModelRun) -> dict[str, Any]:
        clipped = metrics[metrics["prediction_type"].eq("clipped")].set_index("model")
        baseline = float(clipped.loc["Seasonal Naive", "wape"])
        selected_wape = float(clipped.loc[selected.name, "wape"])
        return {
            "status": "PASS" if selected_wape < baseline else "REVIEW_REQUIRED",
            "baseline": "Seasonal Naive",
            "baseline_validation_clipped_wape": baseline,
            "selected_ml_candidate": selected.name,
            "selected_validation_clipped_wape": selected_wape,
            "relative_wape_improvement": (baseline - selected_wape) / baseline,
        }

    def _load_top2_candidates(self) -> list[str]:
        output = self.options.output_dir
        available = {"HistGradientBoostingRegressor"}
        try:
            from xgboost import XGBRegressor
            del XGBRegressor
            available.add("XGBRegressor")
        except ModuleNotFoundError:
            pass
        try:
            from lightgbm import LGBMRegressor
            del LGBMRegressor
            available.add("LGBMRegressor")
        except ModuleNotFoundError:
            pass

        top2_path = output / "top2_selection.json"
        if top2_path.is_file():
            with open(top2_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            top2 = [name for name in payload.get("top2_names", []) if name in available]
            if top2:
                return top2

        baseline_path = output / "baseline_candidate_metrics.csv"
        if not baseline_path.is_file():
            if "HistGradientBoostingRegressor" in available:
                return ["HistGradientBoostingRegressor"]
            raise FileNotFoundError("baseline_candidate_metrics.csv is required for tuning")
        baseline = pd.read_csv(baseline_path)
        candidates = baseline[baseline["prediction_type"].eq("clipped")].sort_values("wape")
        names = [name for name in candidates["model"].dropna().drop_duplicates().head(2).tolist() if name in available]
        if names:
            return names
        names = [name for name in ["XGBRegressor", "LGBMRegressor", "HistGradientBoostingRegressor"] if name in available]
        return names or []

    def _tuning_param_sets(self, model_name: str) -> list[dict[str, Any]]:
        if model_name == "XGBRegressor":
            return [
                {"n_estimators": 400, "learning_rate": 0.05, "max_depth": 4, "subsample": 0.9, "colsample_bytree": 0.8},
                {"n_estimators": 800, "learning_rate": 0.03, "max_depth": 5, "subsample": 0.8, "colsample_bytree": 0.8},
            ]
        if model_name == "LGBMRegressor":
            return [
                {"n_estimators": 1600, "learning_rate": 0.05, "num_leaves": 31, "min_child_samples": 20},
                {"n_estimators": 2400, "learning_rate": 0.03, "num_leaves": 63, "min_child_samples": 16},
            ]
        if model_name == "HistGradientBoostingRegressor":
            return [
                {"max_iter": 200, "learning_rate": 0.1},
                {"max_iter": 400, "learning_rate": 0.08},
            ]
        return [{}]

    def _build_tuned_model(self, model_name: str, params: dict[str, Any]):
        if model_name == "XGBRegressor":
            from xgboost import XGBRegressor

            return XGBRegressor(
                objective="reg:squarederror",
                random_state=SEED,
                n_jobs=-1,
                tree_method="hist",
                eval_metric="mae",
                early_stopping_rounds=self.options.early_stopping_rounds,
                **{"n_estimators": self.options.n_estimators, **params},
            )
        if model_name == "LGBMRegressor":
            from lightgbm import LGBMRegressor

            return LGBMRegressor(
                objective="regression",
                random_state=SEED,
                n_jobs=-1,
                verbosity=-1,
                **{"n_estimators": self.options.n_estimators, **params},
            )
        if model_name == "HistGradientBoostingRegressor":
            from sklearn.ensemble import HistGradientBoostingRegressor

            tuned_max_iter = int(params.get("max_iter", min(self.options.n_estimators, 500)))
            return HistGradientBoostingRegressor(
                random_state=SEED,
                learning_rate=float(params.get("learning_rate", 0.1)),
                max_iter=tuned_max_iter,
            )
        raise ValueError(f"Unsupported model for tuning: {model_name}")

    def _save_test_predictions(
        self,
        frame: pd.DataFrame,
        model_name: str,
        raw: np.ndarray,
        clipped: np.ndarray,
        lower: np.ndarray,
        upper: np.ndarray,
    ) -> None:
        result = frame[KEY_COLUMNS + ["available_room_nights", LABEL]].copy()
        result["model_name"] = model_name
        result["raw_prediction_rooms_sold"] = raw
        result["predicted_rooms_sold"] = clipped
        result["prediction_lower_rooms_sold"] = lower
        result["prediction_upper_rooms_sold"] = upper
        result.to_csv(self.options.output_dir / "test_predictions.csv", index=False)

    def _save_model_artifacts(self, bundle: Any, preprocessor: Any, selected: ModelRun) -> None:
        numeric_ranges = {
            column: {
                "min": float(bundle.train[column].min()),
                "max": float(bundle.train[column].max()),
            }
            for column in NUMERIC_FEATURES
        }
        category_values = {
            column: sorted(bundle.train[column].dropna().astype(str).unique().tolist())
            for column in CATEGORICAL_FEATURES
        }
        joblib.dump({"preprocessor": preprocessor, "model": selected.model, "model_name": selected.name, "feature_columns": FEATURES, "label": LABEL, "seed": SEED, "critical_runtime_features": CRITICAL_RUNTIME_FEATURES, "numeric_training_ranges": numeric_ranges, "categorical_training_values": category_values}, self.options.output_dir / "room_demand_model.joblib")
        names = preprocessor.get_feature_names_out()
        if hasattr(selected.model, "feature_importances_"):
            importances = np.asarray(selected.model.feature_importances_, dtype=float)
        else:
            importances = np.zeros(len(names), dtype=float)
        if importances.size != len(names):
            importances = np.resize(importances, len(names))
        pd.DataFrame({"feature": names, "importance": importances}).sort_values("importance", ascending=False).to_csv(self.options.output_dir / "feature_importance.csv", index=False)
        contract = {
            "label": LABEL,
            "grain": KEY_COLUMNS,
            "feature_count": len(FEATURES),
            "features": FEATURES,
            "numeric_features": NUMERIC_FEATURES,
            "categorical_features": CATEGORICAL_FEATURES,
            "hidden_qa_used": False,
            "critical_runtime_features": CRITICAL_RUNTIME_FEATURES,
            "numeric_training_ranges": numeric_ranges,
            "categorical_training_values": category_values,
            "dataset_versions": self._dataset_versions(bundle.manifest),
        }
        self._save_json(self.options.output_dir / "room_demand_feature_contract.json", contract)

    def _save_forecast(
        self,
        forecast: pd.DataFrame,
        train: pd.DataFrame,
        preprocessor: Any,
        selected: ModelRun,
        calibrator: PredictionIntervalCalibrator,
    ) -> int:
        current = forecast[forecast["prediction_cutoff_date"].eq(pd.Timestamp(self.options.as_of_date))].copy()
        if current.empty:
            raise ValueError(f"prediction_cutoff_date={self.options.as_of_date}인 FORECAST 행이 없습니다.")
        raw = np.asarray(selected.model.predict(preprocessor.transform(current[FEATURES])), dtype=float)
        clipped = apply_capacity_clip(raw, current["available_room_nights"])
        lower, upper = calibrator.bounds(current, clipped)
        result = current[KEY_COLUMNS + ["prediction_cutoff_date", "available_room_nights"]].copy()
        result["model_name"] = selected.name
        result["raw_prediction_rooms_sold"] = raw
        result["predicted_rooms_sold"] = clipped
        result["prediction_lower_rooms_sold"] = lower
        result["prediction_upper_rooms_sold"] = upper
        warning_features = []
        for _, row in current.iterrows():
            outside = [
                column for column in NUMERIC_FEATURES
                if row[column] < train[column].min() or row[column] > train[column].max()
            ]
            warning_features.append(",".join(outside))
        result["input_range_warning"] = [bool(value) for value in warning_features]
        result["out_of_range_features"] = warning_features
        result.to_csv(self.options.output_dir / "forecast_predictions.csv", index=False)
        return len(result)

    def _save_profile(self, bundle: Any, checks: list[Any]) -> None:
        profile: dict[str, Any] = {}
        for name in ("train", "validation", "test", "forecast"):
            frame = getattr(bundle, name)
            profile[name] = {
                "rows": len(frame),
                "columns": len(frame.columns),
                "target_date_min": frame["target_date"].min(),
                "target_date_max": frame["target_date"].max(),
                "max_feature_null_rate": float(frame[FEATURES].isna().mean().max()),
                "room_type_count": int(frame["room_type_code"].nunique()),
                "horizon_count": int(frame["horizon_days"].nunique()),
            }
        profile["hidden_qa"] = {"rows": len(bundle.hidden_qa), "columns": len(bundle.hidden_qa.columns)}
        profile["manifest"] = {"rows": len(bundle.manifest), "columns": len(bundle.manifest.columns)}
        profile["quality"] = {
            "pass": int(sum(check.status == "PASS" for check in checks)),
            "fail": int(sum(check.status == "FAIL" for check in checks)),
        }
        self._save_json(self.options.output_dir / "data_profile.json", profile)

    def _metadata(
        self,
        bundle: Any,
        selected: ModelRun,
        forecast_count: int,
        interval_metrics: dict[str, Any],
        model_sha256: str,
    ) -> dict[str, Any]:
        return {
            "status": "TRAINED_AND_TESTED",
            "is_synthetic": True,
            "seed": SEED,
            "model_name": selected.name,
            "model_sha256": model_sha256,
            "best_iteration": selected.best_iteration,
            "fit_seconds": selected.fit_seconds,
            "feature_count": len(FEATURES),
            "as_of_date": self.options.as_of_date,
            "forecast_row_count": forecast_count,
            "prediction_interval": interval_metrics,
            "dataset_versions": self._dataset_versions(bundle.manifest),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "train_period": [bundle.train["target_date"].min().date(), bundle.train["target_date"].max().date()],
            "validation_period": [bundle.validation["target_date"].min().date(), bundle.validation["target_date"].max().date()],
            "test_period": [bundle.test["target_date"].min().date(), bundle.test["target_date"].max().date()],
            "package_versions": {name: self._package_version(name) for name in ("pandas", "numpy", "scikit-learn", "xgboost", "lightgbm", "joblib")},
        }

    @staticmethod
    def _dataset_versions(manifest: pd.DataFrame) -> dict[str, list[str]]:
        version_columns = ("schema_version", "scenario_version", "fixture_version")
        return {
            column: sorted(manifest[column].dropna().astype(str).unique().tolist())
            for column in version_columns
            if column in manifest
        }

    @staticmethod
    def _package_version(name: str) -> str:
        try:
            return version(name)
        except PackageNotFoundError:
            return "unknown"

    @staticmethod
    def _save_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
