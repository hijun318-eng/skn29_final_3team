"""ML 동결·승인 산출물이 외부 release 정책과 manifest 증거에 결속되는지 검증한다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.ml.room_demand_timeseries.contracts import FEATURE_COLUMNS, MODEL_VERSION
from src.ml.room_demand_timeseries.finalize_approval import ApprovalFinalizer
from src.ml.room_demand_timeseries.freeze import ArtifactFreezer


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _model_manifest(*, synthetic: object) -> dict[str, Any]:
    return {
        "model_version": MODEL_VERSION,
        "model_type": "historical-only-direct-multi-horizon-hgbr",
        "feature_columns": FEATURE_COLUMNS,
        "artifact_sha256": "a" * 64,
        "training_rows": 12,
        "september_observed_values_used": False,
        "synthetic_training_data": synthetic,
        "validation_selection": {
            "metrics": {"wape": 0.1},
            "best_baseline_name": "seasonal",
            "baseline_improvement": 0.2,
        },
    }


def _dataset_manifest(*, synthetic: object) -> dict[str, Any]:
    return {
        "dataset_version": "dataset-release-from-manifest",
        "source_sha256": "b" * 64,
        "file_sha256": {"train": "c" * 64},
        "source_audit": {"synthetic_only": synthetic},
        "cutoff_ranges": {
            "TRAIN": {"min": "2020-02-03", "max": "2021-04-05"},
            "VALIDATION": {"min": "2022-06-07", "max": "2022-08-09"},
            "TEST_A": {"min": "2023-10-11", "max": "2023-12-13"},
            "TEST_B": {"min": "2024-01-15", "max": "2024-03-17"},
        },
    }


def _prepare_artifact(directory: Path, *, synthetic: object) -> Path:
    directory.mkdir(parents=True)
    _write_json(directory / "model_manifest.json", _model_manifest(synthetic=synthetic))
    _write_json(directory / "selection_trials.json", {"trials": []})
    (directory / "model.joblib").write_bytes(b"test-artifact-bytes")
    return directory


def _prepare_evaluation(directory: Path, *, decision: str = "PASS") -> None:
    _write_json(directory / "test_a" / "report.json", {"split": "A"})
    _write_json(directory / "test_b" / "report.json", {"split": "B"})
    _write_json(directory / "approval_decision.json", {"decision": decision})


def test_freezer_binds_external_feature_and_target_policy(tmp_path: Path) -> None:
    artifact_dir = _prepare_artifact(tmp_path / "artifact", synthetic=False)
    dataset_manifest = tmp_path / "dataset_manifest.json"
    _write_json(dataset_manifest, _dataset_manifest(synthetic=False))

    result = ArtifactFreezer().freeze(
        artifact_dir,
        dataset_manifest,
        feature_version="feature-policy-release-17",
        target_column="paid_units",
    )

    feature_contract = json.loads(
        (artifact_dir / "feature_contract.json").read_text(encoding="utf-8")
    )
    runtime_contract = json.loads(
        (artifact_dir / "runtime_feature_contract.json").read_text(encoding="utf-8")
    )
    model_card = (artifact_dir / "model_card.md").read_text(encoding="utf-8")
    assert feature_contract["feature_version"] == "feature-policy-release-17"
    assert feature_contract["target"] == "paid_units"
    assert runtime_contract["september_observed_values_used"] is False
    assert "declared operational daily facts" in model_card
    assert "paid_units" in model_card
    assert result["dataset_version"] == "dataset-release-from-manifest"


@pytest.mark.parametrize("invalid_synthetic", ["false", 0, None])
def test_freezer_rejects_non_boolean_synthetic_policy_before_writes(
    tmp_path: Path,
    invalid_synthetic: object,
) -> None:
    artifact_dir = _prepare_artifact(tmp_path / "artifact", synthetic=invalid_synthetic)
    dataset_manifest = tmp_path / "dataset_manifest.json"
    _write_json(dataset_manifest, _dataset_manifest(synthetic=False))

    with pytest.raises(ValueError, match="synthetic_training_data must be a boolean"):
        ArtifactFreezer().freeze(
            artifact_dir,
            dataset_manifest,
            feature_version="feature-policy-release-17",
            target_column="paid_units",
        )

    assert not (artifact_dir / "feature_contract.json").exists()


def test_approval_uses_manifest_periods_and_external_hidden_release(tmp_path: Path) -> None:
    artifact_dir = _prepare_artifact(tmp_path / "artifact", synthetic=False)
    dataset_manifest = tmp_path / "dataset_manifest.json"
    _write_json(dataset_manifest, _dataset_manifest(synthetic=False))
    _write_json(artifact_dir / "freeze_manifest.json", {"freeze_status": "FROZEN_CANDIDATE"})
    _write_json(
        artifact_dir / "feature_contract.json",
        {"feature_version": "feature-policy-release-17"},
    )
    hidden_dir = tmp_path / "hidden"
    known_dir = tmp_path / "known"
    _prepare_evaluation(hidden_dir)
    _prepare_evaluation(known_dir)
    rolling_report = tmp_path / "rolling.json"
    _write_json(rolling_report, {"summary": {"fold_count": 3}})

    approval = ApprovalFinalizer().finalize(
        artifact_dir,
        dataset_manifest,
        hidden_dir,
        known_dir,
        rolling_report,
        "PASS",
        hidden_test_release_id="hidden-policy-release-42",
    )

    assert approval["train_period"] == "2020-02-03/2021-04-05"
    assert approval["validation_period"] == "2022-06-07/2022-08-09"
    assert approval["known_test_periods"] == [
        "2023-10-11/2023-12-13",
        "2024-01-15/2024-03-17",
    ]
    assert approval["hidden_test_release_id"] == "hidden-policy-release-42"
    assert approval["feature_version"] == "feature-policy-release-17"
    assert approval["data_is_synthetic"] is False
    assert approval["approval_status"] == "VALIDATED"


@pytest.mark.parametrize(
    ("dataset_synthetic", "model_synthetic"),
    [("false", False), (False, "false"), (False, True)],
)
def test_approval_rejects_non_boolean_or_mismatched_synthetic_evidence(
    tmp_path: Path,
    dataset_synthetic: object,
    model_synthetic: object,
) -> None:
    artifact_dir = _prepare_artifact(tmp_path / "artifact", synthetic=model_synthetic)
    _write_json(artifact_dir / "freeze_manifest.json", {"freeze_status": "FROZEN_CANDIDATE"})
    _write_json(
        artifact_dir / "feature_contract.json",
        {"feature_version": "feature-policy-release-17"},
    )
    dataset_manifest = tmp_path / "dataset_manifest.json"
    _write_json(dataset_manifest, _dataset_manifest(synthetic=dataset_synthetic))

    with pytest.raises(ValueError, match="synthetic"):
        ApprovalFinalizer().finalize(
            artifact_dir,
            dataset_manifest,
            tmp_path / "unused-hidden",
            tmp_path / "unused-known",
            tmp_path / "unused-rolling.json",
            "PASS",
            hidden_test_release_id="hidden-policy-release-42",
        )

    assert not (artifact_dir / "model.approval.json").exists()
