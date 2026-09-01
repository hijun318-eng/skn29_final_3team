from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.ml.room_demand_timeseries.operational_contracts import (
    OBSERVED_SIGNAL_SOURCE_KIND,
    POINT_IN_TIME_SIGNAL_FEATURES,
    SIGNAL_REQUIRED_COLUMNS,
)
from src.ml.room_demand_timeseries.operational_snapshot import (
    SnapshotBatchValidator,
)
from src.ml.room_demand_timeseries.operational_snapshot_repository import (
    ObservedSnapshotRepository,
)


ROOT = Path(__file__).resolve().parents[2]


def _snapshot_frame(**overrides: object) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    cutoff = pd.Timestamp("2026-08-24")
    for horizon in range(1, 8):
        row: dict[str, object] = {
            column: 0.0 for column in POINT_IN_TIME_SIGNAL_FEATURES
        }
        row.update(
            {
                "property_id": "grand",
                "room_type_code": "G_DELUXE",
                "cutoff_date": cutoff.date().isoformat(),
                "target_date": (cutoff + pd.Timedelta(horizon, unit="D"))
                .date()
                .isoformat(),
                "horizon_days": horizon,
                "target_sellable_rooms": 100.0,
                "booking_on_hand": 20.0 + horizon,
                "booking_on_hand_ratio": (20.0 + horizon) / 100.0,
                "reservation_as_of_at": "2026-08-24T14:30:00Z",
                "capacity_as_of_at": "2026-08-24T14:20:00Z",
                "event_as_of_at": "2026-08-24T14:10:00Z",
                "signal_source_kind": OBSERVED_SIGNAL_SOURCE_KIND,
                "signal_is_synthetic": False,
                "captured_at": "2026-08-24T15:30:00Z",
                "source_batch_id": "pms-20260824-1530",
            }
        )
        row.update(overrides)
        rows.append(row)
    return pd.DataFrame(rows, columns=SIGNAL_REQUIRED_COLUMNS + [
        "captured_at",
        "source_batch_id",
    ])


def test_observed_snapshot_requires_one_complete_d1_to_d7_batch() -> None:
    normalized, receipt = SnapshotBatchValidator().validate(
        _snapshot_frame(),
        expected_source_kind=OBSERVED_SIGNAL_SOURCE_KIND,
        source_payload_sha256="a" * 64,
    )

    assert normalized["property_id"].unique().tolist() == ["GRAND"]
    assert normalized["horizon_days"].astype(int).tolist() == list(range(1, 8))
    assert receipt.rows == 7
    assert receipt.series_count == 1
    assert receipt.completeness_passed is True

    with pytest.raises(ValueError, match=r"incomplete D\+1..D\+7"):
        SnapshotBatchValidator().validate(
            _snapshot_frame().iloc[:-1],
            expected_source_kind=OBSERVED_SIGNAL_SOURCE_KIND,
            source_payload_sha256="a" * 64,
        )


def test_snapshot_rejects_late_capture_and_unbound_hash() -> None:
    validator = SnapshotBatchValidator()

    with pytest.raises(ValueError, match="outside the cutoff grace window"):
        validator.validate(
            _snapshot_frame(captured_at="2026-08-24T22:00:00Z"),
            expected_source_kind=OBSERVED_SIGNAL_SOURCE_KIND,
            source_payload_sha256="b" * 64,
        )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        validator.validate(
            _snapshot_frame(),
            expected_source_kind=OBSERVED_SIGNAL_SOURCE_KIND,
            source_payload_sha256="not-a-hash",
        )


def test_snapshot_rejects_synthetic_rows_on_observed_path() -> None:
    with pytest.raises(ValueError, match="source kind does not match"):
        SnapshotBatchValidator().validate(
            _snapshot_frame(
                signal_source_kind="SYNTHETIC_PIT",
                signal_is_synthetic=True,
            ),
            expected_source_kind=OBSERVED_SIGNAL_SOURCE_KIND,
            source_payload_sha256="c" * 64,
        )


def test_repository_refuses_historical_backfill_before_database_access(
    tmp_path: Path,
) -> None:
    source = tmp_path / "historical-final-state.csv"
    _snapshot_frame().to_csv(source, index=False)

    with pytest.raises(ValueError, match="historical snapshot backfill is forbidden"):
        ObservedSnapshotRepository("postgresql://unused").load(source)


def test_snapshot_store_is_append_only_and_observed_only() -> None:
    sql = (
        ROOT
        / "infrastructure"
        / "ml"
        / "sql"
        / "03_room_demand_point_in_time_snapshot_store.sql"
    ).read_text(encoding="utf-8")
    synthetic_sql = (
        ROOT
        / "infrastructure"
        / "ml"
        / "sql"
        / "02_room_demand_point_in_time_signals_v43_synthetic.sql"
    ).read_text(encoding="utf-8")

    assert "BEFORE UPDATE OR DELETE" in sql
    assert "BEFORE TRUNCATE" in sql
    assert "historical backfill is forbidden" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "complete D+1 through D+7" in sql
    assert "CHECK (signal_source_kind = 'OBSERVED_PIT')" in sql
    assert "CHECK (NOT signal_is_synthetic)" in sql
    assert "REVOKE UPDATE, DELETE, TRUNCATE" in sql
    assert "room_demand_unverified_final_state_v43_20260901" in synthetic_sql
    assert "CREATE OR REPLACE VIEW\nml_evaluation.room_demand_point_in_time_signals_v43" not in synthetic_sql
