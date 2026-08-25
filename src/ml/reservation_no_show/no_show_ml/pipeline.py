from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

from .config import FEATURES, ProjectConfig
from .dataset import ReservationDatasetBuilder
from .evaluation import select_threshold
from .modeling import ModelTrainer
from .selection import ValidationModelSelector
from .tuning import TuningRunner
from .onnx_support import OnnxExporter


class NoShowTrainingPipeline:
    def __init__(self, config: ProjectConfig):
        self.config = config

    def run(self, phase: str = "all", protocol_version: str = "v2") -> dict:
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.config.model_dir.mkdir(parents=True, exist_ok=True)

        # Load data once for all phases in this run
        self.bundle = ReservationDatasetBuilder(self.config).build()

        if phase in ("baseline", "all"):
            self._run_baseline()

        if phase in ("tune", "all"):
            self._run_tune_top2()

        if phase in ("finalize", "all"):
            self._run_finalize()

        if phase in ("test", "all"):
            self._run_test()

        return {
            "status": "COMPLETED",
            "phase": phase,
            "protocol_version": protocol_version,
            "artifacts_dir": str(self.config.artifacts_dir),
        }

    def _run_baseline(self):
        trainer = ModelTrainer(self.config.seed)
        models = trainer.fit_baseline_candidates(self.bundle.train)
        train_proba = trainer.probabilities(models, self.bundle.train)
        val_proba = trainer.probabilities(models, self.bundle.validation)

        from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

        y_val = self.bundle.validation["is_no_show"].to_numpy()

        metrics = []
        for name in models.keys():
            metrics.append({
                "split": "VALIDATION",
                "model": name,
                "average_precision": average_precision_score(y_val, val_proba[name]),
                "roc_auc": roc_auc_score(y_val, val_proba[name]),
                "brier_score": brier_score_loss(y_val, val_proba[name]),
            })

        metrics_df = pd.DataFrame(metrics)
        metrics_df.to_csv(self.config.artifacts_dir / "baseline_candidate_metrics.csv", index=False)

        selector = ValidationModelSelector(self.config.seed)
        top2 = selector.select_top2(metrics_df)

        with open(self.config.artifacts_dir / "top2_selection.json", "w", encoding="utf-8") as f:
            json.dump({
                "top2_names": top2.top2_names,
                "selection_reason": top2.selection_reason,
            }, f, indent=2)

    def _run_tune_top2(self):
        with open(self.config.artifacts_dir / "top2_selection.json", "r", encoding="utf-8") as f:
            top2_data = json.load(f)

        runner = TuningRunner(self.config.seed, source_snapshot_id=self.config.source_snapshot_id)
        trials = runner.tune_top2(self.bundle.train, self.bundle.validation, top2_data["top2_names"])
        trials.to_csv(self.config.artifacts_dir / "top2_tuning_trials.csv", index=False)
        trials.head(2).to_csv(self.config.artifacts_dir / "top2_tuning_summary.csv", index=False)
        with open(self.config.artifacts_dir / "top2_tuning_summary.json", "w", encoding="utf-8") as f:
            json.dump({
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "seed": self.config.seed,
                "trial_count": int(len(trials)),
                "top2_candidates": top2_data.get("top2_names", []),
            }, f, indent=2)

    def _run_finalize(self):
        trials = pd.read_csv(self.config.artifacts_dir / "top2_tuning_trials.csv")
        selector = ValidationModelSelector(self.config.seed)
        final_selection = selector.select_final(trials)

        final_payload = {
            "final_model": final_selection.final_model,
            "selected_model": final_selection.final_model,
            "threshold": final_selection.threshold,
            "selection_time": datetime.now(timezone.utc).isoformat(),
            "selection_reason": final_selection.selection_reason,
            "risk_flags": final_selection.risk_flags,
            "selection_source": "no_show_ml.tuning_top2",
            "selection_row": final_selection.selection_row,
            "validation_average_precision": final_selection.validation_average_precision,
            "seed": self.config.seed,
        }

        with open(self.config.artifacts_dir / "final_model_selection.json", "w", encoding="utf-8") as f:
            json.dump(final_payload, f, indent=2)

        self._sync_model_metadata(
            final_selection.final_model,
            final_selection.threshold,
            final_selection.selection_reason,
            final_selection.selection_row,
            metadata_path=self.config.artifacts_dir / "model_metadata.json",
        )

    def _run_test(self):
        with open(self.config.artifacts_dir / "final_model_selection.json", "r", encoding="utf-8") as f:
            final_data = json.load(f)

        final_model_name = final_data.get("selected_model") or final_data.get("final_model")
        if not final_model_name:
            raise ValueError("final model selection is empty")

        selection_row = final_data.get("selection_row", {})
        final_configuration = {}
        raw_configuration = selection_row.get("configuration")
        if isinstance(raw_configuration, str) and raw_configuration:
            try:
                final_configuration = json.loads(raw_configuration)
            except json.JSONDecodeError:
                final_configuration = {}

        final_threshold = float(final_data.get("threshold", 0.5))
        if pd.isna(final_threshold) or final_threshold <= 0:
            final_threshold = 0.5

        trainer = ModelTrainer(self.config.seed)
        final_pipeline = trainer.build_pipeline_by_name(final_model_name, final_configuration)
        final_pipeline.fit(self.bundle.train[FEATURES], self.bundle.train["is_no_show"].to_numpy())

        # Recompute decision threshold on validation for contract parity
        val_prob = final_pipeline.predict_proba(self.bundle.validation[FEATURES])[:, 1]
        y_val = self.bundle.validation["is_no_show"].to_numpy()
        fallback_threshold, _ = select_threshold(y_val, val_prob)
        decision_threshold = float(final_threshold) if 0 < float(final_threshold) < 1 else float(fallback_threshold)

        test_proba = final_pipeline.predict_proba(self.bundle.test[FEATURES])[:, 1]
        y_test = self.bundle.test["is_no_show"].to_numpy()

        from sklearn.metrics import average_precision_score, roc_auc_score
        ap = average_precision_score(y_test, test_proba)
        roc = roc_auc_score(y_test, test_proba)

        with open(self.config.artifacts_dir / "final_test_metrics.json", "w", encoding="utf-8") as f:
            json.dump({
                "model": final_model_name,
                "threshold": decision_threshold,
                "pr_auc": ap,
                "roc_auc": roc,
                "test_rows": len(y_test),
            }, f, indent=2)

        final_data["threshold"] = decision_threshold
        with open(self.config.artifacts_dir / "final_model_selection.json", "w", encoding="utf-8") as f:
            json.dump(final_data, f, indent=2)

        # Export models
        joblib_path = self.config.model_dir / "reservation_no_show_model.joblib"
        onnx_path = self.config.model_dir / "reservation_no_show_model.onnx"
        joblib.dump(final_pipeline, joblib_path)

        exporter = OnnxExporter()
        exporter.export(final_pipeline, self.bundle.train[FEATURES], onnx_path)

        self._sync_model_metadata(
            final_model_name,
            decision_threshold,
            final_data.get("selection_reason"),
            final_data.get("selection_row", {}),
            onnx_path=onnx_path,
            metadata_path=self.config.artifacts_dir / "model_metadata.json",
        )

        with open(self.config.artifacts_dir / "run_summary.json", "w", encoding="utf-8") as f:
            json.dump({
                "status": "COMPLETED",
                "selected_model": final_model_name,
                "selection_threshold": decision_threshold,
                "selection_reason": final_data.get("selection_reason"),
                "validation_average_precision": final_data.get("validation_average_precision"),
                "risk_flags": final_data.get("risk_flags", []),
                "test_metrics": {
                    "rows": len(y_test),
                    "model": final_model_name,
                    "pr_auc": ap,
                    "roc_auc": roc,
                },
            }, f, indent=2)

    def _sync_model_metadata(
        self,
        final_model_name: str,
        threshold: float,
        selection_reason: str | None,
        selection_row: dict[str, object] | None,
        *,
        onnx_path: Path | None = None,
        metadata_path: Path,
    ) -> None:
        if onnx_path is not None and not onnx_path.exists():
            raise ValueError(f"ONNX artifact does not exist: {onnx_path}")

        metadata: dict[str, object] = {}
        if metadata_path.is_file():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        metadata.update(
            {
                "model_name": final_model_name,
                "model_version": self.config.model_version,
                "feature_set_version": self.config.feature_set_version,
                "input_schema_version": metadata.get("input_schema_version", "reservation-no-show-input-v1.0"),
                "threshold": float(threshold),
                "selection_reason": selection_reason or metadata.get("selection_reason", ""),
                "selection_metric": "Validation top2 deterministic ranking",
                "selection_row": selection_row or {},
                "training_seed": self.config.seed,
                "trained_at_utc": datetime.now(timezone.utc).isoformat(),
                "label_rule_version": metadata.get("label_rule_version", self.config.label_rule_version),
            }
        )

        if onnx_path is not None and onnx_path.exists():
            metadata["onnx_sha256"] = hashlib.sha256(onnx_path.read_bytes()).hexdigest()

        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
