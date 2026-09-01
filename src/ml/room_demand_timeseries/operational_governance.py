"""운영형 수요예측 데이터와 승인을 보수적으로 차단하는 품질 게이트다."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .operational_contracts import (
    ALLOWED_SIGNAL_SOURCE_KINDS,
    OBSERVED_SIGNAL_SOURCE_KIND,
    SIGNAL_PROVENANCE_COLUMNS,
    SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS,
    SYNTHETIC_SIGNAL_SOURCE_KIND,
)
from .operational_metrics import METRIC_CONTRACT_VERSION
from .operational_split_validation import AlignedSplitValidator


@dataclass(frozen=True)
class SignalProvenanceSummary:
    """시점 신호가 언제, 어떤 종류의 원천에서 관측됐는지 요약한다."""

    rows: int
    source_kinds: list[str]
    synthetic_rows: int
    observed_rows: int
    min_as_of_at: str
    max_as_of_at: str


class OperationalDataGate:
    """미래 정보와 정답 대용 변수가 학습·추론에 들어가지 못하게 한다."""

    _LOCAL_TIMEZONE = "Asia/Seoul"
    _MIN_PROXY_AUDIT_ROWS = 30
    _MAX_EXACT_MATCH_RATE = 0.98
    _MAX_PROXY_CORRELATION = 0.999

    @classmethod
    def validate_signal_provenance(
        cls,
        signals: pd.DataFrame,
    ) -> tuple[pd.DataFrame, SignalProvenanceSummary]:
        """모든 신호 원천의 관측시각이 cutoff 종료시각 이내인지 검증한다."""

        missing = sorted(set(SIGNAL_PROVENANCE_COLUMNS) - set(signals.columns))
        if missing:
            raise ValueError(f"signal provenance missing columns: {missing}")
        frame = signals.copy()
        for column in SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS:
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
        if frame[SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS].isna().any().any():
            raise ValueError("signal provenance timestamp is missing or invalid")
        cutoff_end = (
            pd.to_datetime(frame["cutoff_date"])
            .dt.tz_localize(cls._LOCAL_TIMEZONE)
            .dt.tz_convert("UTC")
            + pd.Timedelta(1, unit="D")
        )
        future_mask = pd.DataFrame(
            {
                column: frame[column] > cutoff_end
                for column in SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS
            }
        )
        if future_mask.any().any():
            raise ValueError("signal provenance is later than the cutoff")
        frame["signal_source_kind"] = (
            frame["signal_source_kind"].astype(str).str.strip().str.upper()
        )
        invalid_kinds = sorted(
            set(frame["signal_source_kind"]) - ALLOWED_SIGNAL_SOURCE_KINDS
        )
        if invalid_kinds:
            raise ValueError(f"unverified signal source kinds: {invalid_kinds}")
        frame["signal_is_synthetic"] = cls._strict_boolean(
            frame["signal_is_synthetic"]
        )
        expected_synthetic = (
            frame["signal_source_kind"] == SYNTHETIC_SIGNAL_SOURCE_KIND
        )
        if not expected_synthetic.equals(frame["signal_is_synthetic"]):
            raise ValueError("signal source kind and synthetic flag do not match")
        timestamps = frame[SIGNAL_PROVENANCE_TIMESTAMP_COLUMNS].stack()
        summary = SignalProvenanceSummary(
            rows=int(len(frame)),
            source_kinds=sorted(frame["signal_source_kind"].unique().tolist()),
            synthetic_rows=int(frame["signal_is_synthetic"].sum()),
            observed_rows=int((~frame["signal_is_synthetic"]).sum()),
            min_as_of_at=timestamps.min().isoformat(),
            max_as_of_at=timestamps.max().isoformat(),
        )
        frame.attrs["signal_provenance"] = asdict(summary)
        return frame, summary

    @staticmethod
    def _strict_boolean(values: pd.Series) -> pd.Series:
        if pd.api.types.is_bool_dtype(values):
            return values.astype(bool)
        normalized = values.astype(str).str.strip().str.lower()
        if not normalized.isin({"true", "false"}).all():
            raise ValueError("signal_is_synthetic must contain only true or false")
        return normalized.eq("true")

    @classmethod
    def audit_label_proxy(cls, frame: pd.DataFrame) -> dict[str, Any]:
        """예약 잔량이 정답을 사실상 복사한 비정상 패턴인지 horizon별 점검한다."""

        required = {"horizon_days", "booking_on_hand", "target_rooms_sold"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"label-proxy audit missing columns: {missing}")
        horizons = []
        for horizon, group in frame.groupby("horizon_days", sort=True):
            booking = group["booking_on_hand"].astype(float).to_numpy()
            actual = group["target_rooms_sold"].astype(float).to_numpy()
            exact_rate = float(np.isclose(booking, actual, atol=1e-9).mean())
            correlation = (
                float(np.corrcoef(booking, actual)[0, 1])
                if len(group) > 1
                and float(np.std(booking)) > 0
                and float(np.std(actual)) > 0
                else None
            )
            blocked = bool(
                len(group) >= cls._MIN_PROXY_AUDIT_ROWS
                and exact_rate >= cls._MAX_EXACT_MATCH_RATE
                and correlation is not None
                and correlation >= cls._MAX_PROXY_CORRELATION
            )
            horizons.append(
                {
                    "horizon_days": int(horizon),
                    "rows": int(len(group)),
                    "exact_match_rate": exact_rate,
                    "correlation": correlation,
                    "mean_absolute_gap": float(np.abs(booking - actual).mean()),
                    "blocked": blocked,
                }
            )
        blocked_horizons = [
            row["horizon_days"] for row in horizons if row["blocked"]
        ]
        return {
            "passed": not blocked_horizons,
            "blocked_horizons": blocked_horizons,
            "thresholds": {
                "minimum_rows": cls._MIN_PROXY_AUDIT_ROWS,
                "exact_match_rate": cls._MAX_EXACT_MATCH_RATE,
                "correlation": cls._MAX_PROXY_CORRELATION,
            },
            "horizons": horizons,
        }

    @staticmethod
    def validate_aligned_splits(
        datasets: Mapping[str, pd.DataFrame],
    ) -> dict[str, Any]:
        """2018~2026 공통 기간과 D+1~D+7 분할이 모두 존재하는지 검증한다."""
        return AlignedSplitValidator.validate(datasets)


class ProductionApprovalGate:
    """실데이터·정렬 비교·shadow 검증·사람 승인이 모두 있어야 승인한다."""

    @staticmethod
    def evaluate(
        dataset_manifest: Mapping[str, Any],
        benchmark_report: Mapping[str, Any],
        shadow_report: Mapping[str, Any],
        *,
        approved_by: str | None,
        approved_at: str | None,
    ) -> dict[str, Any]:
        """데이터·평가·shadow·사람 승인 증거를 종합해 최종 판정을 반환한다."""

        blockers: list[str] = []
        provenance = dataset_manifest.get("signal_provenance") or {}
        if dataset_manifest.get("synthetic_only") is not False:
            blockers.append("training_or_evaluation_data_is_not_observed")
        if provenance.get("source_kinds") != [OBSERVED_SIGNAL_SOURCE_KIND]:
            blockers.append("signal_point_in_time_provenance_is_not_observed")
        audits = dataset_manifest.get("label_proxy_audits") or {}
        if not audits or not all(item.get("passed") is True for item in audits.values()):
            blockers.append("label_proxy_audit_did_not_pass")
        if benchmark_report.get("comparison_mode") != "aligned_same_rows_equal_budget":
            blockers.append("model_comparison_is_not_aligned")
        if benchmark_report.get("metric_contract_version") != METRIC_CONTRACT_VERSION:
            blockers.append("evaluation_metric_contract_is_missing_or_outdated")
        benchmark_gates = benchmark_report.get("approval_gates") or {}
        if not benchmark_gates or not all(value is True for value in benchmark_gates.values()):
            blockers.append("aligned_benchmark_did_not_pass")
        self_evaluation = benchmark_report.get("self_evaluation") or {}
        if self_evaluation.get("technical_validation_passed") is not True:
            blockers.append("self_evaluation_did_not_pass")
        if self_evaluation.get("production_eligible") is not True:
            blockers.append("self_evaluation_is_not_production_eligible")
        if shadow_report.get("data_is_synthetic") is not False:
            blockers.append("shadow_validation_is_not_observed")
        if int(shadow_report.get("observed_days") or 0) < 90:
            blockers.append("shadow_validation_is_shorter_than_90_days")
        shadow_keys = (
            "overall_better_than_baseline",
            "all_horizons_better_than_baseline",
            "all_properties_better_than_baseline",
            "all_room_types_within_threshold",
        )
        if not all(shadow_report.get(key) is True for key in shadow_keys):
            blockers.append("shadow_quality_gates_did_not_pass")
        evidence_checks = shadow_report.get("evidence_checks") or {}
        if not evidence_checks or not all(
            value is True for value in evidence_checks.values()
        ):
            blockers.append("shadow_evidence_checks_did_not_pass")
        shadow_quality = shadow_report.get("quality_gates") or {}
        if not shadow_quality or not all(
            value is True for value in shadow_quality.values()
        ):
            blockers.append("shadow_extended_quality_gates_did_not_pass")
        if shadow_report.get("metric_contract_version") != METRIC_CONTRACT_VERSION:
            blockers.append("shadow_metric_contract_is_missing_or_outdated")
        if not approved_by or not approved_by.strip():
            blockers.append("human_approver_is_missing")
        try:
            approval_time = datetime.fromisoformat(approved_at or "")
            if approval_time.tzinfo is None:
                raise ValueError
        except ValueError:
            blockers.append("human_approval_timestamp_is_invalid")
        return {
            "decision": "APPROVED" if not blockers else "BLOCKED",
            "production_approved": not blockers,
            "blockers": blockers,
            "human_approved_by": approved_by,
            "human_approved_at": approved_at,
        }
