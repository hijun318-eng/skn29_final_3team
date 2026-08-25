from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class Top2Selection:
    top2_names: list[str]
    selection_reason: str


@dataclass
class FinalSelection:
    final_model: str
    threshold: float
    validation_average_precision: float
    selection_reason: str
    risk_flags: list[str]
    selection_row: dict[str, Any]


class ValidationModelSelector:
    def __init__(self, seed: int):
        self.seed = seed

    def select_top2(self, baseline_metrics: pd.DataFrame) -> Top2Selection:
        val_metrics = baseline_metrics[baseline_metrics["split"] == "VALIDATION"].copy()
        val_metrics = val_metrics.sort_values(by=["average_precision", "roc_auc"], ascending=False)

        # Remove PriorProbability from ranking
        val_metrics = val_metrics[val_metrics["model"] != "PriorProbability"]

        top2 = val_metrics.head(2)["model"].tolist()

        if len(top2) < 2:
            raise ValueError("INSUFFICIENT_CANDIDATES")

        reason = "Selected Top2 by VALIDATION average_precision + ROC-AUC tie-break."
        return Top2Selection(top2_names=top2, selection_reason=reason)

    def select_final(self, tuned_metrics: pd.DataFrame) -> FinalSelection:
        required = {
            "model_family",
            "validation_average_precision",
            "validation_roc_auc",
            "validation_threshold",
        }
        missing = sorted(required - set(tuned_metrics.columns))
        if missing:
            raise ValueError(f"Invalid tuning result schema: missing {missing}")

        metrics = tuned_metrics.copy()
        for column in [
            "validation_average_precision",
            "validation_roc_auc",
            "precision_at_15",
            "monthly_average_precision_mean",
            "monthly_average_precision_min",
        ]:
            metrics[column] = pd.to_numeric(metrics[column], errors="coerce")

        metrics = metrics.sort_values(
            by=[
                "validation_average_precision",
                "validation_roc_auc",
                "precision_at_15",
                "monthly_average_precision_mean",
                "monthly_average_precision_min",
            ],
            ascending=[False, False, False, False, False],
            na_position="last",
        )
        metrics = metrics.sort_values(
            by=[
                "validation_average_precision",
                "validation_roc_auc",
                "precision_at_15",
                "monthly_average_precision_mean",
                "monthly_average_precision_min",
                "validation_brier_score",
                "model_version",
                "split",
                "trial_seed",
                "trial_id",
            ],
            ascending=[False, False, False, False, False, True, True, True, True, True],
            na_position="last",
        ).reset_index(drop=True)
        best = metrics.iloc[0]

        risk_flags: list[str] = []
        if pd.isna(best["validation_roc_auc"]) or best["validation_roc_auc"] < 0.5:
            risk_flags.append("low_discrimination")
        if pd.isna(best["monthly_average_precision_std"]) or best["monthly_average_precision_std"] > 0.10:
            risk_flags.append("monthly_ap_instability")
        if pd.isna(best["validation_brier_score"]) or best["validation_brier_score"] > 0.10:
            risk_flags.append("weak_calibration")

        reason = (
            f"{best['model_family']} selected by deterministic ranking: "
            f"AP={best['validation_average_precision']:.6f}, "
            f"ROC-AUC={best['validation_roc_auc']:.4f}, "
            f"Top15 precision={best['precision_at_15']:.4f}, "
            f"seed={best.get('trial_seed', 'n/a')}, "
            f"version={best.get('model_version', 'n/a')}, "
            f"split={best.get('split', 'VALIDATION')}"
        )
        if risk_flags:
            reason = f"{reason}; risk_flags={','.join(risk_flags)}"

        row = {
            key: best[key]
            for key in [
                "trial_id",
                "model_family",
                "configuration",
                "validation_average_precision",
                "validation_roc_auc",
                "validation_threshold",
                "validation_threshold_reason",
                "precision_at_15",
                "recall_at_15",
                "lift_at_15",
                "validation_brier_score",
                "monthly_average_precision_mean",
                "monthly_average_precision_std",
                "monthly_average_precision_min",
                "model_version",
                "trial_seed",
                "split",
                "source_snapshot_id",
            ]
            if key in best
        }
        row = {
            k: (float(v) if isinstance(v, (int, float, np.number)) else v)
            for k, v in row.items()
        }

        return FinalSelection(
            final_model=str(best["model_family"]),
            threshold=float(best["validation_threshold"]),
            validation_average_precision=float(best["validation_average_precision"]),
            selection_reason=reason,
            risk_flags=risk_flags,
            selection_row=row,
        )
