"""운영형 HGBR 모델의 학습 파이프라인·예측구간·영향요인을 구현한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .contracts import CATEGORICAL_FEATURES
from .operational_contracts import (
    EXPLAINABLE_FEATURES,
    FACTOR_LABELS_KO,
    OPERATIONAL_FEATURE_COLUMNS,
    TARGET_CAPACITY_COLUMN,
)


def _encoder() -> OneHotEncoder:
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=False)


def build_operational_pipeline(
    config: dict[str, Any],
    feature_columns: list[str] | None = None,
) -> Pipeline:
    """범주형 인코딩과 HGBR 점유율 회귀를 하나의 재현 가능한 파이프라인으로 만든다."""

    selected = feature_columns or OPERATIONAL_FEATURE_COLUMNS
    categorical = [column for column in CATEGORICAL_FEATURES if column in selected]
    numeric = [column for column in selected if column not in categorical]
    transformer = ColumnTransformer(
        [
            ("categorical", _encoder(), categorical),
            ("numeric", "passthrough", numeric),
        ],
        remainder="drop",
    )
    estimator = HistGradientBoostingRegressor(
        loss=config.get("loss", "squared_error"),
        learning_rate=float(config["learning_rate"]),
        max_iter=int(config["max_iter"]),
        max_leaf_nodes=int(config["max_leaf_nodes"]),
        min_samples_leaf=int(config["min_samples_leaf"]),
        l2_regularization=float(config["l2_regularization"]),
        random_state=int(config["random_state"]),
    )
    return Pipeline([("features", transformer), ("model", estimator)])


@dataclass
class OperationalDemandModel:
    """판매 가능 객실을 분모로 예측하고 보정 구간과 국소 영향요인을 제공한다."""

    pipeline: Pipeline
    model_version: str
    interval_quantiles: dict[int, dict[str, float]] = field(default_factory=dict)
    reference_values: dict[str, float] = field(default_factory=dict)
    quality_scope: dict[str, dict[str, Any]] = field(default_factory=dict)
    feature_columns: list[str] = field(
        default_factory=lambda: list(OPERATIONAL_FEATURE_COLUMNS)
    )

    def selected_feature_columns(self) -> list[str]:
        """구형 직렬화 artifact도 운영 특징 순서로 안전하게 읽는다."""

        return list(getattr(self, "feature_columns", OPERATIONAL_FEATURE_COLUMNS))

    def predict_rate_raw(self, frame: pd.DataFrame) -> np.ndarray:
        """clipping 전 점유율 예측값을 반환한다."""

        return np.asarray(
            self.pipeline.predict(frame[self.selected_feature_columns()]),
            dtype=float,
        )

    def predict_raw(self, frame: pd.DataFrame) -> np.ndarray:
        """clipping 전 점유 객실 수를 반환한다."""

        capacity = frame[TARGET_CAPACITY_COLUMN].astype(float).to_numpy()
        return self.predict_rate_raw(frame) * capacity

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        """예측을 0과 목표일 판매 가능 객실 사이로 제한한다."""

        capacity = frame[TARGET_CAPACITY_COLUMN].astype(float).to_numpy()
        return np.clip(self.predict_raw(frame), 0.0, capacity)

    def prediction_intervals(
        self,
        frame: pd.DataFrame,
        prediction: np.ndarray | None = None,
    ) -> list[dict[str, float]]:
        """horizon별 순차 검증 잔차 분위수로 80%·95% 보정 예측구간을 만든다."""

        points = self.predict(frame) if prediction is None else np.asarray(prediction)
        capacities = frame[TARGET_CAPACITY_COLUMN].astype(float).to_numpy()
        output: list[dict[str, float]] = []
        for index, horizon in enumerate(frame["horizon_days"].astype(int)):
            quantiles = self.interval_quantiles.get(int(horizon))
            if not quantiles:
                raise ValueError(f"prediction interval is missing for D+{horizon}")
            point = float(points[index])
            capacity = float(capacities[index])
            output.append(
                {
                    "lower_80": max(0.0, point - float(quantiles["q80"])),
                    "upper_80": min(capacity, point + float(quantiles["q80"])),
                    "lower_95": max(0.0, point - float(quantiles["q95"])),
                    "upper_95": min(capacity, point + float(quantiles["q95"])),
                }
            )
        return output

    def influencing_factors(
        self,
        frame: pd.DataFrame,
        *,
        limit: int = 5,
    ) -> list[list[dict[str, Any]]]:
        """특징 하나를 학습 기준값으로 바꾼 반사실 차이로 상위 영향요인을 계산한다."""

        base = self.predict(frame)
        per_feature: dict[str, np.ndarray] = {}
        for feature in EXPLAINABLE_FEATURES:
            if feature not in self.reference_values or feature not in frame:
                continue
            changed = frame.copy()
            changed[feature] = float(self.reference_values[feature])
            per_feature[feature] = base - self.predict(changed)
        output: list[list[dict[str, Any]]] = []
        for index, row in frame.reset_index(drop=True).iterrows():
            factors = [
                {
                    "feature_code": feature,
                    "label": FACTOR_LABELS_KO[feature],
                    "value": round(float(row[feature]), 4),
                    "reference_value": round(float(self.reference_values[feature]), 4),
                    "impact_rooms": round(float(impacts[index]), 4),
                    "direction": "INCREASE" if impacts[index] >= 0 else "DECREASE",
                }
                for feature, impacts in per_feature.items()
            ]
            factors.sort(key=lambda item: abs(item["impact_rooms"]), reverse=True)
            output.append(factors[:limit])
        return output
