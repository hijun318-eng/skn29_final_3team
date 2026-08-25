from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBRegressor

from .config import CATEGORICAL_FEATURES, FEATURES, LABEL, NUMERIC_FEATURES, SEED
from .data import DatasetBundle
from .metrics import apply_capacity_clip, build_actual_lookup, seasonal_naive


class RobustnessAuditor:
    ABLATIONS = {
        "FULL": set(),
        "NO_BOOKING_ON_HAND": {
            "booking_on_hand",
            "booking_on_hand_ratio",
            "cancelled_on_hand",
        },
        "NO_RECENT_DEMAND": {
            "booking_on_hand",
            "booking_on_hand_ratio",
            "cancelled_on_hand",
            "rooms_sold_cutoff_lag_1",
            "rooms_sold_cutoff_lag_7",
            "rooms_sold_cutoff_lag_14",
            "rooms_sold_cutoff_rolling_mean_7",
            "rooms_sold_cutoff_rolling_mean_28",
            "adr_cutoff_lag_7",
            "cancellation_rate_cutoff_lag_28",
        },
        "NO_SCALE_PROXY": {"available_room_nights", "room_type_code"},
    }
    SEASON_FOLDS = [
        ("WINTER", "2025-01-01", "2025-03-31"),
        ("SPRING", "2025-04-01", "2025-06-30"),
        ("SUMMER", "2025-07-01", "2025-09-30"),
        ("AUTUMN", "2025-10-01", "2025-12-31"),
    ]

    def __init__(self, bundle: DatasetBundle, artifact_dir: Path) -> None:
        self.bundle = bundle
        self.artifact_dir = artifact_dir
        metadata = json.loads(
            (artifact_dir / "room_demand_model_metadata.json").read_text(encoding="utf-8")
        )
        self.n_estimators = int(metadata["best_iteration"]) + 1

    def run(self) -> dict[str, int]:
        ablation = self._ablation_metrics()
        rolling = self._rolling_metrics()
        ablation.to_csv(self.artifact_dir / "feature_ablation_metrics.csv", index=False)
        rolling.to_csv(self.artifact_dir / "rolling_backtest_metrics.csv", index=False)
        return {"ablation_rows": len(ablation), "rolling_rows": len(rolling)}

    def _ablation_metrics(self) -> pd.DataFrame:
        rows: list[dict[str, float | int | str]] = []
        for scenario, excluded in self.ABLATIONS.items():
            features = [column for column in FEATURES if column not in excluded]
            preprocessor = self._preprocessor(features)
            x_train = preprocessor.fit_transform(self.bundle.train[features])
            model = self._model()
            model.fit(x_train, self.bundle.train[LABEL].to_numpy(float), verbose=False)
            for split, frame in (
                ("VALIDATION", self.bundle.validation),
                ("TEST", self.bundle.test),
            ):
                prediction = apply_capacity_clip(
                    model.predict(preprocessor.transform(frame[features])),
                    frame["available_room_nights"],
                )
                rows.append(
                    self._metric_row(
                        scenario,
                        split,
                        len(features),
                        frame[LABEL].to_numpy(float),
                        prediction,
                    )
                )
        return pd.DataFrame(rows)

    def _rolling_metrics(self) -> pd.DataFrame:
        combined = pd.concat(
            [self.bundle.train, self.bundle.validation], ignore_index=True
        ).sort_values("target_date")
        lookup = build_actual_lookup(self.bundle.train, self.bundle.validation)
        rows: list[dict[str, float | int | str]] = []
        for season, start, end in self.SEASON_FOLDS:
            start_date = pd.Timestamp(start)
            end_date = pd.Timestamp(end)
            train = combined[combined["target_date"] < start_date]
            score = combined[
                combined["target_date"].between(start_date, end_date)
            ]
            preprocessor = self._preprocessor(FEATURES)
            model = self._model()
            model.fit(
                preprocessor.fit_transform(train[FEATURES]),
                train[LABEL].to_numpy(float),
                verbose=False,
            )
            prediction = apply_capacity_clip(
                model.predict(preprocessor.transform(score[FEATURES])),
                score["available_room_nights"],
            )
            baseline = apply_capacity_clip(
                seasonal_naive(score, lookup), score["available_room_nights"]
            )
            row = self._metric_row(
                season,
                "ROLLING_BACKTEST",
                len(FEATURES),
                score[LABEL].to_numpy(float),
                prediction,
            )
            row.update(
                score_start=start,
                score_end=end,
                train_rows=len(train),
                score_rows=len(score),
                negative_predictions=int((prediction < 0).sum()),
                over_capacity_predictions=int(
                    (prediction > score["available_room_nights"].to_numpy(float)).sum()
                ),
                baseline_wape=float(
                    np.abs(baseline - score[LABEL].to_numpy(float)).sum()
                    / np.abs(score[LABEL].to_numpy(float)).sum()
                ),
            )
            rows.append(row)
        return pd.DataFrame(rows)

    def _model(self) -> XGBRegressor:
        return XGBRegressor(
            objective="reg:squarederror",
            n_estimators=self.n_estimators,
            learning_rate=0.03,
            max_depth=6,
            min_child_weight=5,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            tree_method="hist",
            eval_metric="mae",
            random_state=SEED,
            n_jobs=-1,
        )

    @staticmethod
    def _preprocessor(features: list[str]) -> ColumnTransformer:
        numeric = [column for column in NUMERIC_FEATURES if column in features]
        categorical = [column for column in CATEGORICAL_FEATURES if column in features]
        numeric_pipe = Pipeline([("imputer", SimpleImputer(strategy="median"))])
        category_pipe = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
            ]
        )
        return ColumnTransformer(
            [("numeric", numeric_pipe, numeric), ("categorical", category_pipe, categorical)]
        ).set_output(transform="pandas")

    @staticmethod
    def _metric_row(
        scenario: str,
        split: str,
        feature_count: int,
        actual: np.ndarray,
        prediction: np.ndarray,
    ) -> dict[str, float | int | str]:
        error = np.asarray(prediction, dtype=float) - np.asarray(actual, dtype=float)
        absolute = np.abs(error)
        return {
            "scenario": scenario,
            "split": split,
            "feature_count": feature_count,
            "row_count": len(actual),
            "mae": float(absolute.mean()),
            "rmse": float(np.sqrt(np.mean(error**2))),
            "wape": float(absolute.sum() / np.abs(actual).sum()),
            "bias": float(error.mean()),
            "within_3_rooms": float((absolute <= 3).mean()),
        }
