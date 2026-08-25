from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from src.ml.live_room_demand import ForecastRequest
from src.ml.live_room_demand_artifact import ApprovedRoomDemandRuntime


def _find(value: Any, names: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in names and item not in (None, ""):
                return item
        for item in value.values():
            found = _find(item, names)
            if found not in (None, ""):
                return found
    if isinstance(value, list):
        for item in value:
            found = _find(item, names)
            if found not in (None, ""):
                return found
    return None


def create_app() -> FastAPI:
    if os.environ.get("ML_FEATURE_SOURCE", "").lower() != "trino":
        raise RuntimeError("ML_FEATURE_SOURCE=trino is required")
    service = ApprovedRoomDemandRuntime(Path(os.environ["ML_MODEL_ARTIFACT"]))
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await service.aclose()

    app = FastAPI(
        title="Answervice ML Prediction Runtime",
        version="3.4.0",
        lifespan=lifespan,
    )

    async def readiness_payload() -> dict[str, Any]:
        """승인 artifact와 live Trino statement가 모두 준비됐을 때만 READY를 반환한다."""

        try:
            details = await service.health()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"ML runtime unavailable: {exc}") from exc
        return {"status": "READY", "active": True, "approval_status": "APPROVED",
                "active_models": [details["model_name"]], "executable_models": [details["model_name"]],
                "metric": details["metric"], "model_name": details["model_name"],
                "model_version": details["model_version"],
                "artifact_hash": details["artifact_hash"],
                "property_id": details["property_id"], "feature_as_of": details["feature_as_of"],
                "max_horizon": details["max_horizon"],
                "feature_source": "LIVE_TRINO_PMS", "training_source": "LIVE_TRINO_PMS"}

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return await readiness_payload()

    @app.get("/readiness")
    async def readiness() -> dict[str, Any]:
        return await readiness_payload()

    @app.get("/v1/capabilities")
    async def capabilities() -> dict[str, Any]:
        return await readiness_payload()

    @app.post("/v1/predictions")
    async def predict(payload: dict[str, Any]) -> dict[str, Any]:
        """호텔 scope·기준일·예측기간을 검증하고 승인 모델의 실제 예측을 반환한다."""

        property_id = _find(payload, {"property_id", "hotel_code", "hotel_scope"})
        feature_as_of = _find(payload, {"feature_as_of", "as_of"})
        metric = _find(payload, {"metric"})
        horizon = _find(payload, {"horizon", "horizon_days"})
        request_id = _find(payload, {"request_id"})
        trace_id = _find(payload, {"trace_id"})
        if not property_id or not feature_as_of or not metric or horizon is None:
            raise HTTPException(status_code=422, detail="metric, hotel_scope, horizon, and as_of are required")
        try:
            result = await service.predict(
                ForecastRequest.create(str(property_id), str(feature_as_of)),
                str(metric),
                int(horizon),
            )
            return {
                **result,
                "execution_id": str(uuid4()),
                "request_id": str(request_id) if request_id else None,
                "trace_id": str(trace_id) if trace_id else None,
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"live prediction failed: {exc}") from exc

    return app
