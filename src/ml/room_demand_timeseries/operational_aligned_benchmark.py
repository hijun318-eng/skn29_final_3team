"""2.2와 4.0을 동일 행으로 재학습하고 운영 특징의 순수 효과를 비교한다."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .contracts import FEATURE_COLUMNS
from .operational_candidate import CandidateArtifactWriter
from .operational_contracts import OPERATIONAL_FEATURE_COLUMNS
from .operational_evaluation import error_metrics
from .operational_governance import OperationalDataGate
from .operational_metrics import DemandMetricSuite, METRIC_CONTRACT_VERSION
from .operational_self_evaluation import OperationalSelfEvaluator
from .operational_statistical_validation import PairedBaselineValidator
from .operational_training import CANDIDATES, OperationalTrainer
from .train import TimeSeriesTrainer


V22_RELEASE_CONFIG = {
    "name": "global_residual_squared_leaf31",
    "scope": "global",
    "loss": "squared_error",
    "target_mode": "residual_rate",
    "learning_rate": 0.045,
    "max_iter": 360,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 40,
    "l2_regularization": 2.0,
    "random_state": 20260826,
}
V40_RELEASE_CONFIG = next(
    config for config in CANDIDATES if config["name"] == "robust_leaf31"
)
IDENTITY_COLUMNS = [
    "property_id",
    "room_type_code",
    "cutoff_date",
    "target_date",
    "horizon_days",
]


class AlignedBenchmarkRunner:
    """공통 D+1~D+7 행에서 고정 설정 비교와 동일예산 특징 비교를 수행한다."""

    def __init__(self, *, bootstrap_samples: int = 500, random_seed: int = 20260901):
        if bootstrap_samples < 100:
            raise ValueError("bootstrap_samples must be at least 100")
        self.bootstrap_samples = bootstrap_samples
        self.random_seed = random_seed

    @staticmethod
    def _fingerprint(frame: pd.DataFrame) -> str:
        ordered = frame[IDENTITY_COLUMNS].sort_values(IDENTITY_COLUMNS)
        values = pd.util.hash_pandas_object(ordered, index=False).to_numpy()
        return hashlib.sha256(values.tobytes()).hexdigest()

    def _bootstrap_wape_improvement(
        self,
        frame: pd.DataFrame,
        candidate: np.ndarray,
        baseline: np.ndarray,
    ) -> dict[str, Any]:
        return PairedBaselineValidator(
            samples=self.bootstrap_samples,
            random_seed=self.random_seed,
        ).validate(frame, candidate, baseline)

    @staticmethod
    def _all_segments_better(
        frame: pd.DataFrame,
        candidate: np.ndarray,
        baseline: np.ndarray,
        columns: list[str],
    ) -> bool:
        evaluated = frame.assign(candidate=candidate, baseline=baseline)
        for _, group in evaluated.groupby(columns, sort=True):
            actual = group["target_rooms_sold"].astype(float).to_numpy()
            candidate_metrics = error_metrics(actual, group["candidate"].to_numpy())
            baseline_metrics = error_metrics(actual, group["baseline"].to_numpy())
            metric = "mae" if float(candidate_metrics["actual_mean"]) < 10 else "wape"
            if float(candidate_metrics[metric]) >= float(baseline_metrics[metric]):
                return False
        return True

    def _compare(
        self,
        frame: pd.DataFrame,
        candidate: np.ndarray,
        baseline: np.ndarray,
    ) -> dict[str, Any]:
        actual = frame["target_rooms_sold"].astype(float).to_numpy()
        comparison = DemandMetricSuite.compare(actual, candidate, baseline)
        candidate_metrics = comparison["candidate_metrics"]
        baseline_metrics = comparison["baseline_metrics"]
        bootstrap = self._bootstrap_wape_improvement(frame, candidate, baseline)
        return {
            "metric_contract_version": METRIC_CONTRACT_VERSION,
            "rows": int(len(frame)),
            "identity_sha256": self._fingerprint(frame),
            "candidate_metrics": candidate_metrics,
            "baseline_metrics": baseline_metrics,
            "relative_improvement": comparison["relative_improvement"],
            "absolute_reduction": comparison["absolute_reduction"],
            "paired_cutoff_bootstrap": bootstrap,
            "overall_better": bool(
                float(candidate_metrics["wape"]) < float(baseline_metrics["wape"])
            ),
            "all_horizons_better": self._all_segments_better(
                frame, candidate, baseline, ["horizon_days"]
            ),
            "all_properties_better": self._all_segments_better(
                frame, candidate, baseline, ["property_id"]
            ),
            "statistically_better": bool(bootstrap["statistically_better"]),
        }

    @staticmethod
    def _comparison_pass(result: dict[str, Any]) -> bool:
        return bool(
            result["overall_better"]
            and result["all_horizons_better"]
            and result["all_properties_better"]
            and result["statistically_better"]
        )

    def run(
        self,
        train: pd.DataFrame,
        validation: pd.DataFrame,
        test_a: pd.DataFrame,
        test_b: pd.DataFrame,
        *,
        data_is_synthetic: bool | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """같은 네 split을 사용해 두 비교를 실행하고 모델과 보고서를 반환한다."""

        datasets = {
            "TRAIN": train,
            "VALIDATION": validation,
            "TEST_A": test_a,
            "TEST_B": test_b,
        }
        aligned_contract = OperationalDataGate.validate_aligned_splits(datasets)
        combined = pd.concat([train, validation], ignore_index=True)

        fixed_v22 = TimeSeriesTrainer().fit_candidate(combined, V22_RELEASE_CONFIG)
        fixed_v40, fixed_validation = OperationalTrainer().fit_final(
            train,
            validation,
            {"config": V40_RELEASE_CONFIG},
        )

        historical_trainer = OperationalTrainer(
            feature_columns=FEATURE_COLUMNS,
            model_version="aligned-historical-feature-hgbr",
        )
        operational_trainer = OperationalTrainer(
            feature_columns=OPERATIONAL_FEATURE_COLUMNS,
            model_version="aligned-operational-feature-hgbr",
        )
        historical_selected, historical_trials = historical_trainer.select(
            train, validation
        )
        operational_selected, operational_trials = operational_trainer.select(
            train, validation
        )
        historical_ablation = historical_trainer.fit_candidate(
            combined, historical_selected["config"]
        )
        operational_ablation, operational_validation = operational_trainer.fit_final(
            train,
            validation,
            operational_selected,
        )
        operational_development = operational_trainer.fit_candidate(
            train, operational_selected["config"]
        )
        operational_development.interval_quantiles = (
            operational_trainer.calibrate_intervals(
                operational_development, validation
            )
        )
        if data_is_synthetic is None:
            data_is_synthetic = any(
                "signal_is_synthetic" not in frame
                or bool(frame["signal_is_synthetic"].astype(bool).any())
                for frame in datasets.values()
            )
        self_evaluation = OperationalSelfEvaluator(
            bootstrap_samples=self.bootstrap_samples
        ).evaluate(
            operational_ablation,
            datasets,
            data_is_synthetic=data_is_synthetic,
            development_model=operational_development,
        )

        release_results: dict[str, Any] = {}
        ablation_results: dict[str, Any] = {}
        for name, frame in {"TEST_A": test_a, "TEST_B": test_b}.items():
            release_results[name] = self._compare(
                frame,
                fixed_v40.predict(frame),
                fixed_v22.predict(frame),
            )
            ablation_results[name] = self._compare(
                frame,
                operational_ablation.predict(frame),
                historical_ablation.predict(frame),
            )
        gates = {
            **{
                f"fixed_release_{name.lower()}": self._comparison_pass(result)
                for name, result in release_results.items()
            },
            **{
                f"equal_budget_ablation_{name.lower()}": self._comparison_pass(result)
                for name, result in ablation_results.items()
            },
        }
        report = {
            "comparison_mode": "aligned_same_rows_equal_budget",
            "metric_contract_version": METRIC_CONTRACT_VERSION,
            "aligned_contract": aligned_contract,
            "self_evaluation": self_evaluation,
            "fixed_release_comparison": {
                "candidate": "v4.0_fixed_config_retrained",
                "baseline": "v2.2_fixed_config_retrained",
                "candidate_validation": fixed_validation,
                "results": release_results,
            },
            "equal_budget_feature_ablation": {
                "candidate": "operational_features",
                "baseline": "historical_features",
                "target": "target_occupancy_rate",
                "candidate_count_per_side": len(CANDIDATES),
                "historical_selected": historical_selected["config"],
                "operational_selected": operational_selected["config"],
                "historical_trial_count": len(historical_trials),
                "operational_trial_count": len(operational_trials),
                "candidate_validation": operational_validation,
                "results": ablation_results,
            },
            "approval_gates": gates,
            "benchmark_approved": bool(all(gates.values())),
            "production_approved": False,
        }
        models = {
            "v22_fixed": fixed_v22,
            "v40_fixed": fixed_v40,
            "historical_ablation": historical_ablation,
            "operational_ablation": operational_ablation,
        }
        return report, models


def _load(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["cutoff_date", "target_date"])


def main() -> None:
    """네 시간 split을 읽어 정렬 비교 모델과 평가 증거를 저장한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--test-a", type=Path, required=True)
    parser.add_argument("--test-b", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest_bytes = args.dataset_manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    report, models = AlignedBenchmarkRunner().run(
        _load(args.train),
        _load(args.validation),
        _load(args.test_a),
        _load(args.test_b),
        data_is_synthetic=bool(manifest.get("synthetic_only", True)),
    )
    report["dataset_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    report["data_is_synthetic"] = manifest.get("synthetic_only")
    CandidateArtifactWriter().write(
        args.output_dir,
        report,
        models,
        manifest,
        selected_config=report["equal_budget_feature_ablation"][
            "operational_selected"
        ],
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
