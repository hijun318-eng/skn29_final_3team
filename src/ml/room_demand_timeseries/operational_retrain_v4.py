"""V4를 purged Train·Validation·Test 기준으로 재학습하고 제출 증거를 저장한다."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from .operational_evaluation import baseline_prediction
from .operational_metrics import DemandMetricSuite, METRIC_CONTRACT_VERSION
from .operational_retrain_artifacts import RetrainArtifactWriter, sha256, write_json
from .operational_submission_evaluation import (
    OperationalSubmissionEvaluator,
    SubmissionSplitValidator,
)
from .operational_training import CANDIDATES, OperationalTrainer


LEARNING_CURVE_FRACTIONS = (0.25, 0.50, 0.75, 1.00)
V40_CONFIG_NAME = "robust_leaf31"


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["cutoff_date", "target_date"])

class OperationalV4Retrainer:
    """고정 V4 설정으로 재학습하고 재현 가능한 제출 묶음을 만든다."""

    def __init__(
        self,
        *,
        bootstrap_samples: int = 1000,
        inference_requests: int = 500,
    ) -> None:
        self.bootstrap_samples = bootstrap_samples
        self.inference_requests = inference_requests
        self.config = dict(
            next(config for config in CANDIDATES if config["name"] == V40_CONFIG_NAME)
        )
        self.trainer = OperationalTrainer()

    def run(
        self,
        train_path: Path,
        validation_path: Path,
        test_path: Path,
        dataset_manifest_path: Path,
        output_dir: Path,
    ) -> dict[str, Any]:
        """입력 hash를 고정하고 최종 모델·평가표·체크섬을 새 폴더에 기록한다."""

        if output_dir.exists():
            raise FileExistsError(f"output directory already exists: {output_dir}")
        raw_datasets = {
            "TRAIN": _read(train_path),
            "VALIDATION": _read(validation_path),
            "TEST": _read(test_path),
        }
        datasets, purge_report = SubmissionSplitValidator.purge_label_overlap(
            raw_datasets
        )
        split_contract = SubmissionSplitValidator.validate(datasets)
        train = datasets["TRAIN"]
        validation = datasets["VALIDATION"]
        test = datasets["TEST"]
        started = time.perf_counter()
        development_model = self.trainer.fit_candidate(train, self.config)
        development_model.interval_quantiles = self.trainer.calibrate_intervals(
            development_model, validation
        )
        final_model, validation_report = self.trainer.fit_final(
            train, validation, {"config": self.config}
        )
        fit_seconds = time.perf_counter() - started
        learning_curve = self._learning_curve(
            train, validation, development_model
        )
        evaluator = OperationalSubmissionEvaluator(
            bootstrap_samples=self.bootstrap_samples,
            inference_requests=self.inference_requests,
        )
        dataset_manifest_bytes = dataset_manifest_path.read_bytes()
        dataset_manifest = json.loads(dataset_manifest_bytes)
        evaluation, prediction_frames = evaluator.evaluate(
            development_model,
            final_model,
            datasets,
            learning_curve=learning_curve,
            data_is_synthetic=bool(dataset_manifest.get("synthetic_only", True)),
            purge_report=purge_report,
            actual_pms_evaluated=False,
        )
        output_dir.mkdir(parents=True)
        evaluation_dir = output_dir / "evaluation"
        evaluation_dir.mkdir()
        final_path = output_dir / "model.joblib"
        development_path = output_dir / "development_model.joblib"
        joblib.dump(final_model, final_path)
        joblib.dump(development_model, development_path)
        runtime = self._runtime_metadata()
        manifest = {
            "model_version": final_model.model_version,
            "model_type": "operational-point-in-time-hgbr",
            "selected_config": self.config,
            "metric_contract_version": METRIC_CONTRACT_VERSION,
            "split_contract": split_contract,
            "label_availability_purge": purge_report,
            "training_rows": int(len(train) + len(validation)),
            "train_rows": int(len(train)),
            "validation_rows": int(len(validation)),
            "test_rows": int(len(test)),
            "test_seen_by_trainer": False,
            "validation": validation_report,
            "fit_seconds": float(fit_seconds),
            "artifact_bytes": final_path.stat().st_size,
            "artifact_sha256": sha256(final_path),
            "development_artifact_sha256": sha256(development_path),
            "input_file_sha256": {
                "train": sha256(train_path),
                "validation": sha256(validation_path),
                "test": sha256(test_path),
                "dataset_manifest": hashlib.sha256(
                    dataset_manifest_bytes
                ).hexdigest(),
            },
            "source_dataset_sha256": dataset_manifest.get("source_sha256"),
            "signal_dataset_sha256": dataset_manifest.get("signal_sha256"),
            "synthetic_training_data": bool(
                dataset_manifest.get("synthetic_only", True)
            ),
            "training_runtime": runtime,
            "production_approved": False,
        }
        evaluation["model_artifact"] = {
            "bytes": manifest["artifact_bytes"],
            "sha256": manifest["artifact_sha256"],
        }
        evaluation["reproducibility"] = runtime
        evaluation["submission_checklist"]["model_size_and_hash"] = "PASS"
        evaluation["submission_checklist"]["commit_and_runtime_versions"] = (
            "PASS" if not runtime["git_dirty"] else "PARTIAL_GIT_DIRTY"
        )
        writer = RetrainArtifactWriter()
        writer.write_evaluation(evaluation_dir, evaluation, prediction_frames)
        write_json(output_dir / "model_manifest.json", manifest)
        write_json(output_dir / "training_config.json", self.config)
        writer.write_checksums(output_dir)
        return {"manifest": manifest, "evaluation": evaluation}

    def _learning_curve(
        self,
        train: pd.DataFrame,
        validation: pd.DataFrame,
        full_model: Any,
    ) -> list[dict[str, Any]]:
        dates = pd.Series(pd.to_datetime(train["cutoff_date"]).unique()).sort_values()
        output: list[dict[str, Any]] = []
        for fraction in LEARNING_CURVE_FRACTIONS:
            date_count = max(1, int(len(dates) * fraction))
            cutoff_end = pd.Timestamp(dates.iloc[date_count - 1])
            subset = train.loc[pd.to_datetime(train["cutoff_date"]) <= cutoff_end]
            started = time.perf_counter()
            model = (
                full_model
                if fraction == 1.0
                else self.trainer.fit_candidate(subset, self.config)
            )
            fit_seconds = None if fraction == 1.0 else time.perf_counter() - started
            prediction = model.predict(validation)
            comparison = DemandMetricSuite.compare(
                validation["target_rooms_sold"],
                prediction,
                baseline_prediction(validation),
            )
            output.append(
                {
                    "training_fraction": fraction,
                    "training_rows": int(len(subset)),
                    "training_cutoff_start": str(
                        pd.to_datetime(subset["cutoff_date"]).min().date()
                    ),
                    "training_cutoff_end": str(cutoff_end.date()),
                    "validation_rows": int(len(validation)),
                    "validation_metrics": comparison["candidate_metrics"],
                    "baseline_improvement": comparison["relative_improvement"],
                    "fit_seconds": (
                        float(fit_seconds) if fit_seconds is not None else None
                    ),
                    "model_reused": fraction == 1.0,
                }
            )
        return output

    @staticmethod
    def _runtime_metadata() -> dict[str, Any]:
        packages = {}
        for name in ("joblib", "numpy", "pandas", "scikit-learn", "scipy"):
            try:
                packages[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                packages[name] = None
        repository_root = Path(__file__).resolve().parents[3]
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repository_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {
            "git_commit": commit,
            "git_dirty": dirty,
            "python": platform.python_version(),
            "python_executable": Path(sys.executable).name,
            "platform": platform.platform(),
            "packages": packages,
        }

def main() -> None:
    """명령행 인수로 V4 재학습과 제출 평가 산출물 생성을 실행한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--inference-requests", type=int, default=500)
    args = parser.parse_args()
    result = OperationalV4Retrainer(
        bootstrap_samples=args.bootstrap_samples,
        inference_requests=args.inference_requests,
    ).run(
        args.train,
        args.validation,
        args.test,
        args.dataset_manifest,
        args.output_dir,
    )
    print(json.dumps(result["manifest"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
