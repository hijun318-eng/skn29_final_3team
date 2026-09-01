from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ml.room_demand_timeseries.operational_contracts import (
    OPERATIONAL_MODEL_VERSION,
)
from src.ml.room_demand_timeseries.operational_candidate import CandidateArtifactWriter
from src.ml.room_demand_timeseries.operational_metrics import METRIC_CONTRACT_VERSION
from src.ml.room_demand_timeseries.operational_promote import OperationalPromoter
from src.ml.room_demand_timeseries.operational_shadow_contracts import (
    SHADOW_SCHEMA_VERSION,
)
from src.ml.room_demand_timeseries.operational_shadow_validation import (
    ObservedShadowValidator,
)


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _staged_release(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    model_path = artifact_dir / "model.joblib"
    model_path.write_bytes(b"sealed-model")
    model_hash = _sha256(model_path)
    daily_hash = "a" * 64
    signal_hash = "b" * 64
    dataset_path = tmp_path / "dataset_manifest.json"
    _write(
        dataset_path,
        {
            "source_sha256": daily_hash,
            "signal_sha256": signal_hash,
            "synthetic_only": False,
            "signal_provenance": {"source_kinds": ["OBSERVED_PIT"]},
            "label_proxy_audits": {
                name: {"passed": True}
                for name in ("TRAIN", "VALIDATION", "TEST_A", "TEST_B")
            },
        },
    )
    _write(
        artifact_dir / "model_manifest.json",
        {
            "model_version": OPERATIONAL_MODEL_VERSION,
            "artifact_sha256": model_hash,
            "synthetic_training_data": False,
            "source_dataset_sha256": daily_hash,
            "signal_dataset_sha256": signal_hash,
        },
    )
    _write(
        artifact_dir / "feature_contract.json",
        {
            "model_version": OPERATIONAL_MODEL_VERSION,
            "feature_version": "room-demand-point-in-time-d1-d7-v4.0.0",
            "signal_provenance_required": True,
        },
    )
    feature_contract_hash = _sha256(artifact_dir / "feature_contract.json")
    benchmark_path = tmp_path / "aligned_benchmark.json"
    _write(
        benchmark_path,
        {
            "comparison_mode": "aligned_same_rows_equal_budget",
            "metric_contract_version": METRIC_CONTRACT_VERSION,
            "self_evaluation": {
                "technical_validation_passed": True,
                "production_eligible": True,
            },
            "dataset_manifest_sha256": _sha256(dataset_path),
            "model_artifact_sha256": {"operational_ablation": model_hash},
            "approval_gates": {
                "fixed_release_test_a": True,
                "fixed_release_test_b": True,
                "equal_budget_ablation_test_a": True,
                "equal_budget_ablation_test_b": True,
            },
        },
    )
    shadow_source_path = tmp_path / "shadow_source.csv"
    shadow_source_path.write_text("stub\nvalue\n", encoding="utf-8")
    shadow_path = tmp_path / "shadow_report.json"
    _write(
        shadow_path,
        {
            "schema_version": SHADOW_SCHEMA_VERSION,
            "model_version": OPERATIONAL_MODEL_VERSION,
            "artifact_sha256": model_hash,
            "feature_contract_sha256": feature_contract_hash,
            "source_sha256": _sha256(shadow_source_path),
            "runtime_feature_parity": "PASS",
            "metric_contract_version": METRIC_CONTRACT_VERSION,
            "data_is_synthetic": False,
            "observed_days": 90,
            "overall_better_than_baseline": True,
            "all_horizons_better_than_baseline": True,
            "all_properties_better_than_baseline": True,
            "all_room_types_within_threshold": True,
            "evidence_checks": {"observed_source_only": True},
            "quality_gates": {"all_operational_metrics": True},
        },
    )
    return artifact_dir, dataset_path, benchmark_path, shadow_path, shadow_source_path


def _accept_shadow_report(
    monkeypatch: pytest.MonkeyPatch,
    shadow_path: Path,
) -> None:
    expected = json.loads(shadow_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        ObservedShadowValidator,
        "validate",
        lambda self, frame, **kwargs: expected,
    )


def test_promoter_writes_approval_only_when_every_receipt_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_dir, dataset, benchmark, shadow, shadow_source = _staged_release(tmp_path)
    _accept_shadow_report(monkeypatch, shadow)

    approval = OperationalPromoter().promote(
        artifact_dir,
        dataset,
        benchmark,
        shadow,
        shadow_source,
        approved_by="ml-owner",
        approved_at="2026-09-01T10:00:00+09:00",
    )

    assert approval["final_decision"] == "APPROVED"
    assert approval["data_is_synthetic"] is False
    stored = json.loads(
        (artifact_dir / "model.approval.json").read_text(encoding="utf-8")
    )
    assert stored["artifact_sha256"] == approval["artifact_sha256"]


def test_promoter_does_not_write_approval_when_shadow_hash_differs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_dir, dataset, benchmark, shadow, shadow_source = _staged_release(tmp_path)
    shadow_payload = json.loads(shadow.read_text(encoding="utf-8"))
    shadow_payload["artifact_sha256"] = "c" * 64
    _write(shadow, shadow_payload)
    _accept_shadow_report(monkeypatch, shadow)

    with pytest.raises(ValueError, match="shadow_artifact_hash_mismatch"):
        OperationalPromoter().promote(
            artifact_dir,
            dataset,
            benchmark,
            shadow,
            shadow_source,
            approved_by="ml-owner",
            approved_at="2026-09-01T10:00:00+09:00",
        )

    assert not (artifact_dir / "model.approval.json").exists()


def test_candidate_writer_stages_the_validation_selected_operational_model(
    tmp_path: Path,
) -> None:
    output = tmp_path / "candidate"
    report = {
        "aligned_contract": {
            "splits": {"TRAIN": {"rows": 70}, "VALIDATION": {"rows": 70}}
        },
        "equal_budget_feature_ablation": {
            "candidate_validation": {"metrics": {"wape": 0.1}}
        },
    }
    models = {
        "v22_fixed": SimpleNamespace(name="v22"),
        "v40_fixed": SimpleNamespace(name="v40-fixed"),
        "historical_ablation": SimpleNamespace(name="historical"),
        "operational_ablation": SimpleNamespace(
            name="selected-operational",
            quality_scope={"GRAND|G_DELUXE": {"status": "APPROVED"}},
            interval_quantiles={1: {"q80": 1.0, "q95": 2.0}},
        ),
    }

    manifest = CandidateArtifactWriter().write(
        output,
        report,
        models,
        {
            "source_sha256": "a" * 64,
            "signal_sha256": "b" * 64,
            "synthetic_only": False,
        },
        selected_config={"name": "validation-selected"},
    )

    assert manifest["selected_config"]["name"] == "validation-selected"
    assert manifest["artifact_sha256"] == _sha256(output / "model.joblib")
    assert report["model_artifact_sha256"]["operational_ablation"] == manifest[
        "artifact_sha256"
    ]
