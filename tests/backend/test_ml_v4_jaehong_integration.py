"""jaehong의 대화형 ML 경계와 v4 runtime 보안 계약을 검증한다."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date
from pathlib import Path
import sys

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.adapters.ml_prediction_client import MLPredictionClient  # noqa: E402
from app.services.ml_chat_request import MLChatRequestResolver  # noqa: E402
from app.services.ml_prediction_service import (  # noqa: E402
    MLDeploymentPolicyError,
    MLPredictionService,
)
from src.ml.runtime_trust import (  # noqa: E402
    ML_RUNTIME_NONCE_HEADER,
    response_auth_headers,
    verify_request_auth,
)


ARTIFACT = (
    ROOT / "src" / "ml" / "artifacts" / "room-demand-operational-hgbr-v4.0.0"
)


def _capability() -> dict[str, object]:
    model_hash = hashlib.sha256((ARTIFACT / "model.joblib").read_bytes()).hexdigest()
    feature_hash = hashlib.sha256(
        (ARTIFACT / "feature_contract.json").read_bytes()
    ).hexdigest()
    return {
        "schema_version": "MLRuntimeCapability.v2",
        "prediction_contract_version": "MLRoomDemandPrediction.v1",
        "model_version": "room-demand-operational-hgbr-v4.0.0",
        "model_hash": model_hash,
        "feature_contract_sha256": feature_hash,
        "model_type": "operational-point-in-time-hgbr",
        "feature_profile": "point_in_time_demand_v1",
        "estimator_type": "HistGradientBoostingRegressor",
        "approval": "CONDITIONAL_PASS",
        "approval_status": "VALIDATED_SYNTHETIC",
        "min_horizon_days": 1,
        "max_horizon_days": 7,
        "model_max_horizon_days": 7,
        "properties": [
            {
                "property_id": "GRAND",
                "min_as_of": "2025-01-01",
                "max_as_of": "2026-08-24",
                "feature_max_as_of": "2026-08-24",
                "history_rows": 1000,
                "signal_rows": 700,
            }
        ],
        "synthetic_training_data": True,
        "history_source": {
            "table": "pms.ml_evaluation.room_demand_daily_facts",
            "row_count": 1000,
            "property_count": 1,
            "series_count": 3,
            "min_date": "2025-01-01",
            "max_date": "2026-08-31",
            "synthetic_only": True,
            "summary_query_id": "history-summary",
            "continuity_query_id": "history-continuity",
        },
        "signal_source": {
            "table": "pms.ml_evaluation.room_demand_point_in_time_signals",
            "row_count": 700,
            "property_count": 1,
            "min_cutoff_date": "2025-01-01",
            "max_cutoff_date": "2026-08-24",
            "signal_source_kind": "SYNTHETIC_PIT",
            "synthetic_only": True,
            "summary_query_id": "signal-summary",
        },
        "query_id": "history-capability",
        "signal_query_id": "signal-capability",
    }


class _CapabilityClient:
    async def capabilities(self) -> dict[str, object]:
        return _capability()


def _pin_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    capability = _capability()
    monkeypatch.setenv("ML_APPROVED_MODEL_VERSION", str(capability["model_version"]))
    monkeypatch.setenv("ML_APPROVED_MODEL_SHA256", str(capability["model_hash"]))
    monkeypatch.setenv(
        "ML_APPROVED_FEATURE_CONTRACT_SHA256",
        str(capability["feature_contract_sha256"]),
    )


def test_conditional_v4_requires_explicit_local_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_environment(monkeypatch)
    service = MLPredictionService(_CapabilityClient())  # type: ignore[arg-type]

    monkeypatch.setenv("ML_ALLOW_CONDITIONAL", "false")
    with pytest.raises(MLDeploymentPolicyError):
        asyncio.run(service.capabilities())

    monkeypatch.setenv("ML_ALLOW_CONDITIONAL", "true")
    result = asyncio.run(service.capabilities())
    assert result["model_version"] == "room-demand-operational-hgbr-v4.0.0"
    assert result["synthetic_training_data"] is True


def test_chat_resolver_uses_v4_horizon_contract() -> None:
    resolution = MLChatRequestResolver().resolve(
        "GRAND 호텔의 2026년 8월 24일 기준 향후 4일 객실 수요를 예측해줘",
        _capability(),
        conversation_id=None,
    )

    assert resolution.ready is True
    assert resolution.payload == {
        "property_id": "GRAND",
        "as_of": date(2026, 8, 24),
        "horizon": 4,
    }


def test_backend_client_and_runtime_exchange_signed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_text = "test-ml-runtime-secret-that-is-at-least-32-bytes"
    monkeypatch.setenv("ML_RUNTIME_HMAC_SECRET", secret_text)
    monkeypatch.setenv("ML_RUNTIME_URL", "http://ml-runtime.test")
    response_payload = _capability()

    def handler(request: httpx.Request) -> httpx.Response:
        nonce = verify_request_auth(
            secret_text.encode(),
            request.headers,
            request.method,
            request.url.path,
            request.content,
        )
        body = json.dumps(response_payload).encode()
        headers = response_auth_headers(
            secret_text.encode(),
            request.url.path,
            200,
            request.headers[ML_RUNTIME_NONCE_HEADER],
            body,
        )
        assert nonce == request.headers[ML_RUNTIME_NONCE_HEADER]
        return httpx.Response(200, content=body, headers=headers)

    client = MLPredictionClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(client.capabilities())
    assert result["model_version"] == response_payload["model_version"]
