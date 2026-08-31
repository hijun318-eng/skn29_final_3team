"""객실 수요 estimator pipeline과 다중 scope 예측 wrapper를 구현한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .contracts import CATEGORICAL_FEATURES, FEATURE_COLUMNS, NUMERIC_FEATURES



def _encoder() -> OneHotEncoder:
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=False)


def build_pipeline(config: dict[str, Any]) -> Pipeline:
    """범주형 encoding과 지정 HGBR 또는 ExtraTrees estimator를 한 pipeline으로 만든다.

    필요한 hyperparameter가 누락되거나 sklearn이 값을 거부하면 예외를
    그대로 전달하며 아직 학습되지 않은 pipeline을 반환한다.
    """

    transformer = ColumnTransformer(
        [
            ("categorical", _encoder(), CATEGORICAL_FEATURES),
            ("numeric", "passthrough", NUMERIC_FEATURES),
        ],
        remainder="drop",
    )
    if config.get("estimator") == "extra_trees":
        estimator = ExtraTreesRegressor(
            n_estimators=config["n_estimators"],
            max_depth=config["max_depth"],
            min_samples_leaf=config["min_samples_leaf"],
            max_features=config["max_features"],
            n_jobs=-1,
            random_state=config["random_state"],
        )
    else:
        estimator = HistGradientBoostingRegressor(
            loss=config["loss"],
            learning_rate=config["learning_rate"],
            max_iter=config["max_iter"],
            max_leaf_nodes=config["max_leaf_nodes"],
            min_samples_leaf=config["min_samples_leaf"],
            l2_regularization=config["l2_regularization"],
            random_state=config["random_state"],
        )
    return Pipeline([("features", transformer), ("model", estimator)])


@dataclass
class TimeSeriesDemandModel:
    """global 또는 그룹별 pipeline의 target 복원·blend·수용량 제한을 담당한다."""

    pipeline: Pipeline | None
    blend_weight: float
    model_version: str
    pipelines: dict[str, Pipeline] | None = None
    target_mode: str = "occupancy_rate"
    segment_offsets: dict[str, float] | None = None
    pipeline_scope: str = "series"

    @staticmethod
    def series_key(property_id: object, room_type_code: object) -> str:
        """property와 room type을 offset 조회에 쓰는 안정된 문자열 key로 결합한다."""

        return f"{property_id}|{room_type_code}"

    @staticmethod
    def group_key(values: object) -> str:
        """단일값이나 tuple 그룹 값을 pipeline mapping용 문자열 key로 정규화한다."""

        normalized = values if isinstance(values, tuple) else (values,)
        return "|".join(str(value) for value in normalized)

    def _model_prediction(self, frame: pd.DataFrame) -> np.ndarray:
        pipelines = getattr(self, "pipelines", None)
        if pipelines:
            working = frame.reset_index(drop=True)
            prediction = np.empty(len(working), dtype=float)
            scope = getattr(self, "pipeline_scope", "series")
            group_columns = {
                "series": ["property_id", "room_type_code"],
                "horizon": ["horizon_days"],
                "property_horizon": ["property_id", "horizon_days"],
            }[scope]
            for keys, subset in working.groupby(group_columns, sort=False):
                key = self.group_key(keys)
                if key not in pipelines:
                    raise ValueError(f"model missing pipeline group: {key}")
                positions = subset.index.to_numpy()
                prediction[positions] = pipelines[key].predict(
                    subset[FEATURE_COLUMNS]
                )
            return prediction
        pipeline = getattr(self, "pipeline", None)
        if pipeline is None:
            raise ValueError("model has no fitted pipeline")
        return np.asarray(pipeline.predict(frame[FEATURE_COLUMNS]), dtype=float)

    def predict_raw(self, frame: pd.DataFrame) -> np.ndarray:
        """학습 target mode를 객실 수로 복원하고 seasonal blend·segment offset을 적용한다.

        필요한 feature, pipeline group 또는 지원 target mode가 없으면
        ``KeyError``나 ``ValueError``로 추론을 중단하며 수용량 clipping 전 값을 반환한다.
        """

        model_prediction = self._model_prediction(frame)
        capacity = frame["physical_rooms"].astype(float).to_numpy()
        target_mode = getattr(self, "target_mode", "occupancy_rate")
        if target_mode == "occupancy_rate":
            model_rooms = model_prediction * capacity
        elif target_mode == "rooms_sold":
            model_rooms = model_prediction
        elif target_mode == "log_rooms_sold":
            model_rooms = np.expm1(model_prediction)
        elif target_mode in {"residual_rate", "residual_rate_12w"}:
            seasonal_column = (
                "same_weekday_mean_12w"
                if target_mode == "residual_rate_12w"
                else "same_weekday_mean_4w"
            )
            seasonal = frame[seasonal_column].astype(float).to_numpy()
            model_rooms = seasonal + model_prediction * capacity
        else:
            raise ValueError(f"unsupported target mode: {target_mode}")
        seasonal_column = (
            "same_weekday_mean_12w"
            if target_mode == "residual_rate_12w"
            else "same_weekday_mean_4w"
        )
        seasonal = frame[seasonal_column].astype(float).to_numpy()
        prediction = self.blend_weight * model_rooms + (
            1.0 - self.blend_weight
        ) * seasonal
        offsets = getattr(self, "segment_offsets", None)
        if offsets:
            keys = [
                self.series_key(property_id, room_type_code)
                for property_id, room_type_code in zip(
                    frame["property_id"], frame["room_type_code"]
                )
            ]
            prediction = prediction + np.asarray(
                [offsets.get(key, 0.0) for key in keys], dtype=float
            )
        return prediction

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        """raw 객실 수 예측을 0 이상 각 행의 물리 수용량 이하로 제한해 반환한다."""

        capacity = frame["physical_rooms"].astype(float).to_numpy()
        return np.clip(self.predict_raw(frame), 0.0, capacity)
