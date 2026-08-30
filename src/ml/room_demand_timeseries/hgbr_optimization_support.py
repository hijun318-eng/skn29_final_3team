from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


TARGET = "target_rooms_sold"
CAPACITY = "physical_rooms"
DATE = "target_date"
BASELINE = "same_weekday_mean_4w"
IDENTITY = ["property_id", "room_type_code", "cutoff_date", "target_date", "horizon_days"]
MARGIN = 0.002


@dataclass(frozen=True)
class HgbrSpec:
    name: str
    mode: str
    loss: str
    max_iter: int
    learning_rate: float
    max_leaf_nodes: int
    min_samples_leaf: int
    l2_regularization: float


def transform_target(mode: str, target: np.ndarray, baseline: np.ndarray, capacity: np.ndarray) -> np.ndarray:
    if mode == "direct":
        return target
    if mode == "residual_rooms":
        return target - baseline
    if mode == "residual_rate":
        return (target - baseline) / np.maximum(capacity, 1.0)
    if mode == "occupancy_rate":
        return target / np.maximum(capacity, 1.0)
    raise ValueError(f"unknown target mode: {mode}")


def restore_prediction(mode: str, raw: np.ndarray, baseline: np.ndarray, capacity: np.ndarray) -> np.ndarray:
    if mode == "direct":
        prediction = raw
    elif mode == "residual_rooms":
        prediction = baseline + raw
    elif mode == "residual_rate":
        prediction = baseline + raw * capacity
    elif mode == "occupancy_rate":
        prediction = raw * capacity
    else:
        raise ValueError(f"unknown target mode: {mode}")
    return np.clip(prediction, 0, capacity)


def paired_block_bootstrap(
    daily: dict[str, np.ndarray], competitor_column: int, seed: int, samples: int = 2000, block: int = 7
) -> dict[str, object]:
    rng = np.random.default_rng(seed)
    deltas = np.empty(samples)
    for sample_index in range(samples):
        parts = []
        for values in daily.values():
            count = len(values)
            starts = rng.integers(0, count, size=math.ceil(count / block))
            indexes = np.concatenate([(np.arange(start, start + block) % count) for start in starts])[:count]
            parts.append(values[indexes])
        selected = np.concatenate(parts)
        denominator = selected[:, 0].sum()
        deltas[sample_index] = (
            selected[:, 1].sum() / denominator - selected[:, competitor_column].sum() / denominator
        )
    lower, upper = np.quantile(deltas, [0.025, 0.975])
    return {"samples": samples, "block_days": block, "ci95": [float(lower), float(upper)], "ci_upper": float(upper)}
