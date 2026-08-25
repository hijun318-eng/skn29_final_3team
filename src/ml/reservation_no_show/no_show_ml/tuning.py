from __future__ import annotations

import json
from typing import Any

import pandas as pd
from sklearn.metrics import average_precision_score

from .config import FEATURES
from .modeling import BaselineRegistry
from .evaluation import classification_metrics, ranking_metrics, select_threshold


class TuningRunner:
    _MODEL_VERSION = "no-show-tuning-v1"

    def __init__(self, seed: int, *, source_snapshot_id: str | None = None):
        self.seed = seed
        self.source_snapshot_id = source_snapshot_id
        self.registry = BaselineRegistry(seed)

    def tune_top2(
        self,
        train: pd.DataFrame,
        validation: pd.DataFrame,
        top2_names: list[str],
    ) -> pd.DataFrame:
        x_train = train[FEATURES]
        y_train = train["is_no_show"].to_numpy()
        x_validation = validation[FEATURES]
        y_validation = validation["is_no_show"].to_numpy()

        trials: list[dict[str, Any]] = []
        for name in top2_names:
            configs = self._trial_configs(name)
            for idx, config in enumerate(configs):
                pipeline = self.registry.build_pipeline_by_name(name, config)
                pipeline.fit(x_train, y_train)
                prob = pipeline.predict_proba(x_validation)[:, 1]
                threshold, threshold_reason = select_threshold(y_validation, prob)
                class_metrics = classification_metrics("VALIDATION", name, y_validation, prob, threshold)
                rank_metrics = ranking_metrics(y_validation, prob)
                monthly = self._monthly_calibration(validation, y_validation, prob)

                trials.append(
                    {
                        "trial_id": f"{name}:tuned_{idx+1}",
                        "model_family": name,
                        "configuration": json.dumps(config, sort_keys=True, default=str),
                        "split": "VALIDATION",
                        "model_version": self._MODEL_VERSION,
                        "trial_seed": self.seed,
                        "source_snapshot_id": self.source_snapshot_id,
                        "validation_threshold": threshold,
                        "validation_threshold_reason": threshold_reason,
                        "validation_average_precision": class_metrics["pr_auc"],
                        "validation_roc_auc": class_metrics["roc_auc"],
                        "validation_brier_score": class_metrics["brier_score"],
                        "precision_at_15": rank_metrics["precision_at_15"],
                        "recall_at_15": rank_metrics["recall_at_15"],
                        "lift_at_15": rank_metrics["lift_at_15"],
                        "score_cutoff_at_15": rank_metrics["score_cutoff_at_15"],
                        "monthly_average_precision_mean": monthly["mean"],
                        "monthly_average_precision_std": monthly["std"],
                        "monthly_average_precision_min": monthly["min"],
                    }
                )
        return self._sort_trials(trials)

    @staticmethod
    def _monthly_calibration(
        frame: pd.DataFrame,
        y_true: pd.Series | list[float],
        probabilities: pd.Series | list[float],
    ) -> dict[str, Any]:
        if "checkin_date" not in frame.columns:
            return {"mean": 0.0, "std": 0.0, "min": 0.0}
        by_month = (
            pd.DataFrame(
                {
                    "month": pd.to_datetime(frame["checkin_date"]).dt.to_period("M"),
                    "y_true": y_true,
                    "probability": probabilities,
                }
            )
            .groupby("month")
            .apply(lambda g: average_precision_score(g["y_true"], g["probability"]))
        )
        return {
            "mean": float(by_month.mean()) if len(by_month) else 0.0,
            "std": float(by_month.std(ddof=0)) if len(by_month) else 0.0,
            "min": float(by_month.min()) if len(by_month) else 0.0,
        }

    @staticmethod
    def _trial_configs(model_name: str) -> list[dict[str, Any]]:
        if model_name == "LogisticRegression":
            return [
                {"C": 0.3},
                {"C": 1.0},
            ]
        if model_name == "HistGradientBoostingClassifier":
            return [
                {"learning_rate": 0.05, "max_depth": 12},
                {"learning_rate": 0.08, "max_depth": 8},
            ]
        if model_name == "RandomForestClassifier":
            return [
                {"n_estimators": 100},
                {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 1},
            ]
        if model_name == "LGBMClassifier":
            return [
                {"num_leaves": 31, "learning_rate": 0.03, "n_estimators": 800},
                {"num_leaves": 63, "learning_rate": 0.05, "n_estimators": 1200},
            ]
        if model_name == "XGBClassifier":
            return [
                {"n_estimators": 300, "learning_rate": 0.03, "max_depth": 3},
                {"n_estimators": 600, "learning_rate": 0.07, "max_depth": 5},
            ]
        return [{}]

    @staticmethod
    def _sort_trials(trials: list[dict[str, Any]]) -> pd.DataFrame:
        rows = pd.DataFrame(trials)
        if rows.empty:
            return rows
        ranking = rows.sort_values(
            by=[
                "validation_average_precision",
                "validation_roc_auc",
                "precision_at_15",
                "monthly_average_precision_mean",
                "validation_brier_score",
                "model_version",
                "split",
                "trial_seed",
                "trial_id",
            ],
            ascending=[False, False, False, False, True, True, True, True, True],
            na_position="last",
        )
        return ranking.reset_index(drop=True)
