from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.ml_actual_comparison import MLActualComparisonService


EXECUTION_ID = uuid4()


def _prediction() -> dict[str, object]:
    return {
        "schema_version": "MLRoomDemandPrediction.v1",
        "status": "SUCCEEDED",
        "execution_id": str(EXECUTION_ID),
        "property_id": "GRAND",
        "as_of": "2026-08-24",
        "feature_as_of": "2026-08-24",
        "horizon_days": 1,
        "model_version": "room-demand-operational-hgbr-v4.0.0",
        "model_hash": "a" * 64,
        "feature_contract_sha256": "b" * 64,
        "daily_forecasts": [
            {
                "target_date": "2026-08-25",
                "total_available_rooms": 100.0,
                "predicted_occupied_rooms": 70.0,
                "predicted_available_rooms": 30.0,
                "predicted_occupancy_rate": 0.7,
            }
        ],
        "room_type_forecasts": [
            {
                "target_date": "2026-08-25",
                "room_type_code": "G_DELUXE",
                "available_rooms": 100.0,
                "predicted_rooms_raw": 70.0,
                "predicted_rooms": 70.0,
                "occupancy_rate": 0.7,
            }
        ],
        "provenance": {
            "source": "TRINO_HISTORICAL_DAILY_FACTS",
            "history_table": "pms.ml_evaluation.approved_history",
            "trino_query_id": "prediction-query-1",
            "feature_as_of": "2026-08-24",
            "request_as_of": "2026-08-24",
            "rag_called": False,
        },
    }


class _Mappings:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def one_or_none(self) -> dict[str, object]:
        return {"result_payload": self._payload}


class _Result:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def mappings(self) -> _Mappings:
        return _Mappings(self._payload)


class _Session:
    async def execute(self, *_args: object, **_kwargs: object) -> _Result:
        return _Result(_prediction())


class _Client:
    def __init__(self, complete: bool = True) -> None:
        self.complete = complete

    async def actuals(self, _payload: dict[str, object]) -> dict[str, object]:
        response: dict[str, object] = {
            "schema_version": "MLRoomDemandActuals.v1",
            "property_id": "GRAND",
            "target_start": "2026-08-25",
            "target_end": "2026-08-25",
            "complete": self.complete,
            "missing_dates": [] if self.complete else ["2026-08-25"],
            "daily_actuals": [],
            "room_type_actuals": [],
            "history_table": "pms.ml_evaluation.approved_history",
            "trino_query_id": "actual-query-1",
        }
        if self.complete:
            response["daily_actuals"] = [
                {
                    "target_date": "2026-08-25",
                    "sellable_rooms": 100.0,
                    "actual_rooms_sold": 74.0,
                }
            ]
            response["room_type_actuals"] = [
                {
                    "target_date": "2026-08-25",
                    "room_type_code": "G_DELUXE",
                    "sellable_rooms": 100.0,
                    "actual_rooms_sold": 74.0,
                }
            ]
        return deepcopy(response)


def test_actual_comparison_calculates_mae_and_wape() -> None:
    result = asyncio.run(
        MLActualComparisonService(_Client()).compare(  # type: ignore[arg-type]
            _Session(),  # type: ignore[arg-type]
            EXECUTION_ID,
        )
    )

    assert result["status"] == "COMPLETE"
    assert result["metrics"] == {
        "rows": 1,
        "actual_total": 74.0,
        "predicted_total": 70.0,
        "mae_rooms": 4.0,
        "wape": 4 / 74,
    }


def test_actual_comparison_stays_pending_until_actual_arrives() -> None:
    result = asyncio.run(
        MLActualComparisonService(_Client(complete=False)).compare(  # type: ignore[arg-type]
            _Session(),  # type: ignore[arg-type]
            EXECUTION_ID,
        )
    )

    assert result["status"] == "PENDING"
    assert result["metrics"] is None
    assert result["missing_dates"] == ["2026-08-25"]
