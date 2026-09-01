"""학습·검증·시험 split을 한 번에 자체 검증하는 운영 평가기다."""

from __future__ import annotations

import time
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .operational_evaluation import baseline_prediction
from .operational_governance import OperationalDataGate
from .operational_metrics import DemandMetricSuite, METRIC_CONTRACT_VERSION
from .operational_modeling import OperationalDemandModel
from .operational_self_evaluation_support import (
    SPLIT_NAMES,
    MAX_WAPE_RELATIVE_DEGRADATION,
    approval_gates,
    generalization_report,
    group_metrics,
    largest_errors,
)
from .operational_statistical_validation import PairedBaselineValidator


SELF_EVALUATION_VERSION = "room-demand-operational-self-evaluation-v1"


class OperationalSelfEvaluator:
    """동일 행 예측, 데이터 검증, 구간·잔차·일반화 판정을 자동화한다."""

    def __init__(
        self,
        *,
        bootstrap_samples: int = 500,
        inference_repeats: int = 5,
    ) -> None:
        if inference_repeats < 1:
            raise ValueError("inference repeats must be positive")
        self.statistics = PairedBaselineValidator(samples=bootstrap_samples)
        self.inference_repeats = inference_repeats

    def evaluate(
        self,
        model: OperationalDemandModel,
        datasets: Mapping[str, pd.DataFrame],
        *,
        data_is_synthetic: bool,
        development_model: OperationalDemandModel | None = None,
    ) -> dict[str, Any]:
        """네 시간 split의 독립성·성능·일반화·운영 지표를 반환한다."""

        aligned = OperationalDataGate.validate_aligned_splits(datasets)
        split_reports: dict[str, Any] = {}
        prediction_frames: dict[str, pd.DataFrame] = {}
        for name in SPLIT_NAMES:
            selected_model = (
                development_model
                if development_model is not None and name in {"TRAIN", "VALIDATION"}
                else model
            )
            scope = (
                "trained_on_train_only"
                if selected_model is development_model
                else "trained_on_train_and_validation"
            )
            report, evaluated = self._evaluate_split(
                selected_model, datasets[name], name, scope
            )
            split_reports[name] = report
            prediction_frames[name] = evaluated
        generalization = generalization_report(split_reports)
        gates = approval_gates(split_reports, generalization)
        return {
            "schema_version": SELF_EVALUATION_VERSION,
            "metric_contract_version": METRIC_CONTRACT_VERSION,
            "model_version": model.model_version,
            "data_is_synthetic": bool(data_is_synthetic),
            "split_contract": aligned,
            "split_reports": split_reports,
            "generalization": generalization,
            "approval_gates": gates,
            "technical_validation_passed": bool(all(gates.values())),
            "production_eligible": bool(
                not data_is_synthetic
                and all(gates.values())
                and all(
                    report["data_checks"]["observed_source_only"]
                    for report in split_reports.values()
                )
            ),
            "primary_metrics": ["mae", "rmse", "wape"],
            "diagnostic_metrics": [
                "r2",
                "bias",
                "smape",
                "mase",
                "absolute_error_quantiles",
                "prediction_interval_coverage",
                "residual_autocorrelation",
                "inference_latency",
            ],
            "technical_guardrails": {
                "maximum_wape_relative_degradation_vs_train": (
                    MAX_WAPE_RELATIVE_DEGRADATION
                ),
                "high_volume_room_type_maximum_wape": 0.30,
                "low_volume_room_type_maximum_mae_rooms": 3.0,
                "interval_80_minimum_coverage": 0.70,
                "interval_95_minimum_coverage": 0.90,
            },
            "limitations": (
                ["synthetic data cannot provide production approval evidence"]
                if data_is_synthetic
                else []
            ),
        }

    def _evaluate_split(
        self,
        model: OperationalDemandModel,
        frame: pd.DataFrame,
        split_name: str,
        training_scope: str,
    ) -> tuple[dict[str, Any], pd.DataFrame]:
        data = frame.copy().reset_index(drop=True)
        checks = self._data_checks(data)
        prediction, latency = self._timed_prediction(model, data)
        baseline = baseline_prediction(data)
        intervals = pd.DataFrame(model.prediction_intervals(data, prediction))
        evaluated = data.assign(
            predicted_rooms=prediction,
            baseline_predicted_rooms=baseline,
        ).join(intervals)
        self._validate_outputs(evaluated)
        comparison = DemandMetricSuite.compare(
            evaluated["target_rooms_sold"], prediction, baseline
        )
        interval_metrics = {
            "80": DemandMetricSuite.interval_metrics(
                evaluated["target_rooms_sold"],
                evaluated["lower_80"],
                evaluated["upper_80"],
                nominal_coverage=0.80,
                capacity=evaluated["target_sellable_rooms"],
            ),
            "95": DemandMetricSuite.interval_metrics(
                evaluated["target_rooms_sold"],
                evaluated["lower_95"],
                evaluated["upper_95"],
                nominal_coverage=0.95,
                capacity=evaluated["target_sellable_rooms"],
            ),
        }
        return {
            "split": split_name,
            "model_training_scope": training_scope,
            "data_checks": checks,
            "metrics": comparison["candidate_metrics"],
            "baseline_metrics": comparison["baseline_metrics"],
            "baseline_improvement": comparison["relative_improvement"],
            "paired_cutoff_bootstrap": self.statistics.validate(
                evaluated, prediction, baseline
            ),
            "group_metrics": group_metrics(evaluated),
            "prediction_intervals": interval_metrics,
            "residual_diagnostics": DemandMetricSuite.residual_diagnostics(
                evaluated,
                actual_column="target_rooms_sold",
                prediction_column="predicted_rooms",
            ),
            "inference_benchmark": latency,
            "largest_errors": largest_errors(evaluated),
        }, evaluated

    def _timed_prediction(
        self, model: OperationalDemandModel, frame: pd.DataFrame
    ) -> tuple[np.ndarray, dict[str, Any]]:
        durations: list[float] = []
        prediction: np.ndarray | None = None
        for _ in range(self.inference_repeats):
            started = time.perf_counter()
            current = model.predict(frame)
            durations.append((time.perf_counter() - started) * 1000.0)
            if prediction is None:
                prediction = current
            elif not np.array_equal(prediction, current):
                raise ValueError("model predictions are not deterministic")
        metrics = DemandMetricSuite.latency_metrics(durations)
        metrics.update(
            {
                "method": "in_process_batch_prediction",
                "batch_rows": int(len(frame)),
                "p95_ms_per_1000_rows": float(
                    metrics["p95_ms"] * 1000.0 / len(frame)
                ),
                "repeats": self.inference_repeats,
            }
        )
        assert prediction is not None
        return prediction, metrics

    @staticmethod
    def _data_checks(frame: pd.DataFrame) -> dict[str, Any]:
        provenance_error = None
        provenance = None
        try:
            _, summary = OperationalDataGate.validate_signal_provenance(frame)
            provenance = summary.__dict__
        except ValueError as error:
            provenance_error = str(error)
        label_proxy = OperationalDataGate.audit_label_proxy(frame)
        return {
            "point_in_time_provenance_passed": provenance_error is None,
            "observed_source_only": bool(
                provenance is not None
                and provenance["source_kinds"] == ["OBSERVED_PIT"]
                and provenance["synthetic_rows"] == 0
            ),
            "point_in_time_provenance": provenance,
            "point_in_time_provenance_error": provenance_error,
            "label_proxy_audit": label_proxy,
        }

    @staticmethod
    def _validate_outputs(frame: pd.DataFrame) -> None:
        identity = [
            "property_id",
            "room_type_code",
            "cutoff_date",
            "target_date",
            "horizon_days",
        ]
        if frame.duplicated(identity).any():
            raise ValueError("duplicate self-evaluation prediction grain")
        columns = [
            "target_sellable_rooms",
            "target_rooms_sold",
            "predicted_rooms",
            "baseline_predicted_rooms",
            "lower_80",
            "upper_80",
            "lower_95",
            "upper_95",
        ]
        numeric = frame[columns].to_numpy(dtype=float)
        if not np.isfinite(numeric).all():
            raise ValueError("self-evaluation output contains non-finite values")
        capacity = frame["target_sellable_rooms"].to_numpy(dtype=float)
        if (capacity <= 0.0).any() or (numeric[:, 1:] < 0.0).any():
            raise ValueError("self-evaluation room count is outside the valid range")
        if (numeric[:, 1:] > capacity[:, None]).any():
            raise ValueError("self-evaluation room count exceeds sellable capacity")
        if not (
            (frame["lower_95"] <= frame["lower_80"])
            & (frame["lower_80"] <= frame["predicted_rooms"])
            & (frame["predicted_rooms"] <= frame["upper_80"])
            & (frame["upper_80"] <= frame["upper_95"])
        ).all():
            raise ValueError("prediction intervals are not nested around prediction")
