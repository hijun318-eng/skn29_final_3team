from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .evaluate import gate
from .evaluation_metrics import evaluate_model
from .train import TimeSeriesTrainer


class ValidationReporter:
    def run(
        self,
        trainer_dir: Path,
        model_manifest_path: Path,
        output_dir: Path,
    ) -> dict[str, Any]:
        train = pd.read_csv(
            trainer_dir / "train.csv.gz",
            parse_dates=["cutoff_date", "target_date"],
        )
        validation = pd.read_csv(
            trainer_dir / "validation.csv.gz",
            parse_dates=["cutoff_date", "target_date"],
        )
        manifest = json.loads(model_manifest_path.read_text(encoding="utf-8"))
        model = TimeSeriesTrainer().fit_candidate(
            train, manifest["selected_config"]
        )
        model.blend_weight = float(manifest["blend_weight"])
        report, groups = evaluate_model(
            model, validation, bootstrap_samples=1000
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in groups.items():
            frame.to_csv(output_dir / f"metrics_by_{name}.csv", index=False)
        result = {
            "evaluation_role": "PRE_TEST_VALIDATION_ONLY",
            "fit_splits": ["TRAIN"],
            "evaluation_split": "VALIDATION",
            "test_or_hidden_opened": False,
            "report": report,
            "gate": gate(report),
        }
        (output_dir / "validation_report.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trainer-dir", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = ValidationReporter().run(
        args.trainer_dir, args.model_manifest, args.output_dir
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
