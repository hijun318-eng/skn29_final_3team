"""HGBR 후보의 target 변환, 복원과 paired block bootstrap 비교를 지원한다."""

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
    """한 HGBR 후보의 target mode, loss와 학습 hyperparameter를 고정한다."""

    name: str
    mode: str
    loss: str
    max_iter: int
    learning_rate: float
    max_leaf_nodes: int
    min_samples_leaf: int
    l2_regularization: float


def transform_target(mode: str, target: np.ndarray, baseline: np.ndarray, capacity: np.ndarray) -> np.ndarray:
    """객실 수 target을 후보 mode에 맞는 직접값·잔차·점유율 학습값으로 바꾼다.

    지원하지 않는 mode는 ``ValueError``로 거부하며 0 수용량은 분모 1로
    보호해 무한값이 학습에 유입되지 않게 한다.
    """

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
    """후보의 raw 출력을 객실 수로 복원하고 0과 물리 수용량 사이로 제한한다."""

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
    """series별 일별 오차를 paired block 재표집해 경쟁 모델 대비 CI를 계산한다.

    빈 series, 잘못된 열 번호 또는 유효하지 않은 표본 수는 numpy 오류로
    실패하며 고정 seed가 같은 입력의 재현성을 보장한다.
    """

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
