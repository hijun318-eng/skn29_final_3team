from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from .config import LABEL


def apply_capacity_clip(prediction: np.ndarray, capacity: pd.Series) -> np.ndarray:
    rounded = np.rint(np.asarray(prediction, dtype=float))
    return np.minimum(np.maximum(rounded, 0), capacity.to_numpy(dtype=float)).astype(int)


def wape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denominator = float(np.abs(y_true).sum())
    return float("nan") if denominator == 0 else float(np.abs(y_true - y_pred).sum() / denominator)


def metric_record(model: str, split: str, prediction_type: str, y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    return {
        "model": model,
        "split": split,
        "prediction_type": prediction_type,
        "row_count": int(len(y_true)),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "wape": wape(y_true, y_pred),
        "r2": float(r2_score(y_true, y_pred)) if len(y_true) > 1 else float("nan"),
    }


def grouped_metrics(frame: pd.DataFrame, y_true: np.ndarray, y_pred: np.ndarray, model: str, split: str, prediction_type: str) -> list[dict[str, Any]]:
    work = frame[["room_type_code", "horizon_days"]].copy()
    work["_actual"] = y_true
    work["_prediction"] = y_pred
    records: list[dict[str, Any]] = []
    for group_type, columns in (
        ("room_type", ["room_type_code"]),
        ("horizon", ["horizon_days"]),
        ("room_type_horizon", ["room_type_code", "horizon_days"]),
    ):
        for keys, group in work.groupby(columns, dropna=False):
            values = keys if isinstance(keys, tuple) else (keys,)
            record = metric_record(model, split, prediction_type, group["_actual"].to_numpy(float), group["_prediction"].to_numpy(float))
            record["group_type"] = group_type
            record.update(dict(zip(columns, values)))
            records.append(record)
    return records


def build_actual_lookup(*frames: pd.DataFrame) -> pd.DataFrame:
    columns = ["property_id", "target_date", "room_type_code", LABEL]
    history = pd.concat([frame[columns] for frame in frames], ignore_index=True).dropna(subset=[LABEL])
    grain = columns[:-1]
    conflicts = history.groupby(grain)[LABEL].nunique(dropna=True).gt(1)
    if conflicts.any():
        raise ValueError("같은 호텔/날짜/객실유형에 서로 다른 Label이 있습니다.")
    return history.sort_values(grain).drop_duplicates(grain)


def seasonal_naive(target: pd.DataFrame, actual_lookup: pd.DataFrame) -> np.ndarray:
    work = target[["property_id", "target_date", "room_type_code"]].copy()
    work["_baseline_date"] = work["target_date"] - pd.Timedelta(days=7)
    lookup = actual_lookup.rename(columns={"target_date": "_baseline_date", LABEL: "_baseline"})
    merged = work.merge(lookup, on=["property_id", "_baseline_date", "room_type_code"], how="left", validate="many_to_one")
    missing = int(merged["_baseline"].isna().sum())
    if missing:
        raise ValueError(f"Seasonal Naive의 7일 전 Label 누락: {missing}행")
    return merged["_baseline"].to_numpy(float)
