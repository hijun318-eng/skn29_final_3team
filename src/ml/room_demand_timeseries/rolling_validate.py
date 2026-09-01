"""시간 순서가 고정된 rolling-origin fold로 후보의 기간 안정성을 검증한다."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .evaluation_metrics import evaluate_model
from .train import TimeSeriesTrainer


@dataclass(frozen=True)
class RollingFold:
    """rolling 평가 한 회차의 이름, 학습 종료일과 validation 범위를 표현한다."""

    name: str
    train_end: str
    validation_start: str
    validation_end: str


FOLDS = (
    RollingFold("F1", "2021-12-21", "2022-01-01", "2022-06-21"),
    RollingFold("F2", "2022-12-21", "2023-01-01", "2023-06-21"),
    RollingFold("F3", "2023-12-21", "2024-01-01", "2024-06-21"),
)


class RollingOriginValidator:
    """각 과거 cutoff fold를 재학습·평가해 평균과 최악 성능 변동을 집계한다."""

    def run(
        self,
        development: pd.DataFrame,
        config: dict[str, Any],
        blend_weight: float,
    ) -> dict[str, Any]:
        """development 표와 선택 config로 모든 fold report와 안정성 요약을 반환한다.

        어느 fold의 학습 또는 validation 행이 비면 ``ValueError``로 중단하며
        미래 fold 데이터를 과거 학습에 포함하지 않는다.
        """

        trainer = TimeSeriesTrainer()
        records = []
        for fold in FOLDS:
            train = development.loc[
                development["cutoff_date"] <= pd.Timestamp(fold.train_end)
            ].copy()
            validation = development.loc[
                development["cutoff_date"].between(
                    pd.Timestamp(fold.validation_start),
                    pd.Timestamp(fold.validation_end),
                )
            ].copy()
            if train.empty or validation.empty:
                raise ValueError(f"rolling fold is empty: {fold.name}")
            model = trainer.fit_candidate(train, config)
            model.blend_weight = blend_weight
            report, _ = evaluate_model(model, validation)
            records.append(
                {
                    "fold": fold.name,
                    "train_end": fold.train_end,
                    "validation_start": fold.validation_start,
                    "validation_end": fold.validation_end,
                    "train_rows": int(len(train)),
                    "validation_rows": int(len(validation)),
                    **report["metrics"],
                    "best_baseline_name": report["best_baseline_name"],
                    "baseline_wape": report["baseline_metrics"]["wape"],
                    "baseline_improvement": report["baseline_improvement"],
                    "baseline_wape_by_name": {
                        name: metrics["wape"]
                        for name, metrics in report[
                            "baseline_metrics_by_name"
                        ].items()
                    },
                    "improved_horizons_d1_d7": report[
                        "improved_horizons_d1_d7"
                    ],
                    "worst_high_volume_room_type_wape": report[
                        "worst_high_volume_room_type_wape"
                    ],
                    "worst_low_volume_room_type_mae": report[
                        "worst_low_volume_room_type_mae"
                    ],
                }
            )
        wapes = np.asarray([record["wape"] for record in records], dtype=float)
        improvements = np.asarray(
            [record["baseline_improvement"] for record in records], dtype=float
        )
        return {
            "folds": records,
            "summary": {
                "fold_count": len(records),
                "mean_wape": float(wapes.mean()),
                "std_wape": float(wapes.std(ddof=0)),
                "worst_fold_wape": float(wapes.max()),
                "wape_coefficient_of_variation": float(
                    wapes.std(ddof=0) / wapes.mean()
                ),
                "mean_baseline_improvement": float(improvements.mean()),
                "all_folds_improve_baseline": bool((improvements > 0).all()),
            },
        }


def main() -> None:
    """trainer 분할과 model manifest를 읽어 rolling-origin CSV·JSON을 기록한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--trainer-dir", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    frames = [
        pd.read_csv(
            args.trainer_dir / name,
            parse_dates=["cutoff_date", "target_date"],
        )
        for name in ("train.csv.gz", "validation.csv.gz")
    ]
    development = pd.concat(frames, ignore_index=True)
    manifest = json.loads(args.model_manifest.read_text(encoding="utf-8"))
    result = RollingOriginValidator().run(
        development,
        manifest["selected_config"],
        float(manifest["blend_weight"]),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(result["folds"]).to_csv(
        args.output_dir / "rolling_origin_metrics.csv", index=False
    )
    (args.output_dir / "rolling_origin_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
