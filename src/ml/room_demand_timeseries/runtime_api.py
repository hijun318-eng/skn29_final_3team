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
from .contracts import FEATURE_COLUMNS, MAX_HORIZON
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
REQUEST_MAX_HORIZON = 7


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
    horizon: int = Field(default=7, ge=1, le=REQUEST_MAX_HORIZON)


class TimeSeriesRuntime:
    def __init__(self) -> None:
        artifact = Path(os.environ["ML_MODEL_ARTIFACT"])
        manifest_path = Path(os.environ["ML_MODEL_MANIFEST"])
        approval_path = Path(os.environ["ML_MODEL_APPROVAL"])
        feature_contract_path = Path(os.environ["ML_FEATURE_CONTRACT"])
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.approval = json.loads(approval_path.read_text(encoding="utf-8"))
        feature_contract = json.loads(feature_contract_path.read_text(encoding="utf-8"))
        actual_hash = sha256(artifact)
        if actual_hash != self.manifest.get("artifact_sha256"):
            raise RuntimeError("model artifact hash verification failed")
        if feature_contract.get("feature_columns_ordered") != FEATURE_COLUMNS:
            raise RuntimeError("runtime feature contract mismatch")
        decision = self.approval.get("final_decision", self.approval.get("decision"))
        allow_conditional = os.getenv("ML_ALLOW_CONDITIONAL", "false").lower() == "true"
        if decision != "APPROVED" and not (
            decision == "CONDITIONAL_PASS" and allow_conditional
        ):
            raise RuntimeError(f"model is not approved for serving: {decision}")
        self.model = joblib.load(artifact)
        if not hasattr(self.model, "predict_raw") or not hasattr(self.model, "predict"):
            raise RuntimeError("artifact is not a time-series demand model")
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
                        max_date + timedelta(days=MAX_HORIZON - REQUEST_MAX_HORIZON)
                    ).isoformat(),
                    "feature_max_as_of": max_date.isoformat(),
                    "history_rows": int(row["history_rows"]),
                }
            )
        return {
            "model_version": self.manifest["model_version"],
            "model_hash": self.model_hash,
            "approval": self.approval.get("final_decision"),
            "max_horizon": REQUEST_MAX_HORIZON,
            "model_max_horizon": MAX_HORIZON,
            "properties": properties,
            "synthetic_training_data": bool(self.manifest["synthetic_training_data"]),
            "query_id": result.query_id,
        }

    def predict(self, request: PredictionRequest) -> dict[str, Any]:
        facts, query_id = self.query_history(request)
        feature_cutoff = pd.Timestamp(facts["business_date"].max()).date()
        forecast_start = request.as_of + timedelta(days=1)
        forecast_end = request.as_of + timedelta(days=request.horizon)
        if (forecast_end - feature_cutoff).days > MAX_HORIZON:
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
            "status": "SUCCEEDED",
            "execution_id": str(uuid.uuid4()),
            "property_id": request.property_id.upper(),
            "as_of": request.as_of.isoformat(),
            "feature_as_of": feature_cutoff.isoformat(),
            "horizon": request.horizon,
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
    return {"status": "ready", "model_hash": runtime.model_hash, "approval": runtime.approval.get("final_decision")}


@app.get("/capabilities")
def capabilities() -> dict[str, Any]:
    return ready_state().capabilities()


@app.post("/predictions/room-demand")
def predict(request: PredictionRequest) -> dict[str, Any]:
    return ready_state().predict(request)
