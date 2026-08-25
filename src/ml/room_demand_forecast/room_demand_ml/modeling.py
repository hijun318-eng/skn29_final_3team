from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .config import CATEGORICAL_FEATURES, NUMERIC_FEATURES, SEED


@dataclass
class ModelRun:
    name: str
    model: Any
    fit_seconds: float

    @property
    def best_iteration(self) -> int | None:
        for attribute in ("best_iteration", "best_iteration_"):
            value = getattr(self.model, attribute, None)
            if value is not None:
                return int(value)
        return None


class ModelTrainer:
    def __init__(self, n_estimators: int = 3000, early_stopping_rounds: int = 100) -> None:
        self.n_estimators = n_estimators
        self.early_stopping_rounds = early_stopping_rounds

    @staticmethod
    def make_preprocessor() -> ColumnTransformer:
        numeric = Pipeline([("imputer", SimpleImputer(strategy="median"))])
        categorical = Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ])
        preprocessor = ColumnTransformer([
            ("numeric", numeric, NUMERIC_FEATURES),
            ("categorical", categorical, CATEGORICAL_FEATURES),
        ])
        return preprocessor.set_output(transform="pandas")

    def train(self, x_train: Any, y_train: Any, x_validation: Any, y_validation: Any) -> list[ModelRun]:
        try:
            from xgboost import XGBRegressor
            xgb_available = True
        except ModuleNotFoundError:
            xgb_available = False

        try:
            import lightgbm as lgb
            from lightgbm import LGBMRegressor
            lgb_available = True
        except ModuleNotFoundError:
            lgb_available = False
            lgb = None
            LGBMRegressor = None

        models = [
            (
                "XGBRegressor",
                XGBRegressor(
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
                    early_stopping_rounds=self.early_stopping_rounds,
                    random_state=SEED,
                    n_jobs=-1,
                )
                if xgb_available
                else None
            ),
        ]
        if lgb_available:
            models.append(
                (
                    "LGBMRegressor",
                    LGBMRegressor(
                        objective="regression",
                        n_estimators=self.n_estimators,
                        learning_rate=0.03,
                        num_leaves=31,
                        min_child_samples=20,
                        subsample=0.8,
                        subsample_freq=1,
                        colsample_bytree=0.8,
                        reg_lambda=1.0,
                        random_state=SEED,
                        n_jobs=-1,
                        verbosity=-1,
                    ),
                )
            )

        if not xgb_available and not lgb_available:
            models.append(
                (
                    "HistGradientBoostingRegressor",
                    HistGradientBoostingRegressor(
                        max_iter=min(self.n_estimators, 500),
                        learning_rate=0.1,
                        max_depth=12,
                        random_state=SEED,
                    ),
                )
            )
        models = [model for model in models if model[1] is not None]
        if not models:
            raise ModuleNotFoundError(
                "room demand training requires xgboost, lightgbm, or a scikit-learn fallback model"
            )
        runs: list[ModelRun] = []
        for name, model in models:
            started = time.perf_counter()
            if name == "XGBRegressor":
                model.fit(x_train, y_train, eval_set=[(x_validation, y_validation)], verbose=False)
            elif name == "LGBMRegressor":
                model.fit(
                    x_train,
                    y_train,
                    eval_set=[(x_validation, y_validation)],
                    eval_metric="mae",
                    callbacks=[lgb.early_stopping(self.early_stopping_rounds, verbose=False), lgb.log_evaluation(0)],
                )
            else:
                model.fit(x_train, y_train)
            runs.append(ModelRun(name, model, time.perf_counter() - started))
        return runs
