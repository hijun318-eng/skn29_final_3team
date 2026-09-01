"""운영 자체평가의 그룹 집계·일반화·승인 판정 보조 함수다."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from .operational_metrics import DemandMetricSuite


SPLIT_NAMES = ("TRAIN", "VALIDATION", "TEST_A", "TEST_B")
MAX_WAPE_RELATIVE_DEGRADATION = 0.50


def _positive(value: float | None) -> bool:
    return value is not None and value > 0.0


def _group_better(row: Mapping[str, Any]) -> bool:
    metric = "mae" if float(row["actual_mean"]) < 10.0 else "wape"
    return _positive(row["baseline_improvement"][metric])


def group_metrics(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """예측 기간·호텔·객실·수요구간·월·주말 단위 지표를 집계한다."""

    enriched = frame.assign(
        demand_band=pd.cut(
            frame["target_rooms_sold"],
            bins=[-np.inf, 10.0, 30.0, np.inf],
            labels=["LOW", "MEDIUM", "HIGH"],
            right=False,
        ),
        target_month=pd.to_datetime(frame["target_date"]).dt.month,
        target_is_weekend=pd.to_datetime(frame["target_date"]).dt.dayofweek >= 5,
    )
    specs = {
        "horizon": ["horizon_days"],
        "property": ["property_id"],
        "room_type": ["property_id", "room_type_code"],
        "property_horizon": ["property_id", "horizon_days"],
        "demand_band": ["demand_band"],
        "month": ["target_month"],
        "weekend": ["target_is_weekend"],
    }
    output: dict[str, list[dict[str, Any]]] = {}
    for name, columns in specs.items():
        rows: list[dict[str, Any]] = []
        for keys, group in enriched.groupby(columns, sort=True, observed=True):
            values = keys if isinstance(keys, tuple) else (keys,)
            comparison = DemandMetricSuite.compare(
                group["target_rooms_sold"],
                group["predicted_rooms"],
                group["baseline_predicted_rooms"],
            )
            rows.append(
                {
                    **{column: str(value) for column, value in zip(columns, values)},
                    **comparison["candidate_metrics"],
                    "baseline_metrics": comparison["baseline_metrics"],
                    "baseline_improvement": comparison["relative_improvement"],
                }
            )
        output[name] = rows
    return output


def largest_errors(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """절대오차가 큰 상위 10개 예측 행을 재현 가능한 순서로 반환한다."""

    columns = [
        "property_id",
        "room_type_code",
        "cutoff_date",
        "target_date",
        "horizon_days",
        "target_rooms_sold",
        "predicted_rooms",
    ]
    ranked = frame.assign(
        absolute_error=(frame["predicted_rooms"] - frame["target_rooms_sold"]).abs()
    ).nlargest(10, "absolute_error")
    records = ranked[[*columns, "absolute_error"]].copy()
    for column in ("cutoff_date", "target_date"):
        records[column] = pd.to_datetime(records[column]).dt.date.astype(str)
    return records.to_dict(orient="records")


def generalization_report(split_reports: Mapping[str, Any]) -> dict[str, Any]:
    """Train 대비 Validation·Test 오차 차이와 상대 WAPE 악화를 계산한다."""

    train = split_reports["TRAIN"]["metrics"]
    output: dict[str, Any] = {}
    for name in ("VALIDATION", "TEST_A", "TEST_B"):
        current = split_reports[name]["metrics"]
        output[name] = {
            f"{metric}_absolute_gap": float(current[metric] - train[metric])
            for metric in ("mae", "rmse", "wape")
        }
        output[name]["wape_relative_degradation"] = (
            float(current["wape"] / train["wape"] - 1.0)
            if train["wape"]
            else None
        )
    return output


def approval_gates(
    reports: Mapping[str, Any], generalization: Mapping[str, Any]
) -> dict[str, bool]:
    """출처·누수·기준선·통계·구간·일반화 기술 게이트를 판정한다."""

    gates: dict[str, bool] = {}
    for name in SPLIT_NAMES:
        checks = reports[name]["data_checks"]
        gates[f"{name.lower()}_provenance"] = bool(
            checks["point_in_time_provenance_passed"]
        )
        gates[f"{name.lower()}_label_proxy"] = bool(
            checks["label_proxy_audit"]["passed"]
        )
    for name in ("TEST_A", "TEST_B"):
        report = reports[name]
        gates[f"{name.lower()}_overall_baseline"] = _positive(
            report["baseline_improvement"]["wape"]
        )
        gates[f"{name.lower()}_statistical"] = bool(
            report["paired_cutoff_bootstrap"]["statistically_better"]
        )
        gates[f"{name.lower()}_all_horizons"] = all(
            _group_better(row) for row in report["group_metrics"]["horizon"]
        )
        gates[f"{name.lower()}_all_properties"] = all(
            _group_better(row) for row in report["group_metrics"]["property"]
        )
        gates[f"{name.lower()}_room_type_thresholds"] = all(
            _group_better(row)
            and (
                float(row["wape"]) <= 0.30
                if float(row["actual_mean"]) >= 10.0
                else float(row["mae"]) <= 3.0
            )
            for row in report["group_metrics"]["room_type"]
        )
        gates[f"{name.lower()}_interval_80"] = bool(
            report["prediction_intervals"]["80"]["empirical_coverage"] >= 0.70
        )
        gates[f"{name.lower()}_interval_95"] = bool(
            report["prediction_intervals"]["95"]["empirical_coverage"] >= 0.90
        )
    gates["generalization_is_finite"] = all(
        np.isfinite(value)
        for report in generalization.values()
        for value in report.values()
        if value is not None
    )
    gates["generalization_wape_within_guardrail"] = all(
        value["wape_relative_degradation"] is None
        or value["wape_relative_degradation"]
        <= MAX_WAPE_RELATIVE_DEGRADATION
        for value in generalization.values()
    )
    return gates
