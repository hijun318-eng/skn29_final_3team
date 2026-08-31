"""승인 artifact와 감사된 Trino history만 사용하는 객실 수요 추론 HTTP runtime이다."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sklearn.exceptions import InconsistentVersionWarning

from ..room_demand_v3.trino_client import TrinoClient
from ..runtime_trust import (
    ML_RUNTIME_AUTH_MAX_BODY_BYTES,
    MLRuntimeNonceGuard,
    MLRuntimeTrustError,
    response_auth_headers,
    runtime_hmac_secret,
    verify_request_auth,
)
from .contracts import FEATURE_COLUMNS
from .features import TimeSeriesFeatureBuilder


logger = logging.getLogger(__name__)
IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
HISTORY_COLUMNS = [
    "property_id",
    "business_date",
    "room_type_code",
    "physical_rooms",
    "available_room_nights",
    "rooms_sold",
    "daily_adr",
    "cancellation_rate",
    "is_synthetic",
]
DEFAULT_RUNTIME_MAX_HORIZON_DAYS = 7
ABSOLUTE_MAX_HORIZON_DAYS = 366
ML_RUNTIME_CAPABILITY_VERSION = "MLRuntimeCapability.v2"
ML_PREDICTION_RESULT_VERSION = "MLRoomDemandPrediction.v1"


def runtime_estimator_types(model: Any) -> tuple[str, ...]:
    """동결 wrapper 안에서 실제 추론을 담당하는 estimator 종류를 반환한다."""
    pipelines = list((getattr(model, "pipelines", None) or {}).values())
    primary = getattr(model, "pipeline", None)
    if primary is not None:
        pipelines.insert(0, primary)
    estimator_types = []
    for pipeline in pipelines:
        named_steps = getattr(pipeline, "named_steps", None)
        estimator = named_steps.get("model") if isinstance(named_steps, dict) else None
        if estimator is None:
            raise RuntimeError("model pipeline is missing its estimator")
        estimator_types.append(type(estimator).__name__)
    if not estimator_types:
        raise RuntimeError("model artifact has no serving pipeline")
    return tuple(sorted(set(estimator_types)))


def validate_hgbr_runtime(model_type: str, model: Any) -> str:
    """승인 경로에는 HGBR manifest와 실제 HGBR estimator가 함께 있어야 한다."""
    if "hgbr" not in model_type.lower():
        raise RuntimeError("ML release is not declared as an HGBR model")
    estimator_types = runtime_estimator_types(model)
    if estimator_types != ("HistGradientBoostingRegressor",):
        raise RuntimeError("HGBR release contains an unexpected estimator")
    return estimator_types[0]


def validate_history_source(
    trino: TrinoClient,
    history_table: str,
    *,
    expected_synthetic: bool,
) -> dict[str, Any]:
    """History 계약의 값 범위·연속성·합성 출처가 모두 맞을 때만 serving한다."""

    summary_sql = f"""
SELECT
    count(*) AS row_count,
    count(DISTINCT property_id) AS property_count,
    min(business_date) AS min_date,
    max(business_date) AS max_date,
    count_if(
        property_id IS NULL
        OR business_date IS NULL
        OR room_type_code IS NULL
        OR physical_rooms <= 0
        OR available_room_nights < 0
        OR available_room_nights > physical_rooms
        OR rooms_sold < 0
        OR rooms_sold > available_room_nights
        OR daily_adr < 0
        OR cancellation_rate < 0
        OR cancellation_rate > 1
        OR is_synthetic IS NULL
    ) AS invalid_rows,
    count_if(is_synthetic) AS synthetic_rows,
    count_if(NOT is_synthetic) AS non_synthetic_rows
FROM {history_table}
""".strip()
    summary_result = trino.query(summary_sql)
    if len(summary_result.rows) != 1:
        raise RuntimeError("ML history source summary is unreadable")
    summary = summary_result.rows[0]
    row_count = int(summary.get("row_count") or 0)
    property_count = int(summary.get("property_count") or 0)
    invalid_rows = int(summary.get("invalid_rows") or 0)
    synthetic_rows = int(summary.get("synthetic_rows") or 0)
    non_synthetic_rows = int(summary.get("non_synthetic_rows") or 0)
    if row_count < 1 or property_count < 1:
        raise RuntimeError("ML history source is empty or unreadable")
    if invalid_rows:
        raise RuntimeError(f"ML history source has {invalid_rows} invalid rows")
    if expected_synthetic:
        source_mode_matches = synthetic_rows == row_count and non_synthetic_rows == 0
    else:
        source_mode_matches = non_synthetic_rows == row_count and synthetic_rows == 0
    if not source_mode_matches:
        raise RuntimeError("ML history source synthetic mode does not match the release")

    continuity_sql = f"""
SELECT
    count(*) AS series_count,
    min(row_count) AS min_series_rows,
    count_if(
        row_count < 372
        OR row_count <> date_diff('day', min_date, max_date) + 1
    ) AS invalid_series
FROM (
    SELECT
        property_id,
        room_type_code,
        count(*) AS row_count,
        min(business_date) AS min_date,
        max(business_date) AS max_date
    FROM {history_table}
    GROUP BY property_id, room_type_code
) AS history_series
""".strip()
    continuity_result = trino.query(continuity_sql)
    if len(continuity_result.rows) != 1:
        raise RuntimeError("ML history source continuity receipt is unreadable")
    continuity = continuity_result.rows[0]
    series_count = int(continuity.get("series_count") or 0)
    min_series_rows = int(continuity.get("min_series_rows") or 0)
    invalid_series = int(continuity.get("invalid_series") or 0)
    if series_count < 1 or min_series_rows < 372 or invalid_series:
        raise RuntimeError("ML history source has incomplete time series")

    return {
        "table": history_table,
        "row_count": row_count,
        "property_count": property_count,
        "series_count": series_count,
        "min_date": str(summary["min_date"]),
        "max_date": str(summary["max_date"]),
        "synthetic_only": expected_synthetic,
        "summary_query_id": summary_result.query_id,
        "continuity_query_id": continuity_result.query_id,
    }


def sha256(path: Path) -> str:
    """배포 artifact를 스트리밍해 release pin 검증용 SHA-256을 반환한다."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_model_artifact(artifact: Path) -> Any:
    """sklearn 직렬화 version이 runtime과 호환되는 artifact만 역직렬화한다.

    version 경고는 ``RuntimeError``로 승격하며 파일 손상·class 누락 등 다른
    joblib 오류도 호출자에게 전달해 대체 모델로 우회하지 않는다.
    """

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", InconsistentVersionWarning)
            return joblib.load(artifact)
    except InconsistentVersionWarning as error:
        raise RuntimeError(
            "model artifact scikit-learn version is incompatible with ML runtime"
        ) from error


def safe_table(value: str) -> str:
    """Trino history 이름을 정확한 catalog.schema.table 식별자로 검증한다."""

    parts = value.split(".")
    if len(parts) != 3 or any(not IDENTIFIER.fullmatch(part) for part in parts):
        raise RuntimeError("ML_HISTORY_TABLE must be catalog.schema.table")
    return ".".join(parts)


def sql_literal(value: str) -> str:
    """서버에서 검증한 문자열의 작은따옴표를 SQL 문자열 literal 형식으로 escape한다."""

    return "'" + value.replace("'", "''") + "'"


class PredictionRequest(BaseModel):
    """property, feature 기준일과 허용 범위의 예측 horizon을 검증하는 요청 계약이다."""

    property_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    as_of: date
    horizon_days: int = Field(
        default=DEFAULT_RUNTIME_MAX_HORIZON_DAYS,
        ge=1,
        le=ABSOLUTE_MAX_HORIZON_DAYS,
    )


class TimeSeriesRuntime:
    """release hash·승인·HGBR·history 계약을 검증한 뒤 추론 상태를 소유한다.

    필수 환경·artifact·Trino 증거가 없거나 서로 불일치하면 초기화가 실패하며
    준비되지 않은 runtime은 예측 endpoint에 노출되지 않는다.
    """

    def __init__(self) -> None:
        self.hmac_secret = runtime_hmac_secret()
        artifact = Path(os.environ["ML_MODEL_ARTIFACT"])
        manifest_path = Path(os.environ["ML_MODEL_MANIFEST"])
        approval_path = Path(os.environ["ML_MODEL_APPROVAL"])
        feature_contract_path = Path(os.environ["ML_FEATURE_CONTRACT"])
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.approval = json.loads(approval_path.read_text(encoding="utf-8"))
        feature_contract_bytes = feature_contract_path.read_bytes()
        feature_contract = json.loads(feature_contract_bytes.decode("utf-8"))
        synthetic_training_data = self.manifest.get("synthetic_training_data")
        if type(synthetic_training_data) is not bool:
            raise RuntimeError(
                "ML release synthetic_training_data contract is invalid"
            )
        approval_data_is_synthetic = self.approval.get("data_is_synthetic")
        if type(approval_data_is_synthetic) is not bool:
            raise RuntimeError(
                "ML approval data_is_synthetic contract is invalid"
            )
        if approval_data_is_synthetic != synthetic_training_data:
            raise RuntimeError(
                "ML approval and manifest synthetic modes do not match"
            )
        self.synthetic_training_data = synthetic_training_data
        self.feature_contract_sha256 = hashlib.sha256(
            feature_contract_bytes
        ).hexdigest()
        model_versions = {
            self.manifest.get("model_version"),
            self.approval.get("model_version"),
            feature_contract.get("model_version"),
        }
        if None in model_versions or len(model_versions) != 1:
            raise RuntimeError("ML release model versions do not match")
        actual_hash = sha256(artifact)
        if actual_hash != self.manifest.get("artifact_sha256"):
            raise RuntimeError("model artifact hash verification failed")
        if actual_hash != self.approval.get("artifact_sha256"):
            raise RuntimeError("model approval hash verification failed")
        if feature_contract.get("feature_columns_ordered") != FEATURE_COLUMNS:
            raise RuntimeError("runtime feature contract mismatch")
        try:
            model_max_horizon_days = int(self.manifest["max_horizon"])
            feature_max_horizon_days = int(feature_contract["max_horizon"])
            runtime_max_horizon_days = int(
                os.getenv(
                    "ML_RUNTIME_MAX_HORIZON_DAYS",
                    str(DEFAULT_RUNTIME_MAX_HORIZON_DAYS),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("ML horizon release contract is invalid") from error
        if (
            model_max_horizon_days != feature_max_horizon_days
            or not 1
            <= runtime_max_horizon_days
            <= model_max_horizon_days
            <= ABSOLUTE_MAX_HORIZON_DAYS
        ):
            raise RuntimeError("ML horizon release contract is invalid")
        self.model_max_horizon_days = model_max_horizon_days
        self.runtime_max_horizon_days = runtime_max_horizon_days
        decision = self.approval.get("final_decision", self.approval.get("decision"))
        allow_conditional = os.getenv("ML_ALLOW_CONDITIONAL", "false").lower() == "true"
        if decision != "APPROVED" and not (
            decision == "CONDITIONAL_PASS" and allow_conditional
        ):
            raise RuntimeError(f"model is not approved for serving: {decision}")
        self.model = load_model_artifact(artifact)
        if not hasattr(self.model, "predict_raw") or not hasattr(self.model, "predict"):
            raise RuntimeError("artifact is not a time-series demand model")
        self.model_type = str(self.manifest.get("model_type") or "").strip()
        if not self.model_type:
            raise RuntimeError("model manifest is missing model_type")
        self.estimator_type = validate_hgbr_runtime(self.model_type, self.model)
        self.model_hash = actual_hash
        self.history_table = safe_table(os.environ["ML_HISTORY_TABLE"])
        self.builder = TimeSeriesFeatureBuilder()
        self.trino = TrinoClient(
            base_url=os.environ["TRINO_URL"],
            user=os.getenv("TRINO_USER") or os.environ["TRINO_RUNTIME_USER"],
            password=os.getenv("TRINO_PASSWORD") or os.environ["TRINO_RUNTIME_PASSWORD"],
            ca_file=os.getenv("TRINO_CA_FILE") or os.environ["TRINO_TLS_CA_FILE"],
            timeout_seconds=float(os.getenv("TRINO_TIMEOUT_SECONDS", "30")),
        )
        self.history_source = validate_history_source(
            self.trino,
            self.history_table,
            expected_synthetic=self.synthetic_training_data,
        )

    def query_history(self, request: PredictionRequest) -> tuple[pd.DataFrame, str]:
        """property와 as-of 이하의 Trino 일별 실적을 조회해 DataFrame과 query ID를 반환한다.

        조회 행이 없으면 404로 실패하며 요청 property는 검증 후 대문자로
        정규화해 SQL literal로 사용한다.
        """

        sql = f"""
SELECT {', '.join(HISTORY_COLUMNS)}
FROM {self.history_table}
WHERE property_id = {sql_literal(request.property_id.upper())}
  AND business_date <= DATE {sql_literal(request.as_of.isoformat())}
ORDER BY room_type_code, business_date
""".strip()
        result = self.trino.query(sql)
        if not result.rows:
            raise HTTPException(status_code=404, detail="No historical daily facts found")
        frame = pd.DataFrame(result.rows)
        frame["business_date"] = pd.to_datetime(frame["business_date"])
        return frame, result.query_id

    def capabilities(self) -> dict[str, Any]:
        """release pin, 승인 상태, history 범위와 property별 허용 as-of를 반환한다.

        Trino 조회 또는 날짜 변환이 실패하면 capability 생성을 실패시켜 오래된
        정적 목록을 반환하지 않는다.
        """

        sql = f"""
SELECT property_id, min(business_date) AS min_date,
       max(business_date) AS max_date, count(*) AS history_rows
FROM {self.history_table}
GROUP BY property_id
ORDER BY property_id
""".strip()
        result = self.trino.query(sql)
        properties = []
        for row in result.rows:
            min_date = pd.Timestamp(row["min_date"]).date()
            max_date = pd.Timestamp(row["max_date"]).date()
            properties.append(
                {
                    "property_id": row["property_id"],
                    "min_as_of": (min_date + timedelta(days=371)).isoformat(),
                    "max_as_of": (
                        max_date
                        + timedelta(
                            days=(
                                self.model_max_horizon_days
                                - self.runtime_max_horizon_days
                            )
                        )
                    ).isoformat(),
                    "feature_max_as_of": max_date.isoformat(),
                    "history_rows": int(row["history_rows"]),
                }
            )
        return {
            "schema_version": ML_RUNTIME_CAPABILITY_VERSION,
            "prediction_contract_version": ML_PREDICTION_RESULT_VERSION,
            "model_version": self.manifest["model_version"],
            "model_hash": self.model_hash,
            "feature_contract_sha256": self.feature_contract_sha256,
            "model_type": self.model_type,
            "estimator_type": self.estimator_type,
            "approval": self.approval.get("final_decision"),
            "approval_status": self.approval.get("approval_status"),
            "min_horizon_days": 1,
            "max_horizon_days": self.runtime_max_horizon_days,
            "model_max_horizon_days": self.model_max_horizon_days,
            "properties": properties,
            "synthetic_training_data": self.synthetic_training_data,
            "history_source": self.history_source,
            "query_id": result.query_id,
        }

    def predict(self, request: PredictionRequest) -> dict[str, Any]:
        """history를 point-in-time feature로 바꿔 일별·room type별 예측과 provenance를 반환한다.

        runtime 또는 모델 horizon을 넘으면 422, history가 없으면 404로 실패하며
        응답에는 실제 model·feature hash와 Trino query ID를 포함한다.
        """

        if request.horizon_days > self.runtime_max_horizon_days:
            raise HTTPException(
                status_code=422,
                detail="Requested horizon exceeds the active runtime capability",
            )
        facts, query_id = self.query_history(request)
        feature_cutoff = pd.Timestamp(facts["business_date"].max()).date()
        forecast_start = request.as_of + timedelta(days=1)
        forecast_end = request.as_of + timedelta(days=request.horizon_days)
        if (forecast_end - feature_cutoff).days > self.model_max_horizon_days:
            raise HTTPException(
                status_code=422,
                detail="Requested dates exceed the model horizon from latest facts",
            )
        features = self.builder.build_inference(
            facts,
            cutoff_date=feature_cutoff.isoformat(),
            forecast_start=forecast_start.isoformat(),
            forecast_end=forecast_end.isoformat(),
        )
        raw = np.asarray(self.model.predict_raw(features), dtype=float)
        final = np.asarray(self.model.predict(features), dtype=float)
        capacity = features["physical_rooms"].astype(float).to_numpy()
        details = []
        for index, row in features.reset_index(drop=True).iterrows():
            available = round(float(capacity[index]), 2)
            predicted_rooms = round(float(final[index]), 2)
            details.append(
                {
                    "target_date": pd.Timestamp(row["target_date"]).date().isoformat(),
                    "room_type_code": str(row["room_type_code"]),
                    "available_rooms": available,
                    "predicted_rooms_raw": round(float(raw[index]), 4),
                    "predicted_rooms": predicted_rooms,
                    "occupancy_rate": round(predicted_rooms / available, 6),
                }
            )
        daily = []
        for target_date in pd.date_range(forecast_start, forecast_end):
            rows = [row for row in details if row["target_date"] == target_date.date().isoformat()]
            total_available = sum(row["available_rooms"] for row in rows)
            total_predicted = sum(row["predicted_rooms"] for row in rows)
            daily.append(
                {
                    "target_date": target_date.date().isoformat(),
                    "total_available_rooms": round(total_available, 2),
                    "predicted_occupied_rooms": round(total_predicted, 2),
                    "predicted_available_rooms": round(total_available - total_predicted, 2),
                    "predicted_occupancy_rate": round(total_predicted / total_available, 6),
                }
            )
        return {
            "schema_version": ML_PREDICTION_RESULT_VERSION,
            "status": "SUCCEEDED",
            "execution_id": str(uuid.uuid4()),
            "property_id": request.property_id.upper(),
            "as_of": request.as_of.isoformat(),
            "feature_as_of": feature_cutoff.isoformat(),
            "horizon_days": request.horizon_days,
            "model_version": self.manifest["model_version"],
            "model_hash": self.model_hash,
            "feature_contract_sha256": self.feature_contract_sha256,
            "daily_forecasts": daily,
            "room_type_forecasts": details,
            "provenance": {
                "source": "TRINO_HISTORICAL_DAILY_FACTS",
                "history_table": self.history_table,
                "trino_query_id": query_id,
                "feature_as_of": feature_cutoff.isoformat(),
                "request_as_of": request.as_of.isoformat(),
                "rag_called": False,
            },
        }


app = FastAPI(title="Answervice Historical Room Demand Runtime", version="4.0.0")
state: TimeSeriesRuntime | None = None
_AUTHENTICATED_PATHS = frozenset({"/capabilities", "/predictions/room-demand"})
_request_nonce_guard = MLRuntimeNonceGuard()


def _declared_request_body_size(request: Request) -> int:
    """본문을 읽기 전에 chunked·과대 인증 요청을 거부한다."""

    if request.headers.get("transfer-encoding"):
        raise MLRuntimeTrustError("chunked ML runtime requests are not allowed")
    content_length = request.headers.get("content-length")
    if content_length is None:
        if request.method.upper() in {"GET", "HEAD"}:
            return 0
        raise MLRuntimeTrustError("ML runtime request Content-Length is required")
    if not content_length.isdigit() or len(content_length) > 10:
        raise MLRuntimeTrustError("ML runtime request Content-Length is invalid")
    size = int(content_length)
    if size > ML_RUNTIME_AUTH_MAX_BODY_BYTES:
        raise MLRuntimeTrustError("ML runtime authenticated body is too large")
    return size


def _signed_runtime_error(
    secret: bytes,
    path: str,
    status_code: int,
    nonce: str,
    detail: str,
) -> Response:
    """인증된 Backend에만 bounded generic runtime 오류를 서명해 반환한다."""

    body = json.dumps(
        {"detail": detail},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return Response(
        content=body,
        status_code=status_code,
        headers=response_auth_headers(secret, path, status_code, nonce, body),
        media_type="application/json",
    )


@app.middleware("http")
async def authenticate_runtime_exchange(request: Request, call_next) -> Response:
    """Backend 전용 endpoint의 요청을 검증하고 모든 응답을 같은 nonce에 서명한다."""

    if request.url.path not in _AUTHENTICATED_PATHS:
        return await call_next(request)
    runtime = state
    try:
        declared_size = _declared_request_body_size(request)
    except MLRuntimeTrustError:
        return JSONResponse(status_code=413, content={"detail": "Request rejected"})
    try:
        secret = runtime.hmac_secret if runtime is not None else runtime_hmac_secret()
    except MLRuntimeTrustError:
        return JSONResponse(status_code=503, content={"detail": "Runtime unavailable"})
    body = await request.body()
    if len(body) != declared_size or len(body) > ML_RUNTIME_AUTH_MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": "Request rejected"})
    try:
        nonce = verify_request_auth(
            secret,
            request.headers,
            request.method,
            request.url.path,
            body,
        )
        _request_nonce_guard.consume(nonce)
    except MLRuntimeTrustError:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    if runtime is None:
        return _signed_runtime_error(
            secret,
            request.url.path,
            503,
            nonce,
            "ML runtime is not ready",
        )
    try:
        response = await call_next(request)
        response_chunks: list[bytes] = []
        response_size = 0
        async for chunk in response.body_iterator:
            encoded_chunk = chunk.encode("utf-8") if isinstance(chunk, str) else chunk
            response_size += len(encoded_chunk)
            if response_size > ML_RUNTIME_AUTH_MAX_BODY_BYTES:
                close_iterator = getattr(response.body_iterator, "aclose", None)
                if callable(close_iterator):
                    await close_iterator()
                return _signed_runtime_error(
                    secret,
                    request.url.path,
                    502,
                    nonce,
                    "Authenticated ML runtime response is too large",
                )
            response_chunks.append(encoded_chunk)
    except Exception:
        return _signed_runtime_error(
            secret,
            request.url.path,
            500,
            nonce,
            "ML runtime request failed",
        )
    response_body = b"".join(response_chunks)
    signed_headers = dict(response.headers)
    signed_headers.pop("content-length", None)
    signed_headers.update(
        response_auth_headers(
            secret,
            request.url.path,
            response.status_code,
            nonce,
            response_body,
        )
    )
    return Response(
        content=response_body,
        status_code=response.status_code,
        headers=signed_headers,
        media_type=response.media_type,
        background=response.background,
    )


@app.on_event("startup")
def startup() -> None:
    """프로세스 시작 시 모든 release·history 계약을 검증하고 실패하면 미준비 상태로 둔다."""

    global state
    try:
        state = TimeSeriesRuntime()
    except Exception:
        state = None
        logger.exception("ML runtime startup failed")


def ready_state() -> TimeSeriesRuntime:
    """초기화된 runtime을 반환하고 준비 실패 상태는 HTTP 503으로 차단한다."""

    if state is None:
        raise HTTPException(status_code=503, detail="runtime not ready")
    return state


@app.get("/health")
def health() -> dict[str, str]:
    """프로세스 생존 여부만 반환하며 모델 준비 완료를 주장하지 않는다."""

    return {"status": "ok"}


@app.get("/readiness")
def readiness() -> dict[str, Any]:
    """준비된 모델의 hash·estimator·승인 증거를 반환하고 아니면 503으로 실패한다."""

    runtime = ready_state()
    return {
        "status": "ready",
        "model_hash": runtime.model_hash,
        "feature_contract_sha256": runtime.feature_contract_sha256,
        "model_type": runtime.model_type,
        "estimator_type": runtime.estimator_type,
        "approval": runtime.approval.get("final_decision"),
    }


@app.get("/capabilities")
def capabilities() -> dict[str, Any]:
    """인증된 호출에 현재 runtime이 동적으로 조회한 ML capability 계약을 반환한다."""

    return ready_state().capabilities()


@app.post("/predictions/room-demand")
def predict(request: PredictionRequest) -> dict[str, Any]:
    """검증된 요청을 준비된 runtime에 위임해 서명 대상 예측 응답을 반환한다."""

    return ready_state().predict(request)
