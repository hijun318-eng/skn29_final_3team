from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.ml.room_demand_timeseries.operational_contracts import (
    OPERATIONAL_FEATURE_COLUMNS,
    OPERATIONAL_MODEL_VERSION,
    POINT_IN_TIME_SIGNAL_FEATURES,
    SIGNAL_REQUIRED_COLUMNS,
)
from src.ml.room_demand_timeseries.operational_features import OperationalFeatureBuilder
from src.ml.room_demand_timeseries.operational_modeling import OperationalDemandModel
from src.ml.room_demand_timeseries.runtime_api import validate_operational_quality_scope


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "src" / "ml" / "artifacts" / OPERATIONAL_MODEL_VERSION


class _SignalPipeline:
    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return (
            frame["booking_on_hand_ratio"].astype(float).to_numpy()
            + frame["event_demand_uplift"].astype(float).to_numpy() * 0.01
        )


def _signal_frame() -> pd.DataFrame:
    values = {column: 0.0 for column in POINT_IN_TIME_SIGNAL_FEATURES}
    values.update(
        {
            "property_id": "GRAND",
            "room_type_code": "G_DELUXE",
            "cutoff_date": "2026-08-24",
            "target_date": "2026-08-25",
            "horizon_days": 1,
            "target_sellable_rooms": 100.0,
            "booking_on_hand": 65.0,
            "booking_on_hand_ratio": 0.65,
            "reservation_as_of_at": "2026-08-24T14:00:00Z",
            "capacity_as_of_at": "2026-08-24T13:00:00Z",
            "event_as_of_at": "2026-08-24T12:00:00Z",
            "signal_source_kind": "SYNTHETIC_PIT",
            "signal_is_synthetic": True,
        }
    )
    return pd.DataFrame([values], columns=SIGNAL_REQUIRED_COLUMNS)


def _feature_frame() -> pd.DataFrame:
    values: dict[str, object] = {column: 0.0 for column in OPERATIONAL_FEATURE_COLUMNS}
    values.update(
        {
            "property_id": "GRAND",
            "room_type_code": "G_DELUXE",
            "horizon_days": 1,
            "target_sellable_rooms": 100.0,
            "booking_on_hand": 65.0,
            "booking_on_hand_ratio": 0.65,
            "event_demand_uplift": 0.2,
        }
    )
    return pd.DataFrame([values])


def test_operational_release_pins_one_version_and_hash() -> None:
    manifest = json.loads((ARTIFACT / "model_manifest.json").read_text(encoding="utf-8"))
    approval = json.loads((ARTIFACT / "model.approval.json").read_text(encoding="utf-8"))
    contract = json.loads((ARTIFACT / "feature_contract.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256((ARTIFACT / "model.joblib").read_bytes()).hexdigest()

    assert {manifest["model_version"], approval["model_version"], contract["model_version"]} == {
        OPERATIONAL_MODEL_VERSION
    }
    assert manifest["artifact_sha256"] == approval["artifact_sha256"] == digest
    assert approval["final_decision"] == "CONDITIONAL_PASS"
    assert approval["production_approved"] is False


def test_holdout_approval_covers_every_hotel_horizon_and_room_type() -> None:
    report = json.loads(
        (ARTIFACT / "evaluation" / "release_comparison.json").read_text(encoding="utf-8")
    )
    room_types = pd.read_csv(ARTIFACT / "evaluation" / "test_by_room_type.csv")

    assert report["candidate_release_approved_on_synthetic_holdout"] is True
    assert all(report["approval_gates"].values())
    assert len(room_types) == 9
    assert room_types["approval_pass"].all()
    assert room_types.loc[room_types["volume_class"] == "HIGH", "wape"].max() <= 0.30
    assert room_types.loc[room_types["volume_class"] == "LOW", "mae"].max() <= 3.0


def test_signal_contract_rejects_duplicate_point_in_time_rows() -> None:
    signals = _signal_frame()
    validated = OperationalFeatureBuilder.validate_signals(signals)
    assert list(validated.columns) == SIGNAL_REQUIRED_COLUMNS

    with pytest.raises(ValueError, match="duplicate point-in-time signal"):
        OperationalFeatureBuilder.validate_signals(pd.concat([signals, signals]))


def test_operational_model_uses_sellable_capacity_intervals_and_factors() -> None:
    model = OperationalDemandModel(
        pipeline=_SignalPipeline(),  # type: ignore[arg-type]
        model_version=OPERATIONAL_MODEL_VERSION,
        interval_quantiles={1: {"q80": 2.0, "q95": 5.0}},
        reference_values={"booking_on_hand_ratio": 0.5, "event_demand_uplift": 0.0},
    )
    frame = _feature_frame()
    prediction = model.predict(frame)
    interval = model.prediction_intervals(frame, prediction)[0]
    factors = model.influencing_factors(frame, limit=2)[0]

    assert prediction[0] == pytest.approx(65.2)
    assert interval == {
        "lower_80": pytest.approx(63.2),
        "upper_80": pytest.approx(67.2),
        "lower_95": pytest.approx(60.2),
        "upper_95": pytest.approx(70.2),
    }
    assert factors[0]["label"] == "판매 가능 객실 대비 예약률"
    assert factors[0]["impact_rooms"] == pytest.approx(15.0)


def test_signal_sql_has_no_future_capacity_fallback() -> None:
    sql = (
        ROOT / "infrastructure" / "ml" / "sql"
        / "02_room_demand_point_in_time_signals_v43_synthetic.sql"
    ).read_text(encoding="utf-8")

    assert "inventory.business_date + 7 <= bounds.max_business_date" in sql
    assert "JOIN walkerhill_v4_3.pms_room_inventory_daily AS target" in sql
    assert "COALESCE(target.available_room_nights" not in sql
    assert "UNVERIFIED_FINAL_STATE" in sql
    assert "NULL::timestamp with time zone AS capacity_as_of_at" in sql
    assert "NULL::timestamp with time zone AS event_as_of_at" in sql


def test_unapproved_room_type_blocks_operational_runtime() -> None:
    quality_scope = {
        "GRAND|G_DELUXE": {"status": "APPROVED"},
        "GRAND|G_SUITE": {"status": "NOT_APPROVED"},
    }

    with pytest.raises(RuntimeError, match="unapproved room type"):
        validate_operational_quality_scope(
            {"quality_scope": quality_scope},
            SimpleNamespace(quality_scope=quality_scope),
        )
