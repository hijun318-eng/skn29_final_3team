"""실제 운영 shadow 예측과 이후 실적을 90일 승인 보고서로 검증한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .operational_contracts import (
    OBSERVED_SIGNAL_SOURCE_KIND,
    OPERATIONAL_MAX_HORIZON,
    OPERATIONAL_MODEL_VERSION,
    SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS,
)
from .operational_shadow_contracts import (
    HASH_PATTERN,
    SHADOW_IDENTITY_COLUMNS,
    SHADOW_SCHEMA_VERSION,
    normalize_shadow_evidence,
    sha256_file,
)
from .operational_shadow_metrics import ShadowMetricEvaluator


class ObservedShadowValidator:
    """look-ahead 없는 실제 shadow 행만 승인 지표로 집계한다."""

    _TIMEZONE = "Asia/Seoul"
    _MIN_OBSERVED_DAYS = 90

    def validate(
        self,
        frame: pd.DataFrame,
        *,
        expected_artifact_sha256: str,
        expected_feature_contract_sha256: str,
        source_sha256: str,
    ) -> dict[str, Any]:
        """원본 hash와 시점 무결성을 검증해 재현 가능한 shadow 보고서를 만든다."""

        for value, label in (
            (expected_artifact_sha256, "artifact"),
            (expected_feature_contract_sha256, "feature contract"),
            (source_sha256, "source"),
        ):
            if not HASH_PATTERN.fullmatch(value):
                raise ValueError(f"invalid {label} SHA-256")
        data = normalize_shadow_evidence(frame)
        self._validate_constants(
            data,
            expected_artifact_sha256,
            expected_feature_contract_sha256,
        )
        self._validate_temporal_integrity(data)
        self._validate_grain_and_coverage(data)
        metric_report = ShadowMetricEvaluator().evaluate(data)
        observed_days = int(data["cutoff_date"].nunique())
        result = {
            "schema_version": SHADOW_SCHEMA_VERSION,
            "model_version": OPERATIONAL_MODEL_VERSION,
            "artifact_sha256": expected_artifact_sha256,
            "feature_contract_sha256": expected_feature_contract_sha256,
            "source_sha256": source_sha256,
            "runtime_feature_parity": "PASS",
            "data_is_synthetic": False,
            "signal_source_kind": OBSERVED_SIGNAL_SOURCE_KIND,
            "observed_days": observed_days,
            "cutoff_start": data["cutoff_date"].min().date().isoformat(),
            "cutoff_end": data["cutoff_date"].max().date().isoformat(),
            "rows": int(len(data)),
            "series_count": int(
                data[["property_id", "room_type_code"]].drop_duplicates().shape[0]
            ),
            **metric_report,
            "evidence_checks": {
                "observed_source_only": True,
                "minimum_90_consecutive_cutoffs": observed_days
                >= self._MIN_OBSERVED_DAYS,
                "complete_d1_d7_per_series": True,
                "unique_prediction_grain": True,
                "prediction_precedes_actual": True,
                "point_in_time_provenance_valid": True,
                "artifact_and_contract_bound": True,
                "prediction_intervals_valid": True,
                "inference_latency_recorded": True,
            },
            "limitations": [],
        }
        if not result["evidence_checks"]["minimum_90_consecutive_cutoffs"]:
            raise ValueError("observed shadow period is shorter than 90 days")
        return result

    @staticmethod
    def _validate_constants(
        data: pd.DataFrame,
        artifact_sha256: str,
        feature_contract_sha256: str,
    ) -> None:
        if data["signal_is_synthetic"].any():
            raise ValueError("synthetic shadow evidence is forbidden")
        expected = {
            "model_version": OPERATIONAL_MODEL_VERSION,
            "artifact_sha256": artifact_sha256,
            "feature_contract_sha256": feature_contract_sha256,
            "runtime_feature_parity": "PASS",
            "signal_source_kind": OBSERVED_SIGNAL_SOURCE_KIND,
        }
        for column, value in expected.items():
            if set(data[column].astype(str).str.strip()) != {value}:
                raise ValueError(f"shadow {column} does not match the approved contract")

    def _validate_temporal_integrity(self, data: pd.DataFrame) -> None:
        cutoff_end = (
            data["cutoff_date"]
            .dt.tz_localize(self._TIMEZONE)
            .dt.tz_convert("UTC")
            + pd.Timedelta(1, unit="D")
        )
        for column in SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS:
            if (data[column] > cutoff_end).any():
                raise ValueError("shadow provenance is later than the cutoff")
        if ((data["captured_at"] < cutoff_end) | (
            data["captured_at"] > cutoff_end + pd.Timedelta(6, unit="h")
        )).any():
            raise ValueError("shadow capture is outside the cutoff grace window")
        actual_available = (
            data["target_date"]
            .dt.tz_localize(self._TIMEZONE)
            .dt.tz_convert("UTC")
            + pd.Timedelta(1, unit="D")
        )
        if (data["prediction_generated_at"] < data["captured_at"]).any():
            raise ValueError("shadow prediction predates its captured features")
        if (data["actual_as_of_at"] < actual_available).any():
            raise ValueError("shadow actual was read before the target day completed")
        if (data["prediction_generated_at"] >= data["actual_as_of_at"]).any():
            raise ValueError("shadow prediction does not precede the actual outcome")

    @staticmethod
    def _validate_grain_and_coverage(data: pd.DataFrame) -> None:
        if data.duplicated(SHADOW_IDENTITY_COLUMNS).any():
            raise ValueError("duplicate shadow prediction grain")
        expected_horizon = (data["target_date"] - data["cutoff_date"]).dt.days
        if not expected_horizon.equals(data["horizon_days"].astype(int)):
            raise ValueError("shadow target date and horizon are inconsistent")
        if not data["horizon_days"].between(1, OPERATIONAL_MAX_HORIZON).all():
            raise ValueError("shadow horizon is outside D+1 through D+7")
        numeric = data[
            [
                "target_sellable_rooms",
                "predicted_rooms",
                "baseline_predicted_rooms",
                "actual_rooms_sold",
                "lower_80",
                "upper_80",
                "lower_95",
                "upper_95",
                "inference_latency_ms",
            ]
        ].to_numpy(dtype=float)
        if not np.isfinite(numeric).all():
            raise ValueError("shadow evidence contains non-finite values")
        capacity = data["target_sellable_rooms"]
        if (capacity <= 0).any() or (
            data[
                [
                    "predicted_rooms",
                    "baseline_predicted_rooms",
                    "actual_rooms_sold",
                    "lower_80",
                    "upper_80",
                    "lower_95",
                    "upper_95",
                    "inference_latency_ms",
                ]
            ]
            .lt(0)
            .any()
            .any()
        ):
            raise ValueError("shadow room counts are outside the valid range")
        if any((data[column] > capacity).any() for column in (
            "predicted_rooms",
            "baseline_predicted_rooms",
            "actual_rooms_sold",
            "lower_80",
            "upper_80",
            "lower_95",
            "upper_95",
        )):
            raise ValueError("shadow room counts exceed sellable capacity")
        if not (
            (data["lower_95"] <= data["lower_80"])
            & (data["lower_80"] <= data["predicted_rooms"])
            & (data["predicted_rooms"] <= data["upper_80"])
            & (data["upper_80"] <= data["upper_95"])
        ).all():
            raise ValueError("shadow prediction intervals are not nested")
        expected_series = set(
            data[["property_id", "room_type_code"]].itertuples(index=False, name=None)
        )
        for _, cutoff in data.groupby("cutoff_date", sort=True):
            actual_series = set(
                cutoff[["property_id", "room_type_code"]]
                .drop_duplicates()
                .itertuples(index=False, name=None)
            )
            if actual_series != expected_series:
                raise ValueError("shadow series coverage changes by cutoff")
        grouped = data.groupby(
            ["cutoff_date", "property_id", "room_type_code"], sort=True
        )["horizon_days"]
        if any(sorted(values.astype(int).tolist()) != list(range(1, 8))
               for _, values in grouped):
            raise ValueError("shadow evidence has incomplete D+1 through D+7 rows")
        cutoffs = pd.Series(sorted(data["cutoff_date"].unique()))
        if len(cutoffs) > 1 and not (cutoffs.diff().dropna() == pd.Timedelta(1, unit="D")).all():
            raise ValueError("shadow cutoff dates are not consecutive")

def main() -> None:
    """shadow CSV와 후보 artifact를 검증해 승인 입력용 JSON을 저장한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact_hash = sha256_file(args.artifact_dir / "model.joblib")
    contract_hash = sha256_file(args.artifact_dir / "feature_contract.json")
    source_hash = sha256_file(args.input)
    report = ObservedShadowValidator().validate(
        pd.read_csv(args.input),
        expected_artifact_sha256=artifact_hash,
        expected_feature_contract_sha256=contract_hash,
        source_sha256=source_hash,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
