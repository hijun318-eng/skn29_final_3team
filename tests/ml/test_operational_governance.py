from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.ml.room_demand_timeseries import operational_aligned_benchmark
from src.ml.room_demand_timeseries import operational_training
from src.ml.room_demand_timeseries.operational_aligned_benchmark import (
    AlignedBenchmarkRunner,
)
from src.ml.room_demand_timeseries.operational_contracts import (
    OPERATIONAL_FEATURE_COLUMNS,
)
from src.ml.room_demand_timeseries.operational_governance import (
    OperationalDataGate,
    ProductionApprovalGate,
)
from src.ml.room_demand_timeseries.operational_metrics import METRIC_CONTRACT_VERSION
from src.ml.room_demand_timeseries.runtime_api import validate_signal_source


def _provenance_frame(**overrides: object) -> pd.DataFrame:
    row: dict[str, object] = {
        "cutoff_date": "2026-08-24",
        "reservation_as_of_at": "2026-08-24T14:00:00Z",
        "capacity_as_of_at": "2026-08-24T13:00:00Z",
        "event_as_of_at": "2026-08-24T12:00:00Z",
        "signal_source_kind": "OBSERVED_PIT",
        "signal_is_synthetic": False,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _aligned_frame(cutoff: str) -> pd.DataFrame:
    cutoff_date = pd.Timestamp(cutoff)
    return pd.DataFrame(
        [
            {
                "property_id": "GRAND",
                "room_type_code": "G_DELUXE",
                "cutoff_date": cutoff_date,
                "target_date": cutoff_date + pd.Timedelta(horizon, unit="D"),
                "horizon_days": horizon,
            }
            for horizon in range(1, 8)
        ]
    )


def _observed_dataset() -> dict[str, object]:
    return {
        "synthetic_only": False,
        "signal_provenance": {"source_kinds": ["OBSERVED_PIT"]},
        "label_proxy_audits": {
            name: {"passed": True}
            for name in ("TRAIN", "VALIDATION", "TEST_A", "TEST_B")
        },
    }


def _benchmark() -> dict[str, object]:
    return {
        "comparison_mode": "aligned_same_rows_equal_budget",
        "metric_contract_version": METRIC_CONTRACT_VERSION,
        "self_evaluation": {
            "technical_validation_passed": True,
            "production_eligible": True,
        },
        "approval_gates": {
            "fixed_release_test_a": True,
            "fixed_release_test_b": True,
            "equal_budget_ablation_test_a": True,
            "equal_budget_ablation_test_b": True,
        },
    }


def _shadow() -> dict[str, object]:
    return {
        "metric_contract_version": METRIC_CONTRACT_VERSION,
        "data_is_synthetic": False,
        "observed_days": 90,
        "overall_better_than_baseline": True,
        "all_horizons_better_than_baseline": True,
        "all_properties_better_than_baseline": True,
        "all_room_types_within_threshold": True,
        "evidence_checks": {"observed_source_only": True},
        "quality_gates": {"all_operational_metrics": True},
    }


def test_signal_provenance_accepts_only_information_known_by_cutoff() -> None:
    frame, summary = OperationalDataGate.validate_signal_provenance(
        _provenance_frame()
    )

    assert summary.source_kinds == ["OBSERVED_PIT"]
    assert summary.observed_rows == 1
    assert frame["signal_is_synthetic"].tolist() == [False]

    with pytest.raises(ValueError, match="later than the cutoff"):
        OperationalDataGate.validate_signal_provenance(
            _provenance_frame(capacity_as_of_at="2026-08-24T16:00:00Z")
        )


def test_signal_provenance_rejects_final_state_without_snapshot() -> None:
    with pytest.raises(ValueError, match="unverified signal source kinds"):
        OperationalDataGate.validate_signal_provenance(
            _provenance_frame(signal_source_kind="UNVERIFIED_FINAL_STATE")
        )


def test_label_proxy_audit_blocks_near_exact_booking_labels() -> None:
    frame = pd.DataFrame(
        {
            "horizon_days": [1] * 40,
            "booking_on_hand": list(range(40)),
            "target_rooms_sold": list(range(40)),
        }
    )

    report = OperationalDataGate.audit_label_proxy(frame)

    assert report["passed"] is False
    assert report["blocked_horizons"] == [1]


def test_aligned_split_contract_uses_common_dates_and_d1_to_d7() -> None:
    report = OperationalDataGate.validate_aligned_splits(
        {
            "TRAIN": _aligned_frame("2023-12-01"),
            "VALIDATION": _aligned_frame("2024-06-01"),
            "TEST_A": _aligned_frame("2025-06-01"),
            "TEST_B": _aligned_frame("2026-06-01"),
        }
    )

    assert report["max_horizon"] == 7
    assert set(report["splits"]) == {"TRAIN", "VALIDATION", "TEST_A", "TEST_B"}


def test_production_gate_requires_observed_90_day_shadow_and_human_approval() -> None:
    approved = ProductionApprovalGate.evaluate(
        _observed_dataset(),
        _benchmark(),
        _shadow(),
        approved_by="ml-owner",
        approved_at="2026-09-01T10:00:00+09:00",
    )

    assert approved["decision"] == "APPROVED"
    assert approved["blockers"] == []

    synthetic = _observed_dataset()
    synthetic["synthetic_only"] = True
    blocked = ProductionApprovalGate.evaluate(
        synthetic,
        _benchmark(),
        {**_shadow(), "observed_days": 89},
        approved_by="",
        approved_at="",
    )

    assert blocked["production_approved"] is False
    assert "training_or_evaluation_data_is_not_observed" in blocked["blockers"]
    assert "shadow_validation_is_shorter_than_90_days" in blocked["blockers"]


def test_runtime_signal_preflight_requires_matching_point_in_time_source() -> None:
    class StubTrino:
        sql = ""

        def query(self, sql: str) -> SimpleNamespace:
            self.sql = sql
            return SimpleNamespace(
                rows=[
                    {
                        "row_count": 700,
                        "property_count": 3,
                        "min_cutoff_date": "2018-01-01",
                        "max_cutoff_date": "2026-08-21",
                        "invalid_rows": 0,
                        "duplicate_rows": 0,
                    }
                ],
                query_id="trino-signal-1",
            )

    trino = StubTrino()
    receipt = validate_signal_source(
        trino,  # type: ignore[arg-type]
        "pms.ml_evaluation.observed_signals",
        expected_synthetic=False,
    )

    assert receipt["signal_source_kind"] == "OBSERVED_PIT"
    assert receipt["synthetic_only"] is False
    assert "capacity_as_of_at" in trino.sql
    assert "signal_source_kind <> 'OBSERVED_PIT'" in trino.sql


def _benchmark_frame(start: str, days: int = 10) -> pd.DataFrame:
    rows = []
    for offset in range(days):
        cutoff = pd.Timestamp(start) + pd.Timedelta(offset, unit="D")
        for horizon in range(1, 8):
            row: dict[str, object] = {
                column: 0.0 for column in OPERATIONAL_FEATURE_COLUMNS
            }
            target = 35.0 + (offset % 5) + horizon
            row.update(
                {
                    "property_id": "GRAND",
                    "room_type_code": "G_DELUXE",
                    "cutoff_date": cutoff,
                    "target_date": cutoff + pd.Timedelta(horizon, unit="D"),
                    "horizon_days": horizon,
                    "physical_rooms": 100.0,
                    "target_sellable_rooms": 100.0,
                    "same_weekday_mean_4w": target - 3.0,
                    "same_weekday_mean_12w": target - 2.0,
                    "target_same_weekday_mean_4w": target - 3.0,
                    "booking_on_hand": target - horizon,
                    "booking_on_hand_ratio": (target - horizon) / 100.0,
                    "target_rooms_sold": target,
                    "target_occupancy_rate": target / 100.0,
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def test_aligned_benchmark_retrains_both_sides_on_the_same_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fast_operational = {
        "name": "fast_operational",
        "loss": "squared_error",
        "learning_rate": 0.1,
        "max_iter": 5,
        "max_leaf_nodes": 7,
        "min_samples_leaf": 2,
        "l2_regularization": 0.0,
        "random_state": 7,
    }
    fast_v22 = {
        "name": "fast_v22",
        "scope": "global",
        "loss": "squared_error",
        "target_mode": "residual_rate",
        "learning_rate": 0.1,
        "max_iter": 5,
        "max_leaf_nodes": 7,
        "min_samples_leaf": 2,
        "l2_regularization": 0.0,
        "random_state": 7,
    }
    monkeypatch.setattr(operational_training, "CANDIDATES", (fast_operational,))
    monkeypatch.setattr(
        operational_aligned_benchmark, "CANDIDATES", (fast_operational,)
    )
    monkeypatch.setattr(
        operational_aligned_benchmark, "V40_RELEASE_CONFIG", fast_operational
    )
    monkeypatch.setattr(
        operational_aligned_benchmark, "V22_RELEASE_CONFIG", fast_v22
    )

    report, models = AlignedBenchmarkRunner(bootstrap_samples=100).run(
        _benchmark_frame("2023-12-01"),
        _benchmark_frame("2024-06-01"),
        _benchmark_frame("2025-06-01"),
        _benchmark_frame("2026-06-01"),
    )

    assert report["comparison_mode"] == "aligned_same_rows_equal_budget"
    assert report["equal_budget_feature_ablation"]["candidate_count_per_side"] == 1
    assert report["fixed_release_comparison"]["results"]["TEST_A"]["rows"] == 70
    assert set(models) == {
        "v22_fixed",
        "v40_fixed",
        "historical_ablation",
        "operational_ablation",
    }
