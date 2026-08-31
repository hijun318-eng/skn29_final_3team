from __future__ import annotations

import asyncio
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import warnings

from fastapi import HTTPException
import httpx
import joblib
from pydantic import ValidationError
import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.ml_router import RoomDemandRequest, _require_ml_access
from app.contracts import RequestContext, Role
from app.adapters.ml_prediction_client import MLPredictionClient
from app.services.ml_prediction_service import MLPredictionService
from src.ml.room_demand_timeseries import runtime_api
from src.ml.room_demand_timeseries.contracts import FEATURE_COLUMNS
from src.ml.room_demand_timeseries.runtime_api import (
    TimeSeriesRuntime,
    _declared_request_body_size,
    load_model_artifact,
    runtime_estimator_types,
    validate_hgbr_runtime,
    validate_history_source,
)
from src.ml.runtime_trust import (
    ML_RUNTIME_AUTH_MAX_BODY_BYTES,
    MLRuntimeNonceGuard,
    MLRuntimeTrustError,
    request_auth_headers,
    response_auth_headers,
    verify_request_auth,
    verify_response_auth,
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


@pytest.fixture(autouse=True)
def approved_ml_release_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ML_RUNTIME_HMAC_SECRET", "test-ml-runtime-secret-that-is-at-least-32-bytes")
    monkeypatch.setenv("ML_APPROVED_MODEL_VERSION", "room-demand-timeseries-hgbr-v2.2.0")
    monkeypatch.setenv("ML_APPROVED_MODEL_SHA256", "a" * 64)
    monkeypatch.setenv("ML_APPROVED_FEATURE_CONTRACT_SHA256", "b" * 64)


def _runtime_capabilities() -> dict[str, object]:
    return {
        "schema_version": "MLRuntimeCapability.v1",
        "prediction_contract_version": "MLRoomDemandPrediction.v1",
        "model_version": "room-demand-timeseries-hgbr-v2.2.0",
        "model_hash": "a" * 64,
        "feature_contract_sha256": "b" * 64,
        "model_type": "historical-only-direct-multi-horizon-hgbr",
        "estimator_type": "HistGradientBoostingRegressor",
        "approval": "CONDITIONAL_PASS",
        "min_horizon_days": 1,
        "max_horizon_days": 7,
        "model_max_horizon_days": 10,
        "properties": [
            {
                "property_id": "GRAND",
                "min_as_of": "2020-01-07",
                "max_as_of": "2026-08-31",
                "feature_max_as_of": "2026-08-28",
                "history_rows": 1234,
            }
        ],
        "synthetic_training_data": True,
        "history_source": {
            "table": "pms.ml_evaluation.approved_history",
            "row_count": 8766,
            "property_count": 3,
            "series_count": 9,
            "min_date": "2024-01-01",
            "max_date": "2026-08-31",
            "synthetic_only": True,
            "summary_query_id": "trino-history-summary-1",
            "continuity_query_id": "trino-history-continuity-1",
        },
        "query_id": "trino-capability-query-1",
    }


def _prediction_result(horizon_days: int = 7) -> dict[str, object]:
    as_of = date(2026, 8, 28)
    targets = [
        as_of + timedelta(days=offset)
        for offset in range(1, horizon_days + 1)
    ]
    return {
        "schema_version": "MLRoomDemandPrediction.v1",
        "status": "SUCCEEDED",
        "execution_id": "fdcb43b6-5479-4c1b-8745-55e370180071",
        "property_id": "GRAND",
        "as_of": as_of.isoformat(),
        "feature_as_of": as_of.isoformat(),
        "horizon_days": horizon_days,
        "model_version": "room-demand-timeseries-hgbr-v2.2.0",
        "model_hash": "a" * 64,
        "feature_contract_sha256": "b" * 64,
        "daily_forecasts": [
            {
                "target_date": target.isoformat(),
                "total_available_rooms": 100.0,
                "predicted_occupied_rooms": 60.0,
                "predicted_available_rooms": 40.0,
                "predicted_occupancy_rate": 0.6,
            }
            for target in targets
        ],
        "room_type_forecasts": [
            {
                "target_date": target.isoformat(),
                "room_type_code": "STANDARD",
                "available_rooms": 100.0,
                "predicted_rooms_raw": 60.0,
                "predicted_rooms": 60.0,
                "occupancy_rate": 0.6,
            }
            for target in targets
        ],
        "provenance": {
            "source": "TRINO_HISTORICAL_DAILY_FACTS",
            "history_table": "pms.ml_evaluation.approved_history",
            "trino_query_id": "trino-prediction-query-1",
            "feature_as_of": "2026-08-28",
            "request_as_of": "2026-08-28",
            "rag_called": False,
        },
    }


class _StubMLClient:
    def __init__(
        self,
        capabilities: dict[str, object],
        prediction: dict[str, object] | None = None,
    ) -> None:
        self.capability_payload = capabilities
        self.prediction_payload = prediction or _prediction_result()
        self.prediction_calls = 0

    async def capabilities(self) -> dict[str, object]:
        return self.capability_payload

    async def predict(self, payload: dict[str, object]) -> dict[str, object]:
        self.prediction_calls += 1
        return self.prediction_payload


class _RecordingSession:
    def __init__(self) -> None:
        self.execute_calls = 0

    async def execute(self, statement: object, parameters: object) -> None:
        self.execute_calls += 1


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


def test_ml_deployment_example_pins_actual_runtime_artifacts() -> None:
    env_values = {
        key: value
        for line in (
            ROOT / "infrastructure" / "database" / ".env.example"
        ).read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
        for key, value in [line.split("=", 1)]
    }
    manifest = json.loads(
        (ARTIFACT_DIR / "model_manifest.json").read_text(encoding="utf-8")
    )

    assert env_values["ML_APPROVED_MODEL_VERSION"] == manifest["model_version"]
    assert env_values["ML_APPROVED_MODEL_SHA256"] == hashlib.sha256(
        (ARTIFACT_DIR / "model.joblib").read_bytes()
    ).hexdigest()
    assert env_values["ML_APPROVED_FEATURE_CONTRACT_SHA256"] == hashlib.sha256(
        (ARTIFACT_DIR / "feature_contract.json").read_bytes()
    ).hexdigest()


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


def test_ml_artifact_loader_returns_a_compatible_joblib_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "model.joblib"
    sentinel = object()
    monkeypatch.setattr(runtime_api.joblib, "load", lambda path: sentinel)

    assert load_model_artifact(artifact) is sentinel


def test_ml_artifact_loader_rejects_a_sklearn_version_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "model.joblib"

    def incompatible_load(_path: Path) -> object:
        warnings.warn(
            runtime_api.InconsistentVersionWarning(
                estimator_name="HistGradientBoostingRegressor",
                current_sklearn_version="1.8.0",
                original_sklearn_version="1.9.0",
            )
        )
        return object()

    monkeypatch.setattr(runtime_api.joblib, "load", incompatible_load)

    with pytest.raises(RuntimeError, match="scikit-learn version is incompatible"):
        load_model_artifact(artifact)


def test_ml_artifact_loader_preserves_unrelated_warnings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "model.joblib"
    sentinel = object()

    def load_with_unrelated_warning(_path: Path) -> object:
        warnings.warn("unrelated model warning", UserWarning)
        return sentinel

    monkeypatch.setattr(runtime_api.joblib, "load", load_with_unrelated_warning)

    with pytest.warns(UserWarning, match="unrelated model warning"):
        result = load_model_artifact(artifact)

    assert result is sentinel


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


def test_backend_accepts_only_a_complete_hgbr_runtime_capability() -> None:
    service = MLPredictionService(_StubMLClient(_runtime_capabilities()))  # type: ignore[arg-type]

    capabilities = asyncio.run(service.capabilities())

    assert capabilities["estimator_type"] == "HistGradientBoostingRegressor"
    assert capabilities["properties"][0]["property_id"] == "GRAND"


def test_backend_rejects_an_incomplete_ml_runtime_capability() -> None:
    incomplete = _runtime_capabilities()
    incomplete["model_hash"] = "not-a-sha256"
    service = MLPredictionService(_StubMLClient(incomplete))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="capability response is invalid"):
        asyncio.run(service.capabilities())


def test_backend_rejects_runtime_release_outside_environment_pins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ML_APPROVED_MODEL_SHA256", "c" * 64)
    service = MLPredictionService(_StubMLClient(_runtime_capabilities()))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="approved release pins"):
        asyncio.run(service.capabilities())


def test_backend_and_runtime_exchange_is_hmac_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"test-ml-runtime-secret-that-is-at-least-32-bytes"

    class StubRuntime:
        hmac_secret = secret

        @staticmethod
        def capabilities() -> dict[str, object]:
            return _runtime_capabilities()

        @staticmethod
        def predict(request: object) -> dict[str, object]:
            return {"property_id": request.property_id}  # type: ignore[attr-defined]

    monkeypatch.setattr(runtime_api, "state", StubRuntime())
    monkeypatch.setenv("ML_RUNTIME_URL", "http://ml-runtime.test")
    client = MLPredictionClient(transport=httpx.ASGITransport(app=runtime_api.app))

    result = asyncio.run(client.capabilities())
    prediction = asyncio.run(
        client.predict(
            {"property_id": "GRAND", "as_of": "2026-08-28", "horizon_days": 7}
        )
    )
    with pytest.raises(httpx.HTTPStatusError) as signed_error:
        asyncio.run(client.predict({"property_id": "GRAND"}))

    assert result["model_version"] == "room-demand-timeseries-hgbr-v2.2.0"
    assert prediction == {"property_id": "GRAND"}
    assert signed_error.value.response.status_code == 422


def test_runtime_rejects_a_replayed_authenticated_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"test-ml-runtime-secret-that-is-at-least-32-bytes"

    class StubRuntime:
        hmac_secret = secret

        @staticmethod
        def capabilities() -> dict[str, object]:
            return _runtime_capabilities()

    async def send_twice() -> tuple[httpx.Response, httpx.Response]:
        headers = request_auth_headers(secret, "GET", "/capabilities", b"")
        transport = httpx.ASGITransport(app=runtime_api.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://ml-runtime.test",
        ) as client:
            first = await client.get("/capabilities", headers=headers)
            second = await client.get("/capabilities", headers=headers)
        return first, second

    monkeypatch.setattr(runtime_api, "state", StubRuntime())
    monkeypatch.setattr(runtime_api, "_request_nonce_guard", MLRuntimeNonceGuard())

    first, second = asyncio.run(send_twice())

    assert first.status_code == 200
    assert second.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"content-length": str(ML_RUNTIME_AUTH_MAX_BODY_BYTES + 1)},
        {"transfer-encoding": "chunked"},
        {},
    ],
)
def test_runtime_rejects_unbounded_post_bodies_before_reading(headers: dict[str, str]) -> None:
    request = SimpleNamespace(headers=headers, method="POST")

    with pytest.raises(MLRuntimeTrustError):
        _declared_request_body_size(request)  # type: ignore[arg-type]


def test_runtime_not_ready_is_a_signed_generic_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_api, "state", None)
    monkeypatch.setattr(runtime_api, "_request_nonce_guard", MLRuntimeNonceGuard())
    monkeypatch.setenv("ML_RUNTIME_URL", "http://ml-runtime.test")
    client = MLPredictionClient(transport=httpx.ASGITransport(app=runtime_api.app))

    with pytest.raises(httpx.HTTPStatusError) as captured:
        asyncio.run(client.capabilities())

    assert captured.value.response.status_code == 503
    assert captured.value.response.json() == {"detail": "ML runtime is not ready"}


def test_runtime_unhandled_failure_is_a_signed_generic_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"test-ml-runtime-secret-that-is-at-least-32-bytes"

    class FailingRuntime:
        hmac_secret = secret

        @staticmethod
        def capabilities() -> dict[str, object]:
            raise RuntimeError("sensitive trino failure")

    monkeypatch.setattr(runtime_api, "state", FailingRuntime())
    monkeypatch.setattr(runtime_api, "_request_nonce_guard", MLRuntimeNonceGuard())
    monkeypatch.setenv("ML_RUNTIME_URL", "http://ml-runtime.test")
    client = MLPredictionClient(transport=httpx.ASGITransport(app=runtime_api.app))

    with pytest.raises(httpx.HTTPStatusError) as captured:
        asyncio.run(client.capabilities())

    assert captured.value.response.status_code == 500
    assert captured.value.response.json() == {"detail": "ML runtime request failed"}
    assert "sensitive trino failure" not in captured.value.response.text


@pytest.mark.parametrize("now", [69, 131])
def test_runtime_rejects_request_signature_outside_clock_window(now: int) -> None:
    secret = b"test-ml-runtime-secret-that-is-at-least-32-bytes"
    headers = request_auth_headers(
        secret,
        "GET",
        "/capabilities",
        b"",
        timestamp=100,
        nonce="a" * 32,
    )

    with pytest.raises(MLRuntimeTrustError, match="outside the allowed window"):
        verify_request_auth(
            secret,
            headers,
            "GET",
            "/capabilities",
            b"",
            now=now,
        )


@pytest.mark.parametrize(
    ("path", "body", "signature"),
    [
        ("/capabilities", b'{"tampered":true}', None),
        ("/predictions/room-demand", b"", None),
        ("/capabilities", b"", "0" * 64),
    ],
)
def test_runtime_rejects_tampered_request_binding(
    path: str,
    body: bytes,
    signature: str | None,
) -> None:
    secret = b"test-ml-runtime-secret-that-is-at-least-32-bytes"
    headers = request_auth_headers(
        secret,
        "GET",
        "/capabilities",
        b"",
        timestamp=100,
        nonce="a" * 32,
    )
    if signature is not None:
        headers["X-Answervice-ML-Signature"] = signature

    with pytest.raises(MLRuntimeTrustError, match="signature is invalid"):
        verify_request_auth(
            secret,
            headers,
            "GET",
            path,
            body,
            now=100,
        )


def test_runtime_response_binds_nonce_status_path_and_error_body() -> None:
    secret = b"test-ml-runtime-secret-that-is-at-least-32-bytes"
    nonce = "a" * 32
    body = b'{"detail":"invalid prediction"}'
    headers = response_auth_headers(
        secret,
        "/predictions/room-demand",
        422,
        nonce,
        body,
    )

    verify_response_auth(
        secret,
        headers,
        "/predictions/room-demand",
        422,
        nonce,
        body,
    )
    with pytest.raises(MLRuntimeTrustError, match="another request"):
        verify_response_auth(
            secret,
            headers,
            "/predictions/room-demand",
            422,
            "b" * 32,
            body,
        )
    with pytest.raises(MLRuntimeTrustError, match="signature is invalid"):
        verify_response_auth(
            secret,
            headers,
            "/predictions/room-demand",
            422,
            nonce,
            body + b"!",
        )


def test_runtime_oversized_authenticated_response_is_a_signed_bounded_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"test-ml-runtime-secret-that-is-at-least-32-bytes"

    class OversizedRuntime:
        hmac_secret = secret

        @staticmethod
        def capabilities() -> dict[str, str]:
            return {"oversized": "x" * (ML_RUNTIME_AUTH_MAX_BODY_BYTES + 1)}

    monkeypatch.setattr(runtime_api, "state", OversizedRuntime())
    monkeypatch.setenv("ML_RUNTIME_URL", "http://ml-runtime.test")
    client = MLPredictionClient(transport=httpx.ASGITransport(app=runtime_api.app))

    with pytest.raises(httpx.HTTPStatusError) as captured:
        asyncio.run(client.capabilities())

    assert captured.value.response.status_code == 502
    assert len(captured.value.response.content) < ML_RUNTIME_AUTH_MAX_BODY_BYTES
    assert captured.value.response.json() == {
        "detail": "Authenticated ML runtime response is too large"
    }


def test_backend_rejects_unsigned_runtime_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unsigned(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_runtime_capabilities())

    monkeypatch.setenv("ML_RUNTIME_URL", "http://ml-runtime.test")
    client = MLPredictionClient(transport=httpx.MockTransport(unsigned))

    with pytest.raises(MLRuntimeTrustError, match="missing ML runtime authentication"):
        asyncio.run(client.capabilities())


def test_runtime_capability_uses_actual_model_and_feature_artifact_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubTrino:
        def query(self, _sql: str) -> SimpleNamespace:
            return SimpleNamespace(
                rows=[
                    {
                        "property_id": "GRAND",
                        "min_date": "2024-01-01",
                        "max_date": "2026-08-31",
                        "history_rows": 974,
                    }
                ],
                query_id="trino-capability-test",
            )

    history_source = {
        "table": "pms.ml_evaluation.approved_history",
        "row_count": 8766,
        "property_count": 3,
        "series_count": 9,
        "min_date": "2024-01-01",
        "max_date": "2026-08-31",
        "synthetic_only": True,
        "summary_query_id": "summary",
        "continuity_query_id": "continuity",
    }
    monkeypatch.setenv("ML_MODEL_ARTIFACT", str(ARTIFACT_DIR / "model.joblib"))
    monkeypatch.setenv("ML_MODEL_MANIFEST", str(ARTIFACT_DIR / "model_manifest.json"))
    monkeypatch.setenv("ML_MODEL_APPROVAL", str(ARTIFACT_DIR / "model.approval.json"))
    monkeypatch.setenv("ML_FEATURE_CONTRACT", str(ARTIFACT_DIR / "feature_contract.json"))
    monkeypatch.setenv("ML_HISTORY_TABLE", "pms.ml_evaluation.approved_history")
    monkeypatch.setenv("ML_ALLOW_CONDITIONAL", "true")
    monkeypatch.setenv("TRINO_URL", "https://trino.test")
    monkeypatch.setenv("TRINO_RUNTIME_USER", "runtime")
    monkeypatch.setenv("TRINO_RUNTIME_PASSWORD", "secret")
    monkeypatch.setenv("TRINO_TLS_CA_FILE", "ca.pem")
    monkeypatch.setattr(runtime_api, "TrinoClient", lambda **_kwargs: StubTrino())
    monkeypatch.setattr(
        runtime_api,
        "validate_history_source",
        lambda *_args, **_kwargs: history_source,
    )
    compatible_model = SimpleNamespace(
        predict_raw=lambda *_args, **_kwargs: None,
        predict=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        runtime_api,
        "load_model_artifact",
        lambda _artifact: compatible_model,
    )
    monkeypatch.setattr(
        runtime_api,
        "validate_hgbr_runtime",
        lambda _model_type, _model: "HistGradientBoostingRegressor",
    )

    capability = TimeSeriesRuntime().capabilities()

    assert capability["model_hash"] == hashlib.sha256(
        (ARTIFACT_DIR / "model.joblib").read_bytes()
    ).hexdigest()
    assert capability["feature_contract_sha256"] == hashlib.sha256(
        (ARTIFACT_DIR / "feature_contract.json").read_bytes()
    ).hexdigest()


def test_prediction_release_drift_is_blocked_before_audit_storage() -> None:
    changed = _prediction_result()
    changed["model_hash"] = "b" * 64
    client = _StubMLClient(_runtime_capabilities(), changed)
    session = _RecordingSession()
    service = MLPredictionService(client)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="release changed"):
        asyncio.run(
            service.predict(  # type: ignore[arg-type]
                session,
                {"property_id": "GRAND", "as_of": "2026-08-28", "horizon_days": 7},
            )
        )

    assert client.prediction_calls == 1
    assert session.execute_calls == 0


def test_prediction_feature_contract_drift_is_blocked_before_audit_storage() -> None:
    changed = _prediction_result()
    changed["feature_contract_sha256"] = "c" * 64
    client = _StubMLClient(_runtime_capabilities(), changed)
    session = _RecordingSession()
    service = MLPredictionService(client)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="release changed"):
        asyncio.run(
            service.predict(  # type: ignore[arg-type]
                session,
                {"property_id": "GRAND", "as_of": "2026-08-28", "horizon_days": 7},
            )
        )

    assert client.prediction_calls == 1
    assert session.execute_calls == 0


def test_matching_prediction_release_is_saved_once() -> None:
    client = _StubMLClient(_runtime_capabilities())
    session = _RecordingSession()
    service = MLPredictionService(client)  # type: ignore[arg-type]

    result = asyncio.run(
        service.predict(  # type: ignore[arg-type]
            session,
            {"property_id": "grand", "as_of": "2026-08-28", "horizon_days": 7},
        )
    )

    assert result["status"] == "SUCCEEDED"
    assert session.execute_calls == 1


def test_inconsistent_prediction_values_are_blocked_before_audit_storage() -> None:
    changed = _prediction_result()
    daily = changed["daily_forecasts"]
    assert isinstance(daily, list)
    first = daily[0]
    assert isinstance(first, dict)
    first["predicted_available_rooms"] = 99.0
    client = _StubMLClient(_runtime_capabilities(), changed)
    session = _RecordingSession()

    with pytest.raises(RuntimeError, match="prediction response is invalid"):
        asyncio.run(
            MLPredictionService(client).predict(  # type: ignore[arg-type]
                session,
                {
                    "property_id": "GRAND",
                    "as_of": "2026-08-28",
                    "horizon_days": 7,
                },
            )
        )

    assert session.execute_calls == 0


def test_prediction_history_source_drift_is_blocked_before_audit_storage() -> None:
    changed = _prediction_result()
    changed["provenance"] = {
        **changed["provenance"],  # type: ignore[dict-item]
        "history_table": "pms.ml_evaluation.unapproved_history",
    }
    client = _StubMLClient(_runtime_capabilities(), changed)
    session = _RecordingSession()
    service = MLPredictionService(client)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="provenance is incomplete"):
        asyncio.run(
            service.predict(  # type: ignore[arg-type]
                session,
                {"property_id": "GRAND", "as_of": "2026-08-28", "horizon_days": 7},
            )
        )

    assert session.execute_calls == 0


def test_ml_runtime_has_an_explicit_profile_without_joining_full_by_default() -> None:
    compose = (ROOT / "infrastructure" / "ml" / "compose.fragment.yml").read_text(encoding="utf-8")

    assert compose.count("profiles: [ml, ml-candidate]") == 2
    assert "profiles: [ml, ml-candidate, full]" not in compose
    assert "room-demand-timeseries-hgbr-v2.2.0" in compose
    assert "room-demand-hgbr-optimization-v3.3.0" not in compose
    assert "pms.ml_evaluation.room_demand_daily_facts_v43_20260830" in compose
    assert "ml-history-bootstrap:" in compose
    assert "condition: service_completed_successfully" in compose
    assert "../ml/sql/01_room_demand_history_v43_synthetic.sql" in compose
    assert "ML_RUNTIME_HMAC_SECRET" in compose


def _history_summary(**overrides: object) -> dict[str, object]:
    return {
        "row_count": 8766,
        "property_count": 3,
        "min_date": "2024-01-01",
        "max_date": "2026-08-31",
        "invalid_rows": 0,
        "synthetic_rows": 8766,
        "non_synthetic_rows": 0,
        **overrides,
    }


def _history_continuity(**overrides: object) -> dict[str, object]:
    return {
        "series_count": 9,
        "min_series_rows": 974,
        "invalid_series": 0,
        **overrides,
    }


def test_ml_history_preflight_validates_values_continuity_and_source_mode() -> None:
    class StubTrino:
        def __init__(self, responses: list[list[dict[str, object]]]) -> None:
            self.responses = responses
            self.sql: list[str] = []

        def query(self, sql: str) -> SimpleNamespace:
            self.sql.append(sql)
            return SimpleNamespace(
                rows=self.responses.pop(0),
                query_id=f"trino-history-{len(self.sql)}",
            )

    ready = StubTrino([[_history_summary()], [_history_continuity()]])
    receipt = validate_history_source(
        ready,  # type: ignore[arg-type]
        "pms.ml_evaluation.approved_history",
        expected_synthetic=True,
    )

    assert len(ready.sql) == 2
    assert all("pms.ml_evaluation.approved_history" in sql for sql in ready.sql)
    assert "count_if" in ready.sql[0]
    assert "date_diff" in ready.sql[1]
    assert receipt == {
        "table": "pms.ml_evaluation.approved_history",
        "row_count": 8766,
        "property_count": 3,
        "series_count": 9,
        "min_date": "2024-01-01",
        "max_date": "2026-08-31",
        "synthetic_only": True,
        "summary_query_id": "trino-history-1",
        "continuity_query_id": "trino-history-2",
    }


@pytest.mark.parametrize(
    ("summary", "message"),
    [
        (_history_summary(row_count=0, synthetic_rows=0), "empty or unreadable"),
        (_history_summary(invalid_rows=1), "has 1 invalid rows"),
        (
            _history_summary(synthetic_rows=8765, non_synthetic_rows=1),
            "synthetic mode does not match",
        ),
    ],
)
def test_ml_history_preflight_rejects_invalid_summary(
    summary: dict[str, object],
    message: str,
) -> None:
    class StubTrino:
        def query(self, sql: str) -> SimpleNamespace:
            return SimpleNamespace(rows=[summary], query_id="trino-history-summary")

    with pytest.raises(RuntimeError, match=message):
        validate_history_source(
            StubTrino(),  # type: ignore[arg-type]
            "pms.ml_evaluation.approved_history",
            expected_synthetic=True,
        )


def test_ml_history_preflight_rejects_incomplete_series() -> None:
    class StubTrino:
        def __init__(self) -> None:
            self.calls = 0

        def query(self, sql: str) -> SimpleNamespace:
            self.calls += 1
            rows = (
                [_history_summary()]
                if self.calls == 1
                else [_history_continuity(invalid_series=1)]
            )
            return SimpleNamespace(rows=rows, query_id=f"trino-history-{self.calls}")

    with pytest.raises(RuntimeError, match="incomplete time series"):
        validate_history_source(
            StubTrino(),  # type: ignore[arg-type]
            "pms.ml_evaluation.approved_history",
            expected_synthetic=True,
        )


def test_ml_history_view_is_derived_from_v43_sources_without_fixed_results() -> None:
    sql = (
        ROOT
        / "infrastructure"
        / "ml"
        / "sql"
        / "01_room_demand_history_v43_synthetic.sql"
    ).read_text(encoding="utf-8")

    assert "walkerhill_v4_3.pms_room_inventory_daily" in sql
    assert "walkerhill_v4_3.pms_stay_nights" in sql
    assert "walkerhill_v4_3.pms_stays" in sql
    assert "walkerhill_v4_3.pms_reservations" in sql
    assert "VALUES" not in sql.upper()
    assert "true AS is_synthetic" in sql
    assert 'TO :"readonly_role"' in sql
    assert "ML_HISTORY_INVALID_ROWS" in sql
    assert "ML_HISTORY_INVALID_SERIES" in sql


def test_ml_candidate_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ML_FEATURE_ENABLED", raising=False)
    for name in (
        "ML_RUNTIME_HMAC_SECRET",
        "ML_APPROVED_MODEL_VERSION",
        "ML_APPROVED_MODEL_SHA256",
        "ML_APPROVED_FEATURE_CONTRACT_SHA256",
    ):
        monkeypatch.delenv(name, raising=False)
    candidate = MLPredictionService()

    with pytest.raises(HTTPException) as captured:
        _require_ml_access(RequestContext(role=Role.ANALYST))

    assert captured.value.status_code == 503
    assert candidate._client is None


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
            horizon_days=7,
            conversation_id="not-yet-supported",
        )


def test_ml_request_global_contract_accepts_a_ninety_day_model_window() -> None:
    request = RoomDemandRequest(
        property_id="GRAND",
        as_of="2026-08-28",
        horizon_days=90,
    )

    assert request.horizon_days == 90


def test_backend_uses_runtime_capability_as_the_effective_horizon_limit() -> None:
    client = _StubMLClient(_runtime_capabilities())
    service = MLPredictionService(client)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="unsupported ML prediction horizon_days"):
        asyncio.run(
            service.predict(  # type: ignore[arg-type]
                _RecordingSession(),
                {
                    "property_id": "GRAND",
                    "as_of": "2026-08-28",
                    "horizon_days": 90,
                },
            )
        )

    assert client.prediction_calls == 0


def test_backend_accepts_a_ninety_day_replacement_model_without_code_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = _runtime_capabilities()
    capability.update(
        {
            "model_version": "approved-demand-release-vnext",
            "model_type": "approved-room-demand-regressor",
            "estimator_type": "ApprovedRegressor",
            "max_horizon_days": 90,
            "model_max_horizon_days": 90,
        }
    )
    prediction = _prediction_result(horizon_days=90)
    prediction["model_version"] = capability["model_version"]
    monkeypatch.setenv("ML_APPROVED_MODEL_VERSION", str(capability["model_version"]))
    client = _StubMLClient(capability, prediction)
    session = _RecordingSession()

    result = asyncio.run(
        MLPredictionService(client).predict(  # type: ignore[arg-type]
            session,
            {
                "property_id": "GRAND",
                "as_of": "2026-08-28",
                "horizon_days": 90,
            },
        )
    )

    assert result["horizon_days"] == 90
    assert len(result["daily_forecasts"]) == 90
    assert client.prediction_calls == 1
    assert session.execute_calls == 1
