from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

from .config import CATEGORICAL_FEATURES, FEATURES, NUMERIC_FEATURES


@dataclass
class BaselineCandidate:
    name: str
    model: Any
    scale_features: bool


class BaselineRegistry:
    def __init__(self, seed: int):
        self.seed = seed
        self.candidates = [
            BaselineCandidate(
                "LogisticRegression",
                LogisticRegression(max_iter=1000, random_state=self.seed),
                scale_features=True,
            ),
            BaselineCandidate(
                "HistGradientBoostingClassifier",
                HistGradientBoostingClassifier(max_iter=1000, random_state=self.seed),
                scale_features=False,
            ),
            BaselineCandidate(
                "RandomForestClassifier",
                RandomForestClassifier(n_estimators=100, random_state=self.seed),
                scale_features=False,
            ),
            BaselineCandidate(
                "LGBMClassifier",
                LGBMClassifier(random_state=self.seed, verbose=-1),
                scale_features=False,
            ),
            BaselineCandidate(
                "XGBClassifier",
                XGBClassifier(random_state=self.seed, eval_metric="logloss"),
                scale_features=False,
            ),
        ]

    def get_candidate(self, name: str) -> BaselineCandidate:
        for candidate in self.candidates:
            if candidate.name == name:
                return candidate
        raise ValueError(f"Unknown model candidate: {name}")

    def get_reference_baseline(self) -> Pipeline:
        return Pipeline(
            [
                ("preprocess", self.preprocessor(scale=False)),
                ("model", DummyClassifier(strategy="prior")),
            ]
        )

    def preprocessor(self, scale: bool) -> ColumnTransformer:
        numeric = StandardScaler() if scale else "passthrough"
        categorical = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
        return ColumnTransformer(
            [
                ("numeric", numeric, NUMERIC_FEATURES),
                ("categorical", categorical, CATEGORICAL_FEATURES),
            ]
        )

    def build_pipeline(self, candidate: BaselineCandidate) -> Pipeline:
        return Pipeline(
            [
                ("preprocess", self.preprocessor(scale=candidate.scale_features)),
                ("model", candidate.model),
            ]
        )

    def build_pipeline_from_model(self, candidate: BaselineCandidate, model: Any) -> Pipeline:
        return Pipeline(
            [
                ("preprocess", self.preprocessor(scale=candidate.scale_features)),
                ("model", model),
            ]
        )

    def build_pipeline_by_name(
        self,
        candidate_name: str,
        overrides: dict[str, Any] | None = None,
    ) -> Pipeline:
        candidate = self.get_candidate(candidate_name)
        model = clone(candidate.model)
        if overrides:
            model.set_params(**overrides)
        return self.build_pipeline_from_model(candidate, model)

    @staticmethod
    def extract_effective_params(pipeline: Pipeline) -> str:
        model = pipeline.named_steps["model"]
        return json.dumps(model.get_params(), default=str)


class ModelTrainer:
    def __init__(self, seed: int):
        self.seed = seed
        self.registry = BaselineRegistry(seed)

    def fit_baseline_candidates(self, train: pd.DataFrame) -> dict[str, Pipeline]:
        x_train = train[FEATURES]
        y_train = train["is_no_show"].to_numpy()

        models: dict[str, Pipeline] = {}
        reference = self.registry.get_reference_baseline()
        reference.fit(x_train, y_train)
        models["PriorProbability"] = reference

        for candidate in self.registry.candidates:
            pipe = self.registry.build_pipeline(candidate)
            pipe.fit(x_train, y_train)
            models[candidate.name] = pipe

        return models

    def build_pipeline_by_name(
        self,
        candidate_name: str,
        overrides: dict[str, Any] | None = None,
    ) -> Pipeline:
        return self.registry.build_pipeline_by_name(candidate_name, overrides)

    @staticmethod
    def probabilities(models: dict[str, Pipeline], frame: pd.DataFrame) -> dict[str, np.ndarray]:
        return {
            name: model.predict_proba(frame[FEATURES])[:, 1]
            for name, model in models.items()
        }
