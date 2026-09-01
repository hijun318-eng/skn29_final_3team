"""V4 제출용 Train·Validation·Test 평가 증거를 생성한다."""

from __future__ import annotations

import time
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .operational_evaluation import (
    BASELINE_DEFINITION,
    BASELINE_NAME,
    baseline_prediction,
)
from .operational_governance import OperationalDataGate
from .operational_metrics import DemandMetricSuite, METRIC_CONTRACT_VERSION
from .operational_modeling import OperationalDemandModel
from .operational_self_evaluation_support import group_metrics, largest_errors
from .operational_statistical_validation import PairedBaselineValidator
SUBMISSION_EVALUATION_VERSION = "room-demand-v4-submission-evaluation-v1"
SPLIT_NAMES = ("TRAIN", "VALIDATION", "TEST")
IDENTITY_COLUMNS = [
    "property_id",
    "room_type_code",
    "cutoff_date",
    "target_date",
    "horizon_days",
]
class SubmissionSplitValidator:
    """세 분할의 label 가용시점과 D+1~D+7 독립성을 검증한다."""

    @staticmethod
    def purge_label_overlap(
        datasets: Mapping[str, pd.DataFrame],
    ) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
        """다음 분할 시작 이후에 확정되는 이전 분할 label을 제거한다."""
        if set(datasets) != set(SPLIT_NAMES):
            raise ValueError("submission evaluation requires TRAIN, VALIDATION, TEST")
        output = {name: frame.copy() for name, frame in datasets.items()}
        removed: dict[str, int] = {name: 0 for name in SPLIT_NAMES}
        boundaries: dict[str, str] = {}
        for current, following in zip(SPLIT_NAMES, SPLIT_NAMES[1:]):
            next_start = pd.to_datetime(output[following]["cutoff_date"]).min()
            cutoff = pd.to_datetime(output[current]["cutoff_date"])
            max_horizon = int(output[current]["horizon_days"].max())
            keep = cutoff + pd.Timedelta(max_horizon, unit="D") < next_start
            removed[current] = int((~keep).sum())
            output[current] = output[current].loc[keep].copy().reset_index(drop=True)
            boundaries[current] = str(next_start.date())
        return output, {
            "method": "purged_target_date_before_next_split_cutoff",
            "removed_rows": removed,
            "next_split_cutoff_boundaries": boundaries,
        }

    @staticmethod
    def validate(datasets: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
        """시간 독립성·grain·horizon·시리즈 일관성을 실패 차단형으로 확인한다."""
        if set(datasets) != set(SPLIT_NAMES):
            raise ValueError("submission evaluation requires TRAIN, VALIDATION, TEST")
        identities: set[tuple[object, ...]] = set()
        common_series: set[tuple[str, str]] | None = None
        summary: dict[str, Any] = {}
        previous_target_max: pd.Timestamp | None = None
        for name in SPLIT_NAMES:
            frame = datasets[name]
            if frame.empty or frame.duplicated(IDENTITY_COLUMNS).any():
                raise ValueError(f"submission split {name} is empty or duplicated")
            cutoff = pd.to_datetime(frame["cutoff_date"], errors="raise")
            target = pd.to_datetime(frame["target_date"], errors="raise")
            horizon = frame["horizon_days"].astype(int)
            if sorted(horizon.unique().tolist()) != list(range(1, 8)):
                raise ValueError(
                    f"submission split {name} must contain D+1 through D+7"
                )
            if not ((target - cutoff).dt.days == horizon).all():
                raise ValueError(f"submission split {name} has inconsistent horizons")
            grouped = frame.assign(_horizon=horizon).groupby(
                ["cutoff_date", "property_id", "room_type_code"], sort=True
            )["_horizon"]
            incomplete = any(
                sorted(values.tolist()) != list(range(1, 8))
                for _, values in grouped
            )
            if incomplete:
                raise ValueError(f"submission split {name} has incomplete horizons")
            if previous_target_max is not None and cutoff.min() <= previous_target_max:
                raise ValueError("submission split label availability overlaps")
            previous_target_max = target.max()
            series = set(
                frame[["property_id", "room_type_code"]]
                .astype(str)
                .itertuples(index=False, name=None)
            )
            if common_series is not None and series != common_series:
                raise ValueError("submission split series coverage differs")
            common_series = series
            current = set(frame[IDENTITY_COLUMNS].itertuples(index=False, name=None))
            if identities.intersection(current):
                raise ValueError("submission split identity overlap detected")
            identities.update(current)
            summary[name] = {
                "rows": int(len(frame)),
                "cutoff_start": str(cutoff.min().date()),
                "cutoff_end": str(cutoff.max().date()),
                "target_end": str(target.max().date()),
                "series_count": int(len(series)),
                "horizons": list(range(1, 8)),
            }
        return {"contract": "purged_train_validation_test_v1", "splits": summary}
class OperationalSubmissionEvaluator:
    """V4 제출에 필요한 성능·일반화·오차·통계·지연 증거를 묶는다."""

    def __init__(
        self,
        *,
        bootstrap_samples: int = 500,
        inference_requests: int = 200,
        inference_warmups: int = 10,
    ) -> None:
        if inference_requests < 100:
            raise ValueError("inference requests must be at least 100 for p99")
        self.statistics = PairedBaselineValidator(samples=bootstrap_samples)
        self.inference_requests = inference_requests
        self.inference_warmups = inference_warmups

    def evaluate(
        self,
        development_model: OperationalDemandModel,
        final_model: OperationalDemandModel,
        datasets: Mapping[str, pd.DataFrame],
        *,
        learning_curve: list[dict[str, Any]],
        data_is_synthetic: bool,
        purge_report: Mapping[str, Any],
        actual_pms_evaluated: bool = False,
    ) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
        """Train 전용 모델과 Train+Validation 최종 모델을 구분해 평가한다."""

        split_contract = SubmissionSplitValidator.validate(datasets)
        reports: dict[str, Any] = {}
        predictions: dict[str, pd.DataFrame] = {}
        for name in SPLIT_NAMES:
            model = development_model if name != "TEST" else final_model
            scope = "TRAIN_ONLY" if name != "TEST" else "TRAIN_PLUS_VALIDATION"
            reports[name], predictions[name] = self._evaluate_split(
                model, datasets[name], scope
            )
        train_metrics = reports["TRAIN"]["metrics"]
        validation_metrics = reports["VALIDATION"]["metrics"]
        generalization = {
            f"{metric}_absolute_gap": float(
                validation_metrics[metric] - train_metrics[metric]
            )
            for metric in ("mae", "rmse", "wape")
        }
        generalization["wape_relative_degradation"] = (
            float(validation_metrics["wape"] / train_metrics["wape"] - 1.0)
            if train_metrics["wape"]
            else None
        )
        provenance_passed = all(
            report["data_checks"]["point_in_time_provenance_passed"]
            for report in reports.values()
        )
        report = {
            "schema_version": SUBMISSION_EVALUATION_VERSION,
            "metric_contract_version": METRIC_CONTRACT_VERSION,
            "model_version": final_model.model_version,
            "baseline": {"name": BASELINE_NAME, "definition": BASELINE_DEFINITION},
            "split_contract": split_contract,
            "label_availability_purge": dict(purge_report),
            "split_reports": reports,
            "train_validation_generalization": generalization,
            "learning_curve": learning_curve,
            "actual_pms_evaluation": {
                "status": "AVAILABLE" if actual_pms_evaluated else "NOT_AVAILABLE",
                "data_is_synthetic": bool(data_is_synthetic),
            },
            "submission_checklist": {
                "baseline_name_and_improvement": "PASS",
                "train_validation_comparison": "PASS",
                "d1_d7_metrics": "PASS",
                "property_and_room_type_details": "PASS",
                "residual_and_extreme_error_details": "PASS",
                "target_date_block_bootstrap_ci95": "PASS",
                "single_request_latency_p50_p95_p99": "PASS",
                "learning_curve": "PASS" if learning_curve else "FAIL",
                "actual_pms_evaluation": (
                    "PASS" if actual_pms_evaluated else "FAIL_NOT_PROVIDED"
                ),
                "point_in_time_provenance": (
                    "PASS" if provenance_passed else "FAIL_MISSING_OR_INVALID"
                ),
            },
            "production_eligible": bool(
                not data_is_synthetic
                and provenance_passed
                and actual_pms_evaluated
            ),
            "limitations": [
                "현재 평가는 합성 데이터이므로 실제 PMS 운영 성능을 증명하지 않는다."
            ] if data_is_synthetic else [],
        }
        return report, predictions

    def _evaluate_split(
        self,
        model: OperationalDemandModel,
        frame: pd.DataFrame,
        training_scope: str,
    ) -> tuple[dict[str, Any], pd.DataFrame]:
        data = frame.copy().reset_index(drop=True)
        prediction = model.predict(data)
        baseline = baseline_prediction(data)
        intervals = pd.DataFrame(model.prediction_intervals(data, prediction))
        evaluated = data.assign(
            predicted_rooms=prediction,
            baseline_predicted_rooms=baseline,
            residual_rooms=prediction - data["target_rooms_sold"].to_numpy(dtype=float),
            absolute_error_rooms=np.abs(
                prediction - data["target_rooms_sold"].to_numpy(dtype=float)
            ),
        ).join(intervals)
        comparison = DemandMetricSuite.compare(
            evaluated["target_rooms_sold"], prediction, baseline
        )
        return {
            "model_training_scope": training_scope,
            "data_checks": self._data_checks(evaluated),
            "metrics": comparison["candidate_metrics"],
            "baseline_metrics": comparison["baseline_metrics"],
            "baseline_improvement": comparison["relative_improvement"],
            "paired_target_date_bootstrap": self.statistics.validate(
                evaluated, prediction, baseline, date_column="target_date"
            ),
            "group_metrics": group_metrics(evaluated),
            "residual_diagnostics": DemandMetricSuite.residual_diagnostics(
                evaluated,
                actual_column="target_rooms_sold",
                prediction_column="predicted_rooms",
            ),
            "largest_errors": largest_errors(evaluated),
            "prediction_intervals": {
                coverage: DemandMetricSuite.interval_metrics(
                    evaluated["target_rooms_sold"],
                    evaluated[f"lower_{coverage}"],
                    evaluated[f"upper_{coverage}"],
                    nominal_coverage=float(coverage) / 100.0,
                    capacity=evaluated["target_sellable_rooms"],
                )
                for coverage in ("80", "95")
            },
            "inference_benchmark": self._request_latency(model, data),
        }, evaluated

    def _request_latency(
        self, model: OperationalDemandModel, frame: pd.DataFrame
    ) -> dict[str, Any]:
        indices = np.linspace(
            0, len(frame) - 1, num=self.inference_requests, dtype=int
        )
        for index in indices[: self.inference_warmups]:
            model.predict(frame.iloc[[int(index)]])
        durations = []
        for index in indices:
            started = time.perf_counter_ns()
            model.predict(frame.iloc[[int(index)]])
            durations.append((time.perf_counter_ns() - started) / 1_000_000.0)
        metrics = DemandMetricSuite.latency_metrics(durations)
        metrics.update(
            {
                "method": "in_process_single_row_request",
                "request_rows": 1,
                "warmups": self.inference_warmups,
                "includes": "feature_preprocessing_and_model_prediction",
                "excludes": "network_api_authentication_and_serialization",
            }
        )
        return metrics

    @staticmethod
    def _data_checks(frame: pd.DataFrame) -> dict[str, Any]:
        try:
            _, summary = OperationalDataGate.validate_signal_provenance(frame)
            return {
                "point_in_time_provenance_passed": True,
                "point_in_time_provenance": summary.__dict__,
                "point_in_time_provenance_error": None,
            }
        except ValueError as error:
            return {
                "point_in_time_provenance_passed": False,
                "point_in_time_provenance": None,
                "point_in_time_provenance_error": str(error),
            }
