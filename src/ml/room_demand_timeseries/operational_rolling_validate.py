"""최근 월을 순서대로 전진시키며 운영형 모델과 동일요일 기준선을 검증한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .operational_evaluation import evaluate_operational_model
from .operational_training import OperationalTrainer


class RecentRollingValidator:
    """최근 3~6개 완전 월을 학습 종료 이후 순차 검증한다."""

    def run(
        self,
        development: pd.DataFrame,
        config: dict[str, Any],
        *,
        months: int = 6,
    ) -> dict[str, Any]:
        """최근 완전 월을 순서대로 분리해 기간별 기준선 우위를 검증한다."""

        if not 3 <= months <= 6:
            raise ValueError("rolling validation months must be between 3 and 6")
        frame = development.copy()
        frame["cutoff_date"] = pd.to_datetime(frame["cutoff_date"])
        last_month = frame["cutoff_date"].max().to_period("M")
        periods = pd.period_range(end=last_month, periods=months, freq="M")
        trainer = OperationalTrainer()
        folds = []
        for period in periods:
            start = period.start_time
            end = min(period.end_time.normalize(), frame["cutoff_date"].max())
            train = frame.loc[frame["cutoff_date"] < start].copy()
            validation = frame.loc[frame["cutoff_date"].between(start, end)].copy()
            if train.empty or validation.empty:
                raise ValueError(f"rolling fold is empty: {period}")
            model = trainer.fit_candidate(train, config)
            report, groups = evaluate_operational_model(model, validation)
            folds.append(
                {
                    "month": str(period),
                    "train_end": (
                        start - pd.Timedelta(1, unit="D")
                    ).date().isoformat(),
                    "validation_start": start.date().isoformat(),
                    "validation_end": end.date().isoformat(),
                    "train_rows": int(len(train)),
                    "validation_rows": int(len(validation)),
                    **report,
                    "horizon_metrics": groups["horizon"].to_dict(orient="records"),
                    "property_metrics": groups["property"].to_dict(orient="records"),
                    "room_type_metrics": groups["room_type"].to_dict(orient="records"),
                }
            )
        return {
            "folds": folds,
            "summary": {
                "fold_count": len(folds),
                "mean_wape": sum(fold["metrics"]["wape"] for fold in folds) / len(folds),
                "all_folds_better_than_baseline": all(
                    fold["baseline_improvement"] > 0 for fold in folds
                ),
                "all_horizons_better_than_baseline": all(
                    fold["all_horizons_better_than_baseline"] for fold in folds
                ),
                "all_properties_better_than_baseline": all(
                    fold["all_properties_better_than_baseline"] for fold in folds
                ),
            },
        }


def main() -> None:
    """개발 자료에서 최근 월 순차 검증 보고서를 생성한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--months", type=int, default=6)
    args = parser.parse_args()
    frame = pd.read_csv(args.development, parse_dates=["cutoff_date", "target_date"])
    manifest = json.loads(args.model_manifest.read_text(encoding="utf-8"))
    report = RecentRollingValidator().run(
        frame, manifest["selected_config"], months=args.months
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
