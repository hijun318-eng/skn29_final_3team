"""GRAND 객실 수요예측의 입력 범위와 추론 기준일 계약을 검증한다."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from sys import path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.api.ml_router import MLPredictionRequest  # noqa: E402
from app.services.ml_prediction_service import (  # noqa: E402
    MLAnalysisError,
    MLPredictionService,
)


def test_prediction_api_defaults_to_the_approved_grand_scope() -> None:
    request = MLPredictionRequest(
        metric="OCCUPANCY_RATE",
        horizon=7,
        as_of="2026-08-24",
    )

    assert request.hotel_scope == "GRAND"
    with pytest.raises(ValidationError):
        MLPredictionRequest(
            metric="OCCUPANCY_RATE",
            hotel_scope="VISTA",
            horizon=7,
            as_of="2026-08-24",
        )


def test_approved_task_rejects_a_scope_without_an_approved_artifact() -> None:
    approved = MLPredictionService._normalize_approved_request(
        {"metric": "OCCUPANCY_RATE", "horizon": 7}
    )

    assert approved["hotel_scope"] == "GRAND"
    with pytest.raises(MLAnalysisError) as failure:
        MLPredictionService._normalize_approved_request(
            {"metric": "OCCUPANCY_RATE", "hotel_scope": "VISTA", "horizon": 7}
        )
    assert failure.value.code == "ML_HOTEL_UNSUPPORTED"


def test_inference_date_prefers_the_explicit_deployment_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ML_INFERENCE_AS_OF", "2026-08-24")

    assert MLPredictionService._inference_as_of() == "2026-08-24"


def test_inference_date_uses_the_current_seoul_business_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ML_INFERENCE_AS_OF", raising=False)
    current = datetime(2026, 8, 26, 0, 5, tzinfo=ZoneInfo("Asia/Seoul"))
    with patch("app.services.ml_prediction_service.datetime") as clock:
        clock.now.return_value = current

        assert MLPredictionService._inference_as_of() == "2026-08-26"
