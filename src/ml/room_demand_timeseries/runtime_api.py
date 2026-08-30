from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..room_demand_v3.trino_client import TrinoClient
from .contracts import FEATURE_COLUMNS
from .features import TimeSeriesFeatureBuilder


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
ML_RUNTIME_CAPABILITY_VERSION = "MLRuntimeCapability.v1"
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_table(value: str) -> str:
    parts = value.split(".")
    if len(parts) != 3 or any(not IDENTIFIER.fullmatch(part) for part in parts):
        raise RuntimeError("ML_HISTORY_TABLE must be catalog.schema.table")
    return ".".join(parts)


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class PredictionRequest(BaseModel):
    property_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    as_of: date
    horizon_days: int = Field(
        default=DEFAULT_RUNTIME_MAX_HORIZON_DAYS,
        ge=1,
        le=ABSOLUTE_MAX_HORIZON_DAYS,
    )


class TimeSeriesRuntime:
    def __init__(self) -> None:
        artifact = Path(os.environ["ML_MODEL_ARTIFACT"])
        manifest_path = Path(os.environ["ML_MODEL_MANIFEST"])
        approval_path = Path(os.environ["ML_MODEL_APPROVAL"])
        feature_contract_path = Path(os.environ["ML_FEATURE_CONTRACT"])
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.approval = json.loads(approval_path.read_text(encoding="utf-8"))
        feature_contract = json.loads(feature_contract_path.read_text(encoding="utf-8"))
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
        self.model = joblib.load(artifact)
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
            expected_synthetic=bool(self.manifest["synthetic_training_data"]),
        )

    def query_history(self, request: PredictionRequest) -> tuple[pd.DataFrame, str]:
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
            "model_type": self.model_type,
            "estimator_type": self.estimator_type,
            "approval": self.approval.get("final_decision"),
            "min_horizon_days": 1,
            "max_horizon_days": self.runtime_max_horizon_days,
            "model_max_horizon_days": self.model_max_horizon_days,
            "properties": properties,
            "synthetic_training_data": bool(self.manifest["synthetic_training_data"]),
            "history_source": self.history_source,
            "query_id": result.query_id,
        }

    def predict(self, request: PredictionRequest) -> dict[str, Any]:
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
            available = float(capacity[index])
            details.append(
                {
                    "target_date": pd.Timestamp(row["target_date"]).date().isoformat(),
                    "room_type_code": str(row["room_type_code"]),
                    "available_rooms": round(available, 2),
                    "predicted_rooms_raw": round(float(raw[index]), 4),
                    "predicted_rooms": round(float(final[index]), 2),
                    "occupancy_rate": round(float(final[index] / available), 6),
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
startup_error: str | None = None


@app.on_event("startup")
def startup() -> None:
    global state, startup_error
    try:
        state = TimeSeriesRuntime()
        startup_error = None
    except Exception as exc:
        state = None
        startup_error = str(exc)


def ready_state() -> TimeSeriesRuntime:
    if state is None:
        raise HTTPException(status_code=503, detail=startup_error or "runtime not loaded")
    return state


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readiness")
def readiness() -> dict[str, Any]:
    runtime = ready_state()
    return {
        "status": "ready",
        "model_hash": runtime.model_hash,
        "model_type": runtime.model_type,
        "estimator_type": runtime.estimator_type,
        "approval": runtime.approval.get("final_decision"),
    }


@app.get("/capabilities")
def capabilities() -> dict[str, Any]:
    return ready_state().capabilities()


@app.post("/predictions/room-demand")
def predict(request: PredictionRequest) -> dict[str, Any]:
    return ready_state().predict(request)
