from __future__ import annotations

import pandas as pd
import pytest

from src.ml.room_demand_timeseries.operational_contracts import (
    OBSERVED_SIGNAL_SOURCE_KIND,
    OPERATIONAL_MODEL_VERSION,
)
from src.ml.room_demand_timeseries.operational_shadow_validation import (
    ObservedShadowValidator,
)


ARTIFACT_HASH = "a" * 64
CONTRACT_HASH = "b" * 64
SOURCE_HASH = "c" * 64


def _shadow_frame(days: int = 90, **overrides: object) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for offset in range(days):
        cutoff = pd.Timestamp("2026-01-01") + pd.Timedelta(offset, unit="D")
        cutoff_end = (
            cutoff.tz_localize("Asia/Seoul").tz_convert("UTC")
            + pd.Timedelta(1, unit="D")
        )
        for horizon in range(1, 8):
            target = cutoff + pd.Timedelta(horizon, unit="D")
            actual = 30.0 + horizon + offset % 5
            actual_available = (
                target.tz_localize("Asia/Seoul").tz_convert("UTC")
                + pd.Timedelta(1, unit="D")
            )
            row: dict[str, object] = {
                "cutoff_date": cutoff.date().isoformat(),
                "property_id": "grand",
                "room_type_code": "G_DELUXE",
                "target_date": target.date().isoformat(),
                "horizon_days": horizon,
                "target_sellable_rooms": 100.0,
                "predicted_rooms": actual + 0.5,
                "baseline_predicted_rooms": actual + 5.0,
                "actual_rooms_sold": actual,
                "lower_80": actual - 1.0,
                "upper_80": actual + 1.0,
                "lower_95": actual - 2.0,
                "upper_95": actual + 2.0,
                "inference_latency_ms": 12.0 + horizon / 10.0,
                "model_version": OPERATIONAL_MODEL_VERSION,
                "artifact_sha256": ARTIFACT_HASH,
                "feature_contract_sha256": CONTRACT_HASH,
                "runtime_feature_parity": "PASS",
                "signal_source_kind": OBSERVED_SIGNAL_SOURCE_KIND,
                "signal_is_synthetic": False,
                "reservation_as_of_at": cutoff_end - pd.Timedelta(20, unit="min"),
                "capacity_as_of_at": cutoff_end - pd.Timedelta(15, unit="min"),
                "event_as_of_at": cutoff_end - pd.Timedelta(10, unit="min"),
                "captured_at": cutoff_end + pd.Timedelta(30, unit="min"),
                "prediction_generated_at": cutoff_end
                + pd.Timedelta(31, unit="min"),
                "actual_as_of_at": actual_available + pd.Timedelta(1, unit="h"),
                "source_batch_id": f"pms-{cutoff:%Y%m%d}-0030",
            }
            row.update(overrides)
            rows.append(row)
    return pd.DataFrame(rows)


def _validate(frame: pd.DataFrame) -> dict[str, object]:
    return ObservedShadowValidator().validate(
        frame,
        expected_artifact_sha256=ARTIFACT_HASH,
        expected_feature_contract_sha256=CONTRACT_HASH,
        source_sha256=SOURCE_HASH,
    )


def test_observed_shadow_report_requires_90_complete_consecutive_days() -> None:
    report = _validate(_shadow_frame())

    assert report["observed_days"] == 90
    assert report["rows"] == 630
    assert report["overall_better_than_baseline"] is True
    assert report["all_horizons_better_than_baseline"] is True
    assert report["all_properties_better_than_baseline"] is True
    assert report["all_room_types_within_threshold"] is True
    assert report["paired_improvement_is_statistically_positive"] is True
    assert report["prediction_intervals"]["95"]["empirical_coverage"] == 1.0
    assert report["inference_latency"]["p95_ms"] < 100.0
    assert all(report["evidence_checks"].values())

    with pytest.raises(ValueError, match="shorter than 90 days"):
        _validate(_shadow_frame(days=89))


def test_shadow_rejects_synthetic_or_future_provenance() -> None:
    with pytest.raises(ValueError, match="synthetic shadow evidence is forbidden"):
        _validate(
            _shadow_frame(
                signal_source_kind="SYNTHETIC_PIT",
                signal_is_synthetic=True,
            )
        )
    with pytest.raises(ValueError, match="provenance is later than the cutoff"):
        _validate(
            _shadow_frame(
                reservation_as_of_at="2026-12-31T00:00:00Z",
            )
        )


def test_shadow_rejects_incomplete_or_duplicate_prediction_grain() -> None:
    frame = _shadow_frame()
    with pytest.raises(ValueError, match=r"incomplete D\+1 through D\+7"):
        _validate(frame.loc[frame["horizon_days"] != 7])
    with pytest.raises(ValueError, match="duplicate shadow prediction grain"):
        _validate(pd.concat([frame, frame.iloc[[0]]], ignore_index=True))


def test_shadow_rejects_predictions_created_after_actuals() -> None:
    with pytest.raises(ValueError, match="does not precede the actual outcome"):
        _validate(_shadow_frame(prediction_generated_at="2027-01-01T00:00:00Z"))


def test_shadow_rejects_invalid_intervals_or_latency() -> None:
    with pytest.raises(ValueError, match="intervals are not nested"):
        _validate(_shadow_frame(lower_80=80.0))
    with pytest.raises(ValueError, match="outside the valid range"):
        _validate(_shadow_frame(inference_latency_ms=-1.0))
