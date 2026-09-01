from __future__ import annotations

from pathlib import Path

from src.ml.room_demand_timeseries.operational_readiness import (
    OperationalReadinessAuditor,
)


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = (
    ROOT
    / "src"
    / "ml"
    / "artifacts"
    / "room-demand-operational-hgbr-v4.0.0"
)


def test_current_v4_readiness_proves_safety_but_blocks_production() -> None:
    report = OperationalReadinessAuditor().audit(
        ARTIFACT,
        ROOT / "infrastructure" / "database" / ".env.example",
        dataset_manifest_path=(
            ROOT
            / "data"
            / "processed"
            / "ml_operational_v4"
            / "dataset"
            / "dataset_manifest.json"
        ),
        aligned_benchmark_path=ARTIFACT / "evaluation" / "release_comparison.json",
    )

    assert report["decision"] == "BLOCKED"
    assert report["production_approved"] is False
    assert report["checks"] == {
        "artifact_integrity": True,
        "feature_provenance_contract": True,
        "runtime_default_disabled": True,
        "observed_aligned_dataset": False,
        "aligned_v22_v40_benchmark": False,
        "observed_90_day_shadow": False,
        "human_approval_recorded": False,
    }
