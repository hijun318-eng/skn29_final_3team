from __future__ import annotations

import hashlib
from pathlib import Path
import sys

from fastapi import HTTPException
from pydantic import ValidationError
import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.ml_router import RoomDemandRequest, _require_ml_access
from app.contracts import RequestContext, Role


ARTIFACT_DIR = (
    ROOT
    / "src"
    / "ml"
    / "artifacts"
    / "room-demand-timeseries-hgbr-v2.2.0"
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
