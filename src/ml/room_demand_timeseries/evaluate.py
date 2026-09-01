"""trainer와 분리된 private label로 모델 성능을 계산하고 승인 gate를 판정한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from .contracts import IDENTITY_COLUMNS
from .evaluation_metrics import evaluate_model
from .modeling import TimeSeriesDemandModel


class IndependentEvaluator:
    """비공개 feature·label을 일대일 결합해 모델 외부 평가 증거를 저장한다."""

    def load_private_split(
        self,
        evaluator_dir: Path,
        split_name: str,
    ) -> pd.DataFrame:
        """지정 split의 feature와 label을 식별자로 결합해 완전한 평가표를 반환한다.

        행이 빠지거나 중복되어 일대일 결합할 수 없으면 ``ValueError``로
        평가를 중단한다.
        """

        features = pd.read_csv(
            evaluator_dir / f"{split_name}_features.csv.gz",
            parse_dates=["cutoff_date", "target_date"],
        )
        labels = pd.read_csv(
            evaluator_dir / f"{split_name}_labels.csv.gz",
            parse_dates=["cutoff_date", "target_date"],
        )
        merged = features.merge(
            labels,
            on=IDENTITY_COLUMNS,
            how="inner",
            validate="one_to_one",
        )
        if len(merged) != len(features) or len(merged) != len(labels):
            raise ValueError(f"{split_name} feature-label join is incomplete")
        return merged

    def evaluate_split(
        self,
        model: TimeSeriesDemandModel,
        frame: pd.DataFrame,
        output_dir: Path,
    ) -> dict[str, Any]:
        """모델을 평가해 전체·그룹 metric 파일을 쓰고 report 객체를 반환한다."""

        report, groups = evaluate_model(model, frame, bootstrap_samples=1000)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, group in groups.items():
            group.to_csv(output_dir / f"metrics_by_{name}.csv", index=False)
        (output_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report


def gate(report: dict[str, Any]) -> dict[str, Any]:
    """품질·baseline·범위 기준을 적용해 PASS, 조건부 통과 또는 거절을 반환한다."""

    hard_checks = {
        "wape_lte_18pct": report["metrics"]["wape"] <= 0.18,
        "baseline_improvement_gte_8pct": report[
            "baseline_improvement"
        ] >= 0.08,
        "improved_horizons_gte_5_of_7": report[
            "improved_horizons_d1_d7"
        ] >= 5,
        "max_horizon_relative_degradation_lte_10pct": report[
            "max_horizon_relative_degradation_d1_d7"
        ] <= 0.10,
        "high_volume_room_type_wape_lte_30pct": report[
            "worst_high_volume_room_type_wape"
        ] <= 0.30,
        "low_volume_room_type_mae_lte_3_rooms": report[
            "worst_low_volume_room_type_mae"
        ] <= 3.0,
        "horizon_10_wape_lte_20pct": report["horizon_10_wape"] <= 0.20,
        "absolute_bias_lte_5pct": abs(report["metrics"]["bias"]) <= 0.05,
        "clipped_negative_zero": report["clipped_negative"] == 0,
        "clipped_above_capacity_zero": report[
            "clipped_above_capacity"
        ] == 0,
    }
    hard_pass = all(hard_checks.values())
    raw_range_pass = (
        report["raw_negative"] == 0
        and report["raw_above_capacity"] == 0
    )
    status = (
        "PASS"
        if hard_pass and raw_range_pass
        else "CONDITIONAL_PASS"
        if hard_pass
        else "REJECT"
    )
    return {
        "status": status,
        "hard_checks": hard_checks,
        "raw_range_pass": raw_range_pass,
    }


def main() -> None:
    """동결 모델의 두 private split을 평가하고 통합 승인 결정을 기록한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--evaluator-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()

    model: TimeSeriesDemandModel = joblib.load(args.artifact_dir / "model.joblib")
    evaluator = IndependentEvaluator()
    reports: dict[str, dict[str, Any]] = {}
    gates: dict[str, dict[str, Any]] = {}
    for split in ("test_a", "test_b"):
        frame = evaluator.load_private_split(args.evaluator_dir, split)
        reports[split] = evaluator.evaluate_split(
            model, frame, args.report_dir / split
        )
        gates[split] = gate(reports[split])
    degradation = (
        reports["test_b"]["metrics"]["wape"]
        / reports["test_a"]["metrics"]["wape"]
        - 1.0
    )
    statuses = [value["status"] for value in gates.values()]
    decision = (
        "REJECT"
        if "REJECT" in statuses or degradation > 0.20
        else "CONDITIONAL_PASS"
        if "CONDITIONAL_PASS" in statuses
        else "PASS"
    )
    approval = {
        "decision": decision,
        "split_gates": gates,
        "test_b_relative_wape_degradation": degradation,
        "test_seen_by_trainer": False,
        "september_observed_values_used": False,
        "statistically_uncertain": any(
            report["bootstrap"]["statistically_uncertain"]
            for report in reports.values()
        ),
    }
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "approval_decision.json").write_text(
        json.dumps(approval, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.artifact_dir / "model.approval.json").write_text(
        json.dumps(approval, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"reports": reports, "approval": approval}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
