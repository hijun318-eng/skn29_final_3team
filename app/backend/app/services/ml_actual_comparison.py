"""저장된 객실 수요 예측을 이후 도착한 실제값과 자동 비교한다."""

from __future__ import annotations

import math
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.ml_prediction_client import MLPredictionClient
from app.contract_core import ContractModel
from app.services.ml_prediction_service import MLRoomDemandPrediction


class MLActualDaily(ContractModel):
    """하루 판매 가능 객실과 실제 판매 객실을 표현한다."""

    target_date: date
    sellable_rooms: float = Field(gt=0)
    actual_rooms_sold: float = Field(ge=0)


class MLActualRoomType(MLActualDaily):
    """객실 유형별 하루 실제 판매 실적을 표현한다."""

    room_type_code: str = Field(min_length=1, max_length=64)


class MLActualsResponse(ContractModel):
    """예측 기간의 일별·객실 유형별 실제값 조회 결과다."""

    schema_version: Literal["MLRoomDemandActuals.v1"]
    property_id: str = Field(min_length=1, max_length=64)
    target_start: date
    target_end: date
    complete: bool
    missing_dates: tuple[date, ...]
    daily_actuals: tuple[MLActualDaily, ...]
    room_type_actuals: tuple[MLActualRoomType, ...]
    history_table: str = Field(min_length=5, max_length=256)
    trino_query_id: str = Field(min_length=1, max_length=256)


class MLDailyComparison(ContractModel):
    """하루 예측값과 실제값 및 절대 오차를 표현한다."""

    target_date: date
    predicted_rooms: float = Field(ge=0)
    actual_rooms: float = Field(ge=0)
    absolute_error_rooms: float = Field(ge=0)


class MLRoomTypeComparison(MLDailyComparison):
    """객실 유형별 예측값과 실제값 비교 결과다."""

    room_type_code: str = Field(min_length=1, max_length=64)


class MLComparisonMetrics(ContractModel):
    """완료된 예측 비교의 합계와 대표 오차 지표다."""

    rows: int = Field(ge=1)
    actual_total: float = Field(ge=0)
    predicted_total: float = Field(ge=0)
    mae_rooms: float = Field(ge=0)
    wape: float = Field(ge=0)


class MLActualComparison(ContractModel):
    """실적 적재 여부에 따른 예측 자동 비교 상태와 결과다."""

    schema_version: Literal["MLRoomDemandActualComparison.v1"]
    execution_id: UUID
    property_id: str = Field(min_length=1, max_length=64)
    status: Literal["COMPLETE", "PENDING"]
    missing_dates: tuple[date, ...]
    daily_comparisons: tuple[MLDailyComparison, ...]
    room_type_comparisons: tuple[MLRoomTypeComparison, ...]
    metrics: MLComparisonMetrics | None
    actuals_query_id: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_status(self) -> "MLActualComparison":
        """완료·대기 상태와 누락 날짜 및 지표 조합을 검증한다."""

        if self.status == "COMPLETE" and (self.missing_dates or self.metrics is None):
            raise ValueError("complete ML actual comparison is incomplete")
        if self.status == "PENDING" and not self.missing_dates:
            raise ValueError("pending ML actual comparison has no missing date")
        return self


def _metrics(rows: list[dict[str, object]]) -> dict[str, float | int] | None:
    if not rows:
        return None
    actual = [float(row["actual_rooms"]) for row in rows]
    predicted = [float(row["predicted_rooms"]) for row in rows]
    errors = [abs(left - right) for left, right in zip(actual, predicted)]
    actual_total = sum(actual)
    return {
        "rows": len(rows),
        "actual_total": actual_total,
        "predicted_total": sum(predicted),
        "mae_rooms": sum(errors) / len(errors),
        "wape": sum(errors) / actual_total if actual_total else 0.0,
    }


class MLActualComparisonService:
    """감사된 예측만 읽어 실제값 조회와 오차 계산을 수행한다."""

    def __init__(self, client: MLPredictionClient | None = None) -> None:
        self._client = client

    def _runtime_client(self) -> MLPredictionClient:
        if self._client is None:
            self._client = MLPredictionClient()
        return self._client

    async def compare(
        self,
        session: AsyncSession,
        execution_id: UUID,
    ) -> dict[str, object]:
        """저장된 예측을 같은 원천의 이후 실적과 비교해 오차를 반환한다."""

        result = await session.execute(
            text(
                """
                SELECT result_payload
                FROM governance.ml_prediction_audit_events
                WHERE execution_id = :execution_id AND status = 'SUCCEEDED'
                """
            ),
            {"execution_id": str(execution_id)},
        )
        stored = result.mappings().one_or_none()
        if stored is None:
            raise LookupError("ML prediction execution was not found")
        prediction = MLRoomDemandPrediction.model_validate(stored["result_payload"])
        start = prediction.daily_forecasts[0].target_date
        end = prediction.daily_forecasts[-1].target_date
        actuals = MLActualsResponse.model_validate(
            await self._runtime_client().actuals(
                {
                    "property_id": prediction.property_id,
                    "target_start": start.isoformat(),
                    "target_end": end.isoformat(),
                }
            )
        )
        if (
            actuals.property_id != prediction.property_id
            or actuals.history_table != prediction.provenance.history_table
        ):
            raise RuntimeError("ML actuals provenance differs from the prediction")
        actual_daily = {row.target_date: row for row in actuals.daily_actuals}
        daily = []
        for forecast in prediction.daily_forecasts:
            actual = actual_daily.get(forecast.target_date)
            if actual is None:
                continue
            daily.append(
                {
                    "target_date": forecast.target_date,
                    "predicted_rooms": forecast.predicted_occupied_rooms,
                    "actual_rooms": actual.actual_rooms_sold,
                    "absolute_error_rooms": abs(
                        forecast.predicted_occupied_rooms - actual.actual_rooms_sold
                    ),
                }
            )
        actual_room_types = {
            (row.target_date, row.room_type_code): row
            for row in actuals.room_type_actuals
        }
        room_types = []
        for forecast in prediction.room_type_forecasts:
            actual = actual_room_types.get((forecast.target_date, forecast.room_type_code))
            if actual is None:
                continue
            error = abs(forecast.predicted_rooms - actual.actual_rooms_sold)
            if not math.isfinite(error):
                raise RuntimeError("ML actual comparison contains a non-finite error")
            room_types.append(
                {
                    "target_date": forecast.target_date,
                    "room_type_code": forecast.room_type_code,
                    "predicted_rooms": forecast.predicted_rooms,
                    "actual_rooms": actual.actual_rooms_sold,
                    "absolute_error_rooms": error,
                }
            )
        payload = {
            "schema_version": "MLRoomDemandActualComparison.v1",
            "execution_id": execution_id,
            "property_id": prediction.property_id,
            "status": "COMPLETE" if actuals.complete else "PENDING",
            "missing_dates": actuals.missing_dates,
            "daily_comparisons": daily,
            "room_type_comparisons": room_types,
            "metrics": _metrics(daily),
            "actuals_query_id": actuals.trino_query_id,
        }
        return MLActualComparison.model_validate(payload).model_dump(mode="json")
