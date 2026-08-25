from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


class OfficialMetricTableGenerator:
    """Normalize existing experiment results without retraining or redefining metrics."""

    def __init__(self) -> None:
        self.ml_dir = Path(__file__).resolve().parent
        self.no_show = self.ml_dir / "reservation_no_show" / "artifacts"
        self.demand = self.ml_dir / "room_demand_forecast" / "artifacts"

    def run(self) -> dict[str, object]:
        outputs = [
            self._no_show_models(),
            self._no_show_tuning(),
            self._demand_models(),
        ]
        no_show_profile = self._read_json(self.no_show / "data_profile.json")
        demand_profile = self._read_json(self.demand / "data_profile.json")
        manifest = {
            "status": "PASS",
            "metric_policy": {
                "classification_primary": "average_precision_score",
                "classification_secondary": [
                    "roc_auc_score",
                    "precision_score",
                    "recall_score",
                    "f1_score",
                    "brier_score_loss",
                    "confusion_matrix",
                ],
                "regression_primary": "mean_absolute_error",
                "regression_secondary": [
                    "sqrt(mean_squared_error)",
                    "r2_score",
                ],
                "business_secondary": ["recall_at_15", "precision_at_15", "lift_at_15", "wape"],
            },
            "official_reference": "https://scikit-learn.org/stable/modules/model_evaluation.html",
            "selection_rule": "Tune and select on VALIDATION; TEST is post-selection reporting only.",
            "data_basis": {
                "shared_training_dataset": False,
                "common_source_lineage": "BLOCKED_NOT_PROVEN",
                "reservation_no_show": {
                    "grain": "reservation_id",
                    "target": "is_no_show",
                    "label_rule_version": no_show_profile["label_rule_version"],
                    "source_no_show_rows": no_show_profile["source_no_show_rows"],
                    "split_rows": no_show_profile["split_rows"],
                    "activation_status": "BLOCKED_SOURCE_LABEL_REQUIRED",
                },
                "room_demand_forecast": {
                    "grain": "property_id,target_date,room_type_code,horizon_days",
                    "target": "rooms_sold",
                    "split_rows": {
                        name.upper(): demand_profile[name]["rows"]
                        for name in ("train", "validation", "test", "forecast")
                    },
                    "forecast_max_feature_null_rate": demand_profile["forecast"][
                        "max_feature_null_rate"
                    ],
                    "activation_status": "LOCAL_TECHNICAL_VALIDATION_ONLY",
                },
            },
            "unmeasured_gates": [
                "no_show_metric_confidence_intervals",
                "multi_seed_variance",
                "shared_source_snapshot_lineage",
                "deployed_latency_and_hard_timeout",
                "production_drift_baseline",
                "real_deidentified_external_validation",
            ],
            "outputs": [self._record(path) for path in outputs],
        }
        path = self.ml_dir / "artifacts" / "official_metric_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return manifest

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _no_show_models(self) -> Path:
        # Expected new artifact: baseline_candidate_metrics.csv
        baseline_path = self.no_show / "baseline_candidate_metrics.csv"
        if not baseline_path.exists():
            raise ValueError(f"Missing {baseline_path}")
        source = pd.read_csv(baseline_path)

        path = self.no_show / "official_model_comparison.csv"
        source.to_csv(path, index=False)
        return path

    def _no_show_tuning(self) -> Path:
        # Expected new artifact: top2_tuning_trials.csv
        tuning_path = self.no_show / "top2_tuning_trials.csv"
        if not tuning_path.exists():
            raise ValueError(f"Missing {tuning_path}")
        source = pd.read_csv(tuning_path)

        path = self.no_show / "official_tuning_comparison.csv"
        source.to_csv(path, index=False)
        return path

    def _demand_models(self) -> Path:
        # Expected new artifact: baseline_candidate_metrics.csv
        baseline_path = self.demand / "baseline_candidate_metrics.csv"
        if not baseline_path.exists():
            raise ValueError(f"Missing {baseline_path}")
        source = pd.read_csv(baseline_path)

        path = self.demand / "official_model_comparison.csv"
        source.to_csv(path, index=False)
        return path

    def _record(self, path: Path) -> dict[str, object]:
        return {
            "path": path.relative_to(self.ml_dir.parents[1]).as_posix(),
            "rows": len(pd.read_csv(path)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }


if __name__ == "__main__":
    OfficialMetricTableGenerator().run()
