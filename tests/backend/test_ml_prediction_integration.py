from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi import HTTPException
import joblib
from pydantic import ValidationError
import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.ml_router import RoomDemandRequest, _require_ml_access
from app.contracts import RequestContext, Role
from src.ml.room_demand_timeseries.contracts import FEATURE_COLUMNS
from src.ml.room_demand_timeseries.runtime_api import (
    runtime_estimator_types,
    validate_hgbr_runtime,
    validate_history_source,
)


ARTIFACT_DIR = (
    ROOT
    / "src"
    / "ml"
    / "artifacts"
    / "room-demand-timeseries-hgbr-v2.2.0"
)
CANDIDATE_DIR = (
    ROOT
    / "src"
    / "ml"
    / "artifacts"
    / "room-demand-hgbr-optimization-v3.3.0"
)


@pytest.mark.parametrize(
    "manifest_name",
    ["SHA256SUMS.txt", "APPROVAL_SHA256SUMS.txt"],
)
def test_ml_artifact_checksum_manifest_is_current(manifest_name: str) -> None:
    """동결 모델과 승인 증거의 선언 해시가 현재 파일 바이트와 일치한다."""

    manifest_path = ARTIFACT_DIR / manifest_name
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        expected, filename = line.split(maxsplit=1)
        artifact_path = ARTIFACT_DIR / filename.strip()

        assert artifact_path.is_file(), filename
        assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == expected


def test_ml_release_is_the_integrated_hgbr_runtime() -> None:
    manifest = json.loads((ARTIFACT_DIR / "model_manifest.json").read_text(encoding="utf-8"))
    approval = json.loads((ARTIFACT_DIR / "model.approval.json").read_text(encoding="utf-8"))
    model = joblib.load(ARTIFACT_DIR / "model.joblib")

    assert manifest["model_type"].endswith("hgbr")
    assert runtime_estimator_types(model) == ("HistGradientBoostingRegressor",)
    assert approval["model_version"] == manifest["model_version"]
    assert approval["artifact_sha256"] == manifest["artifact_sha256"]
    assert validate_hgbr_runtime(manifest["model_type"], model) == (
        "HistGradientBoostingRegressor"
    )


def test_hgbr_v33_candidate_release_files_match_declared_checksums() -> None:
    """선택 반영한 v3.3 후보의 증거 파일은 원본 바이트와 일치해야 한다."""

    checksums = json.loads(
        (CANDIDATE_DIR / "release_checksums.json").read_text(encoding="utf-8")
    )
    for entry in checksums["files"]:
        candidate_path = CANDIDATE_DIR / entry["path"]

        assert candidate_path.is_file(), entry["path"]
        assert candidate_path.stat().st_size == entry["bytes"]
        assert hashlib.sha256(candidate_path.read_bytes()).hexdigest() == entry["sha256"]


def test_hgbr_v33_candidate_matches_features_but_is_not_a_serving_release() -> None:
    """v3.3은 입력 계약을 공유하지만 승인·Runtime 변환 전에는 활성화하지 않는다."""

    manifest = json.loads(
        (CANDIDATE_DIR / "model_manifest.json").read_text(encoding="utf-8")
    )
    selection = json.loads(
        (CANDIDATE_DIR / "selection.json").read_text(encoding="utf-8")
    )
    feature_contract = json.loads(
        (CANDIDATE_DIR / "feature_contract.json").read_text(encoding="utf-8")
    )
    package = joblib.load(CANDIDATE_DIR / manifest["artifact_file"])

    assert feature_contract["feature_columns_ordered"] == FEATURE_COLUMNS
    assert package["feature_columns"] == FEATURE_COLUMNS
    assert package["target_mode"] == manifest["target_mode"] == "occupancy_rate"
    assert type(package["model"]).__name__ == "HistGradientBoostingRegressor"
    assert package["model"].n_features_in_ == len(FEATURE_COLUMNS)
    assert set(package["category_maps"]) == {"property_id", "room_type_code"}
    assert manifest["artifact_sha256"] == hashlib.sha256(
        (CANDIDATE_DIR / manifest["artifact_file"]).read_bytes()
    ).hexdigest()

    assert selection["selected_operational_family"] == "hgbr"
    assert selection["observed_accuracy_winner"] == "xgboost"
    assert selection["production_approved"] is False
    assert manifest["runtime_integrated"] is False
    assert manifest["production_approved"] is False
    assert not (CANDIDATE_DIR / "model.approval.json").exists()
    assert not hasattr(package, "predict_raw")
    assert not hasattr(package, "predict")

    runtime_sklearn = next(
        line
        for line in (ROOT / "src" / "ml" / "room_demand_v3" / "requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.startswith("scikit-learn==")
    )
    candidate_sklearn = next(
        line
        for line in (
            ROOT
            / "src"
            / "ml"
            / "room_demand_timeseries"
            / "requirements.hgbr-v3.3.txt"
        )
        .read_text(encoding="utf-8")
        .splitlines()
        if line.startswith("scikit-learn==")
    )
    assert candidate_sklearn == (
        f"scikit-learn=={manifest['training_runtime_versions']['scikit_learn']}"
    )
    assert runtime_sklearn != candidate_sklearn


def test_ml_runtime_rejects_a_non_hgbr_manifest() -> None:
    model = joblib.load(ARTIFACT_DIR / "model.joblib")

    with pytest.raises(RuntimeError, match="not declared as an HGBR"):
        validate_hgbr_runtime("generic-regressor", model)


def test_ml_runtime_has_an_explicit_profile_without_joining_full_by_default() -> None:
    compose = (ROOT / "infrastructure" / "ml" / "compose.fragment.yml").read_text(encoding="utf-8")

    assert "profiles: [ml, ml-candidate]" in compose
    assert "profiles: [ml, ml-candidate, full]" not in compose
    assert "room-demand-timeseries-hgbr-v2.2.0" in compose
    assert "room-demand-hgbr-optimization-v3.3.0" not in compose


def test_ml_history_preflight_uses_the_contract_table_and_requires_a_row() -> None:
    class StubTrino:
        def __init__(self, rows: list[dict[str, int]]) -> None:
            self.rows = rows
            self.sql = ""

        def query(self, sql: str) -> SimpleNamespace:
            self.sql = sql
            return SimpleNamespace(rows=self.rows)

    ready = StubTrino([{"source_ready": 1}])
    validate_history_source(ready, "pms.ml_evaluation.approved_history")
    assert ready.sql == "SELECT 1 AS source_ready FROM pms.ml_evaluation.approved_history LIMIT 1"

    with pytest.raises(RuntimeError, match="empty or unreadable"):
        validate_history_source(StubTrino([]), "pms.ml_evaluation.approved_history")


def test_ml_candidate_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ML_FEATURE_ENABLED", raising=False)

    with pytest.raises(HTTPException) as captured:
        _require_ml_access(RequestContext(role=Role.ANALYST))

    assert captured.value.status_code == 503


def test_ml_candidate_requires_analysis_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ML_FEATURE_ENABLED", "1")

    with pytest.raises(HTTPException) as captured:
        _require_ml_access(RequestContext(role=Role.DATA_ADMIN))

    assert captured.value.status_code == 403


def test_ml_candidate_can_be_explicitly_enabled_for_analyst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ML_FEATURE_ENABLED", "true")

    _require_ml_access(RequestContext(role=Role.ANALYST))


def test_ml_request_rejects_unimplemented_conversation_binding() -> None:
    with pytest.raises(ValidationError):
        RoomDemandRequest(
            property_id="GRAND",
            as_of="2026-08-28",
            horizon=7,
            conversation_id="not-yet-supported",
        )
