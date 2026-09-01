"""관측 shadow 자료의 성능·보정·지연시간·통계 지표를 집계한다."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .operational_metrics import DemandMetricSuite, METRIC_CONTRACT_VERSION
from .operational_statistical_validation import PairedBaselineValidator


class ShadowMetricEvaluator:
    """90일 shadow의 점 예측과 운영 품질 게이트를 한 계약으로 계산한다."""

    _MAX_P95_INFERENCE_LATENCY_MS = 100.0

    def evaluate(self, data: pd.DataFrame) -> dict[str, Any]:
        """관측 shadow의 성능·구간·잔차·지연·통계 게이트를 집계한다."""

        comparison = DemandMetricSuite.compare(
            data["actual_rooms_sold"],
            data["predicted_rooms"],
            data["baseline_predicted_rooms"],
        )
        groups = {
            "horizon": self._group_metrics(data, ["horizon_days"]),
            "property": self._group_metrics(data, ["property_id"]),
            "room_type": self._group_metrics(
                data, ["property_id", "room_type_code"]
            ),
        }
        intervals = {
            "80": DemandMetricSuite.interval_metrics(
                data["actual_rooms_sold"],
                data["lower_80"],
                data["upper_80"],
                nominal_coverage=0.80,
                capacity=data["target_sellable_rooms"],
            ),
            "95": DemandMetricSuite.interval_metrics(
                data["actual_rooms_sold"],
                data["lower_95"],
                data["upper_95"],
                nominal_coverage=0.95,
                capacity=data["target_sellable_rooms"],
            ),
        }
        latency = DemandMetricSuite.latency_metrics(data["inference_latency_ms"])
        statistics = PairedBaselineValidator().validate(
            data,
            data["predicted_rooms"],
            data["baseline_predicted_rooms"],
            actual_column="actual_rooms_sold",
        )
        room_thresholds = [
            bool(
                row["better_than_baseline"]
                and (
                    float(row["wape"]) <= 0.30
                    if float(row["actual_mean"]) >= 10.0
                    else float(row["mae"]) <= 3.0
                )
            )
            for row in groups["room_type"]
        ]
        quality_gates = {
            "overall_better_than_baseline": bool(
                comparison["relative_improvement"]["wape"] > 0.0
            ),
            "all_horizons_better_than_baseline": all(
                row["better_than_baseline"] for row in groups["horizon"]
            ),
            "all_properties_better_than_baseline": all(
                row["better_than_baseline"] for row in groups["property"]
            ),
            "all_room_types_within_threshold": all(room_thresholds),
            "paired_improvement_is_statistically_positive": bool(
                statistics["statistically_better"]
            ),
            "interval_80_minimum_coverage": bool(
                intervals["80"]["empirical_coverage"] >= 0.70
            ),
            "interval_95_minimum_coverage": bool(
                intervals["95"]["empirical_coverage"] >= 0.90
            ),
            "inference_p95_within_technical_guardrail": bool(
                latency["p95_ms"] <= self._MAX_P95_INFERENCE_LATENCY_MS
            ),
        }
        return {
            "metric_contract_version": METRIC_CONTRACT_VERSION,
            "metrics": comparison["candidate_metrics"],
            "baseline_metrics": comparison["baseline_metrics"],
            "baseline_improvement": comparison["relative_improvement"],
            "paired_cutoff_bootstrap": statistics,
            "prediction_intervals": intervals,
            "residual_diagnostics": DemandMetricSuite.residual_diagnostics(
                data,
                actual_column="actual_rooms_sold",
                prediction_column="predicted_rooms",
            ),
            "inference_latency": latency,
            "inference_latency_guardrail_ms": self._MAX_P95_INFERENCE_LATENCY_MS,
            "group_metrics": groups,
            "quality_gates": quality_gates,
            **quality_gates,
        }

    @staticmethod
    def _group_metrics(data: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for keys, group in data.groupby(columns, sort=True):
            values = keys if isinstance(keys, tuple) else (keys,)
            comparison = DemandMetricSuite.compare(
                group["actual_rooms_sold"],
                group["predicted_rooms"],
                group["baseline_predicted_rooms"],
            )
            candidate = comparison["candidate_metrics"]
            metric = "mae" if float(candidate["actual_mean"]) < 10.0 else "wape"
            records.append(
                {
                    **{
                        column: int(value) if column == "horizon_days" else str(value)
                        for column, value in zip(columns, values)
                    },
                    **candidate,
                    "baseline_metrics": comparison["baseline_metrics"],
                    "baseline_wape": comparison["baseline_metrics"]["wape"],
                    "baseline_mae": comparison["baseline_metrics"]["mae"],
                    "baseline_improvement": comparison["relative_improvement"],
                    "better_than_baseline": bool(
                        comparison["absolute_reduction"][metric] > 0.0
                    ),
                }
            )
        return records
