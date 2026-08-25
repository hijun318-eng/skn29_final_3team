from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

from src.ml.live_room_demand import FEATURES, ForecastRequest, LiveRoomDemandService


METRIC = "OCCUPANCY_RATE"
SCHEMA_VERSION = "room-demand-artifact-v1"


class RoomDemandArtifactTrainer:
    def __init__(self, data_service: LiveRoomDemandService | None = None) -> None:
        self.data = data_service or LiveRoomDemandService()

    async def train(self, request: ForecastRequest, artifact_path: Path) -> dict[str, Any]:
        """live PMS feature로 시간 분할 검증 후 승인 artifact를 원자적으로 기록한다."""

        inventory, calendar, reservations = await self.data._load(request)
        frame = self.data._build_features(request, inventory, calendar, reservations)
        training = frame[frame["is_training"]].copy()
        split_date = request.feature_as_of - timedelta(days=28)
        fit_rows = training[training["target_date"] < split_date]
        validation = training[training["target_date"] >= split_date]
        if len(fit_rows) < 100 or validation.empty:
            raise ValueError("insufficient live PMS rows for time-based model validation")

        capacity = validation["available_room_nights"].to_numpy(float)
        baseline = np.clip(validation["seasonal_naive_rooms_sold"].to_numpy(float), 0, capacity)
        model = self.data._model()
        model.fit(fit_rows[FEATURES], fit_rows["rooms_sold"])
        candidate = np.clip(model.predict(validation[FEATURES]), 0, capacity)
        baseline_metrics = self._metrics(validation, baseline)
        candidate_metrics = self._metrics(validation, candidate)
        selected = (
            "HIST_GRADIENT_BOOSTING"
            if candidate_metrics["occupancy_mae"] < baseline_metrics["occupancy_mae"]
            and candidate_metrics["occupancy_rmse"] <= baseline_metrics["occupancy_rmse"]
            else "SEASONAL_NAIVE"
        )
        if selected == "HIST_GRADIENT_BOOSTING":
            model.fit(training[FEATURES], training["rooms_sold"])
            approved_model = model
            model_name = "live-pms-hist-gradient-boosting"
        else:
            approved_model = None
            model_name = "live-pms-seasonal-naive"

        version = f"pms-{request.property_id.lower()}-{request.feature_as_of.isoformat()}"
        artifact = {
            "schema_version": SCHEMA_VERSION,
            "approval_status": "APPROVED",
            "metric": METRIC,
            "property_id": request.property_id,
            "feature_as_of": request.feature_as_of.isoformat(),
            "model_name": model_name,
            "model_version": version,
            "selected_strategy": selected,
            "feature_source": "LIVE_TRINO_PMS",
            "training_source": "LIVE_TRINO_PMS",
            "training_row_count": int(len(training)),
            "validation_row_count": int(len(validation)),
            "training_start": str(training["target_date"].min()),
            "training_end": str(training["target_date"].max()),
            "validation_start": str(validation["target_date"].min()),
            "validation_end": str(validation["target_date"].max()),
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
            "features": FEATURES,
            "model": approved_model,
        }
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
        joblib.dump(artifact, temporary)
        temporary.replace(artifact_path)
        summary = {key: value for key, value in artifact.items() if key != "model"}
        summary["artifact_hash"] = f"sha256:{hashlib.sha256(artifact_path.read_bytes()).hexdigest()}"
        artifact_path.with_suffix(".approval.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary

    @staticmethod
    def _metrics(frame: Any, predicted_rooms: np.ndarray) -> dict[str, float]:
        actual_rooms = frame["rooms_sold"].to_numpy(float)
        capacity = frame["available_room_nights"].to_numpy(float)
        actual_occupancy = np.divide(actual_rooms, capacity, out=np.zeros_like(actual_rooms), where=capacity > 0)
        predicted_occupancy = np.divide(predicted_rooms, capacity, out=np.zeros_like(predicted_rooms), where=capacity > 0)
        return {
            "rooms_mae": round(float(mean_absolute_error(actual_rooms, predicted_rooms)), 6),
            "rooms_rmse": round(float(root_mean_squared_error(actual_rooms, predicted_rooms)), 6),
            "occupancy_mae": round(float(mean_absolute_error(actual_occupancy, predicted_occupancy)), 8),
            "occupancy_rmse": round(float(root_mean_squared_error(actual_occupancy, predicted_occupancy)), 8),
        }


class ApprovedRoomDemandRuntime:
    def __init__(self, artifact_path: Path, data_service: LiveRoomDemandService | None = None) -> None:
        if not artifact_path.is_file():
            raise RuntimeError(f"approved model artifact not found: {artifact_path}")
        approval_path = artifact_path.with_suffix(".approval.json")
        if not approval_path.is_file():
            raise RuntimeError(f"approved model manifest not found: {approval_path}")
        self.artifact: dict[str, Any] = joblib.load(artifact_path)
        manifest = json.loads(approval_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        expected_digest = str(manifest.get("artifact_hash") or "").removeprefix("sha256:")
        if not expected_digest or expected_digest != digest:
            raise RuntimeError("model artifact hash does not match approved manifest")
        if self.artifact.get("schema_version") != SCHEMA_VERSION:
            raise RuntimeError("unsupported model artifact schema")
        if self.artifact.get("approval_status") != "APPROVED":
            raise RuntimeError("model artifact is not approved")
        for key in ("model_name", "model_version", "property_id", "metric", "feature_as_of"):
            if manifest.get(key) != self.artifact.get(key):
                raise RuntimeError(f"model artifact manifest mismatch: {key}")
        self.artifact_hash = f"sha256:{digest}"
        self.data = data_service or LiveRoomDemandService()

    async def health(self) -> dict[str, Any]:
        """artifact 계약과 실제 Trino statement 준비 상태를 반환한다."""

        await self.data.health()
        return {
            "metric": self.artifact["metric"],
            "model_name": self.artifact["model_name"],
            "model_version": self.artifact["model_version"],
            "artifact_hash": self.artifact_hash,
            "property_id": self.artifact["property_id"],
            "feature_as_of": self.artifact["feature_as_of"],
            "max_horizon": 7,
        }

    async def predict(self, request: ForecastRequest, metric: str, horizon: int) -> dict[str, Any]:
        """승인 scope와 horizon 안에서 live feature 기반 점유율 예측을 반환한다."""

        if metric.upper() != METRIC:
            raise ValueError(f"metric must be {METRIC}")
        if request.property_id != self.artifact["property_id"]:
            raise ValueError("hotel_scope is outside the approved model artifact")
        if request.feature_as_of.isoformat() != self.artifact["feature_as_of"]:
            raise ValueError("as_of must match the approved model artifact")
        if horizon < 1 or horizon > 7:
            raise ValueError("horizon must be between 1 and 7 days")

        inventory, calendar, reservations = await self.data._load(request)
        trino_query_ids = [
            str(frame.attrs["trino_query_id"])
            for frame in (inventory, calendar, reservations)
            if frame.attrs.get("trino_query_id")
        ]
        frame = self.data._build_features(request, inventory, calendar, reservations)
        forecast = frame[(~frame["is_training"]) & (frame["horizon_days"] <= horizon)].copy()
        if forecast.empty:
            raise ValueError("forecast rows are unavailable for the requested scope")
        if self.artifact["selected_strategy"] == "HIST_GRADIENT_BOOSTING":
            predicted = self.artifact["model"].predict(forecast[FEATURES])
        else:
            predicted = forecast["seasonal_naive_rooms_sold"].to_numpy(float)
        capacity = forecast["available_room_nights"].to_numpy(float)
        forecast["predicted_rooms_sold"] = np.clip(predicted, 0, capacity).round(2)
        forecast["predicted_occupancy_rate"] = np.divide(
            forecast["predicted_rooms_sold"].to_numpy(float),
            capacity,
            out=np.zeros_like(capacity),
            where=capacity > 0,
        ).round(6)
        result = forecast[
            ["property_id", "target_date", "room_type_code", "horizon_days",
             "available_room_nights", "booking_on_hand", "predicted_rooms_sold",
             "predicted_occupancy_rate"]
        ].copy()
        result["target_date"] = result["target_date"].astype(str)
        return {
            "status": "SUCCESS",
            "forecast_status": "SUCCESS",
            "evidence_type": "PREDICTED_EVIDENCE",
            "metric": METRIC,
            "model_name": self.artifact["model_name"],
            "model_version": self.artifact["model_version"],
            "artifact_hash": self.artifact_hash,
            "selected_strategy": self.artifact["selected_strategy"],
            "feature_source": self.artifact["feature_source"],
            "training_source": self.artifact["training_source"],
            "property_id": request.property_id,
            "feature_as_of": request.feature_as_of.isoformat(),
            "trino_query_ids": trino_query_ids,
            "baseline_metrics": self.artifact["baseline_metrics"],
            "candidate_metrics": self.artifact["candidate_metrics"],
            "predictions": result.to_dict(orient="records"),
        }

    async def aclose(self) -> None:
        """예측 runtime이 소유한 외부 연결을 닫는다."""

        await self.data.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and approve the live PMS occupancy forecast artifact")
    parser.add_argument("--property-id", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = asyncio.run(
        RoomDemandArtifactTrainer().train(
            ForecastRequest.create(args.property_id, args.as_of),
            args.output,
        )
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
