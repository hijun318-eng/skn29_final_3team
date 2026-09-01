"""기존 운영 모델과 신규 후보를 같은 보유 데이터에서 비교해 승인 게이트를 판정한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .operational_evaluation import baseline_prediction, error_metrics
from .operational_modeling import OperationalDemandModel


GROUPS = {
    "horizon": ["horizon_days"],
    "property": ["property_id"],
    "room_type": ["property_id", "room_type_code"],
}


def _group_comparison(
    frame: pd.DataFrame,
    new_prediction: np.ndarray,
    old_prediction: np.ndarray,
    baseline: np.ndarray,
) -> dict[str, pd.DataFrame]:
    evaluated = frame.assign(
        new_prediction=new_prediction,
        old_prediction=old_prediction,
        baseline_prediction=baseline,
    )
    outputs: dict[str, pd.DataFrame] = {}
    for group_name, columns in GROUPS.items():
        records = []
        for keys, subset in evaluated.groupby(columns, sort=True):
            values = keys if isinstance(keys, tuple) else (keys,)
            actual = subset["target_rooms_sold"].to_numpy()
            new = error_metrics(actual, subset["new_prediction"].to_numpy())
            old = error_metrics(actual, subset["old_prediction"].to_numpy())
            base = error_metrics(actual, subset["baseline_prediction"].to_numpy())
            high_volume = float(new["actual_mean"]) >= 10.0
            threshold_pass = (
                float(new["wape"]) <= 0.30
                if high_volume
                else float(new["mae"]) <= 3.0
            )
            comparison_pass = (
                float(new["wape"]) < float(old["wape"])
                and float(new["wape"]) < float(base["wape"])
                if high_volume
                else float(new["mae"]) < float(old["mae"])
                and float(new["mae"]) < float(base["mae"])
            )
            records.append(
                {
                    **dict(zip(columns, values)),
                    **new,
                    "old_wape": old["wape"],
                    "old_mae": old["mae"],
                    "baseline_wape": base["wape"],
                    "baseline_mae": base["mae"],
                    "volume_class": "HIGH" if high_volume else "LOW",
                    "threshold_pass": bool(threshold_pass),
                    "comparison_pass": bool(comparison_pass),
                    "approval_pass": bool(threshold_pass and comparison_pass),
                }
            )
        outputs[group_name] = pd.DataFrame(records)
    return outputs


def _interval_coverage(
    model: OperationalDemandModel,
    frame: pd.DataFrame,
    prediction: np.ndarray,
) -> dict[str, float | bool]:
    intervals = model.prediction_intervals(frame, prediction)
    actual = frame["target_rooms_sold"].astype(float).to_numpy()
    coverage_80 = np.mean(
        [row["lower_80"] <= value <= row["upper_80"] for row, value in zip(intervals, actual)]
    )
    coverage_95 = np.mean(
        [row["lower_95"] <= value <= row["upper_95"] for row, value in zip(intervals, actual)]
    )
    return {
        "coverage_80": float(coverage_80),
        "coverage_95": float(coverage_95),
        "coverage_pass": bool(coverage_80 >= 0.75 and coverage_95 >= 0.90),
    }


def _flatness_check(frame: pd.DataFrame, prediction: np.ndarray) -> dict[str, Any]:
    grouped = frame.assign(
        prediction=prediction,
        displayed_prediction=np.round(prediction, 1),
    ).groupby(["cutoff_date", "property_id", "room_type_code"], sort=True)
    exact_flat_rate = float((grouped["prediction"].std().fillna(0.0) < 1e-9).mean())
    displayed_flat_rate = float((grouped["displayed_prediction"].nunique() == 1).mean())
    return {
        "windows": int(grouped.ngroups),
        "exact_flat_window_rate": exact_flat_rate,
        "one_decimal_flat_window_rate": displayed_flat_rate,
        "flatness_pass": bool(exact_flat_rate <= 0.01 and displayed_flat_rate <= 0.05),
    }


def compare_release(
    new_model: OperationalDemandModel,
    old_model: Any,
    test: pd.DataFrame,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    """신규·기존·동일요일 기준선을 같은 보유기간에서 비교한다."""

    actual = test["target_rooms_sold"].astype(float).to_numpy()
    new_prediction = new_model.predict(test)
    old_prediction = old_model.predict(test)
    baseline = baseline_prediction(test)
    groups = _group_comparison(test, new_prediction, old_prediction, baseline)
    new_metrics = error_metrics(actual, new_prediction)
    old_metrics = error_metrics(actual, old_prediction)
    baseline_metrics = error_metrics(actual, baseline)
    interval = _interval_coverage(new_model, test, new_prediction)
    flatness = _flatness_check(test, new_prediction)
    gates = {
        "overall_better_than_old": new_metrics["wape"] < old_metrics["wape"],
        "overall_better_than_baseline": new_metrics["wape"] < baseline_metrics["wape"],
        "all_horizons_approved": bool(groups["horizon"]["approval_pass"].all()),
        "all_properties_approved": bool(groups["property"]["approval_pass"].all()),
        "all_room_types_approved": bool(groups["room_type"]["approval_pass"].all()),
        "interval_coverage_approved": bool(interval["coverage_pass"]),
        "flatness_approved": bool(flatness["flatness_pass"]),
    }
    return {
        "new_model_version": new_model.model_version,
        "old_model_version": old_model.model_version,
        "test_period": {
            "cutoff_start": str(pd.to_datetime(test["cutoff_date"]).min().date()),
            "cutoff_end": str(pd.to_datetime(test["cutoff_date"]).max().date()),
            "rows": int(len(test)),
        },
        "new_metrics": new_metrics,
        "old_metrics": old_metrics,
        "baseline_metrics": baseline_metrics,
        "interval_coverage": interval,
        "flatness": flatness,
        "approval_gates": gates,
        "candidate_release_approved_on_synthetic_holdout": bool(all(gates.values())),
        "production_approved": False,
        "production_block_reason": "운영 관측 데이터 순차 검증이 없어 합성 데이터 조건부 검증만 완료",
    }, groups


def main() -> None:
    """동결 모델과 평가 자료를 읽어 배포 비교 증거를 저장한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--new-artifact", type=Path, required=True)
    parser.add_argument("--old-artifact", type=Path, required=True)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    test = pd.read_csv(args.test, parse_dates=["cutoff_date", "target_date"])
    report, groups = compare_release(
        joblib.load(args.new_artifact),
        joblib.load(args.old_artifact),
        test,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "release_comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name, table in groups.items():
        table.to_csv(args.output_dir / f"test_by_{name}.csv", index=False)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
