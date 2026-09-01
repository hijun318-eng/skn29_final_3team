"""운영형 예측을 전체·호텔·객실유형·예측일별 기준선과 비교한다."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .operational_contracts import TARGET_CAPACITY_COLUMN
from .operational_metrics import DemandMetricSuite, METRIC_CONTRACT_VERSION
from .operational_modeling import OperationalDemandModel


def error_metrics(
    actual: np.ndarray, prediction: np.ndarray
) -> dict[str, float | int | None]:
    """공통 계약으로 점 예측 지표를 계산하는 하위 호환 진입점이다."""

    return DemandMetricSuite.point_metrics(actual, prediction)


def baseline_prediction(frame: pd.DataFrame) -> np.ndarray:
    """목표일 기준 최근 4주 동일 요일 평균을 판매 가능 객실 범위로 제한한다."""

    baseline = frame["target_same_weekday_mean_4w"].astype(float).to_numpy()
    capacity = frame[TARGET_CAPACITY_COLUMN].astype(float).to_numpy()
    return np.clip(baseline, 0.0, capacity)


def evaluate_operational_model(
    model: OperationalDemandModel,
    frame: pd.DataFrame,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    """전체와 주요 세그먼트에서 모델·기준선 오차 및 승인 가능 여부를 반환한다."""

    actual = frame["target_rooms_sold"].astype(float).to_numpy()
    prediction = model.predict(frame)
    baseline = baseline_prediction(frame)
    groups: dict[str, pd.DataFrame] = {}
    group_specs = {
        "horizon": ["horizon_days"],
        "property": ["property_id"],
        "room_type": ["property_id", "room_type_code"],
        "property_horizon": ["property_id", "horizon_days"],
    }
    evaluated = frame.assign(prediction=prediction, baseline_prediction=baseline)
    for name, columns in group_specs.items():
        records = []
        for keys, subset in evaluated.groupby(columns, sort=True):
            values = keys if isinstance(keys, tuple) else (keys,)
            comparison = DemandMetricSuite.compare(
                subset["target_rooms_sold"],
                subset["prediction"],
                subset["baseline_prediction"],
            )
            model_metrics = comparison["candidate_metrics"]
            base_metrics = comparison["baseline_metrics"]
            records.append(
                {
                    **dict(zip(columns, values)),
                    **model_metrics,
                    "baseline_wape": base_metrics["wape"],
                    "baseline_mae": base_metrics["mae"],
                    "baseline_rmse": base_metrics["rmse"],
                    "wape_improvement": comparison["relative_improvement"]["wape"],
                    "mae_improvement": comparison["relative_improvement"]["mae"],
                    "rmse_improvement": comparison["relative_improvement"]["rmse"],
                    "better_than_baseline": (
                        model_metrics["mae"] < base_metrics["mae"]
                        if model_metrics["actual_mean"] < 10
                        else model_metrics["wape"] < base_metrics["wape"]
                    ),
                }
            )
        groups[name] = pd.DataFrame(records)
    overall_comparison = DemandMetricSuite.compare(actual, prediction, baseline)
    overall = overall_comparison["candidate_metrics"]
    overall_baseline = overall_comparison["baseline_metrics"]
    room_types = groups["room_type"]
    high_volume = room_types.loc[room_types["actual_mean"] >= 10]
    low_volume = room_types.loc[room_types["actual_mean"] < 10]
    return {
        "metric_contract_version": METRIC_CONTRACT_VERSION,
        "metrics": overall,
        "baseline_metrics": overall_baseline,
        "baseline_improvement": overall_comparison["relative_improvement"]["wape"],
        "baseline_improvement_by_metric": overall_comparison[
            "relative_improvement"
        ],
        "all_horizons_better_than_baseline": bool(
            groups["horizon"]["better_than_baseline"].all()
        ),
        "all_properties_better_than_baseline": bool(
            groups["property"]["better_than_baseline"].all()
        ),
        "approved_room_type_count": int(room_types["better_than_baseline"].sum()),
        "room_type_count": int(len(room_types)),
        "worst_high_volume_room_type_wape": (
            float(high_volume["wape"].max()) if not high_volume.empty else None
        ),
        "worst_low_volume_room_type_mae": (
            float(low_volume["mae"].max()) if not low_volume.empty else None
        ),
    }, groups
