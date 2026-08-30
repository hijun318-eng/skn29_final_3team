"""ML runtime 응답을 검증하고 예측 provenance를 App DB에 기록한다."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import math
from typing import Any, Literal
from uuid import UUID

import httpx
from pydantic import Field, ValidationError, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.ml_prediction_client import MLPredictionClient
from app.contract_core import ContractModel
from app.ports.agent import (
    AgentKind,
    AgentPortReadiness,
    ML_ABSOLUTE_MAX_HORIZON_DAYS,
)


ML_RUNTIME_CAPABILITY_VERSION = "MLRuntimeCapability.v1"
ML_PREDICTION_RESULT_VERSION = "MLRoomDemandPrediction.v1"


class MLPropertyCapability(ContractModel):
    """한 호텔의 예측 가능 기준일과 읽힌 history 범위를 고정한다."""

    property_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    min_as_of: date
    max_as_of: date
    feature_max_as_of: date
    history_rows: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_date_window(self) -> "MLPropertyCapability":
        """Feature 기준일이 공개된 예측 가능 구간 밖이면 후보를 거부한다."""

        if not self.min_as_of <= self.feature_max_as_of <= self.max_as_of:
            raise ValueError("ML property capability date window is invalid")
        return self


class MLHistorySourceCapability(ContractModel):
    """Runtime 시작 시 검증된 history source의 최소 영수증이다."""

    table: str = Field(
        min_length=5,
        max_length=256,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$",
    )
    row_count: int = Field(ge=1)
    property_count: int = Field(ge=1)
    series_count: int = Field(ge=1)
    min_date: date
    max_date: date
    synthetic_only: bool
    summary_query_id: str = Field(min_length=1, max_length=256)
    continuity_query_id: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_history_window(self) -> "MLHistorySourceCapability":
        """시작일이 종료일보다 늦은 history 영수증은 거부한다."""

        if self.min_date > self.max_date:
            raise ValueError("ML history source date window is invalid")
        return self


class MLRuntimeCapability(ContractModel):
    """Backend가 호출할 수 있는 객실 수요 Runtime의 release receipt다."""

    schema_version: Literal["MLRuntimeCapability.v1"]
    prediction_contract_version: Literal["MLRoomDemandPrediction.v1"]
    model_version: str = Field(min_length=1, max_length=160)
    model_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_type: str = Field(min_length=1, max_length=160)
    estimator_type: str = Field(min_length=1, max_length=160)
    approval: Literal["APPROVED", "CONDITIONAL_PASS"]
    min_horizon_days: int = Field(ge=1, le=ML_ABSOLUTE_MAX_HORIZON_DAYS)
    max_horizon_days: int = Field(ge=1, le=ML_ABSOLUTE_MAX_HORIZON_DAYS)
    model_max_horizon_days: int = Field(ge=1, le=ML_ABSOLUTE_MAX_HORIZON_DAYS)
    properties: tuple[MLPropertyCapability, ...] = Field(min_length=1)
    synthetic_training_data: bool
    history_source: MLHistorySourceCapability
    query_id: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_release_scope(self) -> "MLRuntimeCapability":
        """요청 horizon과 호텔 식별자의 중복을 release 단계에서 차단한다."""

        if not (
            self.min_horizon_days
            <= self.max_horizon_days
            <= self.model_max_horizon_days
        ):
            raise ValueError("ML runtime horizon exceeds the model contract")
        property_ids = [item.property_id.upper() for item in self.properties]
        if len(property_ids) != len(set(property_ids)):
            raise ValueError("ML runtime property capability is duplicated")
        if self.synthetic_training_data != self.history_source.synthetic_only:
            raise ValueError("ML release and history source synthetic mode differ")
        return self


class MLPredictionRequest(ContractModel):
    """Backend와 ML runtime이 공유하는 일 단위 예측 입력이다."""

    property_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    as_of: date
    horizon_days: int = Field(ge=1, le=ML_ABSOLUTE_MAX_HORIZON_DAYS)


class MLPredictionProvenance(ContractModel):
    """예측값이 승인 history 조회와 요청 기준일에서 생성됐음을 증명한다."""

    source: Literal["TRINO_HISTORICAL_DAILY_FACTS"]
    history_table: str = Field(
        min_length=5,
        max_length=256,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$",
    )
    trino_query_id: str = Field(min_length=1, max_length=256)
    feature_as_of: date
    request_as_of: date
    rag_called: Literal[False]


class MLDailyForecast(ContractModel):
    """한 영업일의 객실 수요·잔여·점유율 예측을 동일 capacity에 결속한다."""

    target_date: date
    total_available_rooms: float = Field(gt=0)
    predicted_occupied_rooms: float = Field(ge=0)
    predicted_available_rooms: float = Field(ge=0)
    predicted_occupancy_rate: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_capacity_balance(self) -> "MLDailyForecast":
        """일별 예측의 유한 값·수용량 합계·점유율이 서로 일치하는지 확인한다."""

        values = (
            self.total_available_rooms,
            self.predicted_occupied_rooms,
            self.predicted_available_rooms,
            self.predicted_occupancy_rate,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("ML daily forecast contains a non-finite value")
        if self.predicted_occupied_rooms > self.total_available_rooms + 0.02:
            raise ValueError("ML occupied rooms exceed available capacity")
        if not math.isclose(
            self.predicted_occupied_rooms + self.predicted_available_rooms,
            self.total_available_rooms,
            abs_tol=0.02,
        ):
            raise ValueError("ML daily forecast capacity does not balance")
        if not math.isclose(
            self.predicted_occupancy_rate,
            self.predicted_occupied_rooms / self.total_available_rooms,
            abs_tol=0.00001,
        ):
            raise ValueError("ML daily forecast occupancy rate is inconsistent")
        return self


class MLRoomTypeForecast(ContractModel):
    """일자·객실 유형별 raw·capacity-clipped 예측값을 보존한다."""

    target_date: date
    room_type_code: str = Field(min_length=1, max_length=64)
    available_rooms: float = Field(gt=0)
    predicted_rooms_raw: float
    predicted_rooms: float = Field(ge=0)
    occupancy_rate: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_capacity(self) -> "MLRoomTypeForecast":
        """객실 유형별 예측이 유한하고 수용량·점유율 계약을 지키는지 확인한다."""

        values = (
            self.available_rooms,
            self.predicted_rooms_raw,
            self.predicted_rooms,
            self.occupancy_rate,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("ML room-type forecast contains a non-finite value")
        if self.predicted_rooms > self.available_rooms + 0.02:
            raise ValueError("ML room-type prediction exceeds available capacity")
        if not math.isclose(
            self.occupancy_rate,
            self.predicted_rooms / self.available_rooms,
            abs_tol=0.00001,
        ):
            raise ValueError("ML room-type occupancy rate is inconsistent")
        return self


class MLRoomDemandPrediction(ContractModel):
    """Runtime의 전체 room-demand prediction wire contract를 검증한다."""

    schema_version: Literal["MLRoomDemandPrediction.v1"]
    status: Literal["SUCCEEDED"]
    execution_id: UUID
    property_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    as_of: date
    feature_as_of: date
    horizon_days: int = Field(ge=1, le=ML_ABSOLUTE_MAX_HORIZON_DAYS)
    model_version: str = Field(min_length=1, max_length=160)
    model_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    daily_forecasts: tuple[MLDailyForecast, ...] = Field(min_length=1)
    room_type_forecasts: tuple[MLRoomTypeForecast, ...] = Field(min_length=1)
    provenance: MLPredictionProvenance

    @model_validator(mode="after")
    def validate_prediction_window(self) -> "MLRoomDemandPrediction":
        """요청 창과 일별·유형별 예측, provenance, 합계가 하나의 계약인지 확인한다."""

        expected_dates = tuple(
            self.as_of + timedelta(days=offset)
            for offset in range(1, self.horizon_days + 1)
        )
        daily_dates = tuple(item.target_date for item in self.daily_forecasts)
        if daily_dates != expected_dates:
            raise ValueError("ML daily forecast dates do not match the request horizon")
        room_type_dates = tuple(item.target_date for item in self.room_type_forecasts)
        if set(room_type_dates) != set(expected_dates):
            raise ValueError("ML room-type forecast date is outside the request horizon")
        room_type_keys = tuple(
            (item.target_date, item.room_type_code)
            for item in self.room_type_forecasts
        )
        if len(room_type_keys) != len(set(room_type_keys)):
            raise ValueError("ML room-type forecast identity is duplicated")
        if self.feature_as_of != self.provenance.feature_as_of:
            raise ValueError("ML feature cutoff differs from provenance")
        if self.as_of != self.provenance.request_as_of:
            raise ValueError("ML request date differs from provenance")
        if self.feature_as_of > self.as_of:
            raise ValueError("ML feature cutoff is later than the request date")
        daily_by_date = {item.target_date: item for item in self.daily_forecasts}
        for target_date in expected_dates:
            rows = [
                item
                for item in self.room_type_forecasts
                if item.target_date == target_date
            ]
            daily = daily_by_date[target_date]
            if not math.isclose(
                sum(item.available_rooms for item in rows),
                daily.total_available_rooms,
                abs_tol=0.05,
            ) or not math.isclose(
                sum(item.predicted_rooms for item in rows),
                daily.predicted_occupied_rooms,
                abs_tol=0.05,
            ):
                raise ValueError("ML daily and room-type forecasts do not reconcile")
        return self


class MLPredictionService:
    """지원 대상 검증, runtime 호출과 append-only 감사 저장을 조정한다."""

    def __init__(
        self,
        client: MLPredictionClient | None = None,
    ) -> None:
        self._client = client or MLPredictionClient()

    async def capabilities(self) -> dict[str, Any]:
        """모델·승인·기간·호텔 범위가 완전한 Runtime receipt만 반환한다."""

        return (await self._validated_capabilities()).model_dump(mode="json")

    async def _validated_capabilities(self) -> MLRuntimeCapability:
        """원시 runtime 응답을 versioned capability 계약으로 한 번 검증한다."""

        try:
            capabilities = MLRuntimeCapability.model_validate(
                await self._client.capabilities()
            )
        except ValidationError as error:
            raise RuntimeError("ML capability response is invalid") from error
        return capabilities

    async def readiness(self) -> AgentPortReadiness:
        """현재 모델 release와 capability payload가 함께 유효할 때만 ready다."""

        try:
            capability = await self._validated_capabilities()
        except (httpx.HTTPError, RuntimeError, ValueError):
            return AgentPortReadiness(
                agent=AgentKind.ML_PREDICTION,
                status="not_ready",
                capability_version=ML_RUNTIME_CAPABILITY_VERSION,
                reason="ML runtime capability를 확인하지 못했습니다.",
            )
        canonical = json.dumps(
            capability.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return AgentPortReadiness(
            agent=AgentKind.ML_PREDICTION,
            status="ready",
            capability_version=capability.schema_version,
            release_refs=(
                f"ml-model:sha256:{capability.model_hash}",
                f"ml-capability:sha256:{digest}",
            ),
        )

    async def predict(
        self,
        session: AsyncSession,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """지원 대상만 예측하고 RAG 격리 근거가 있는 결과만 저장한다."""
        try:
            prediction_request = MLPredictionRequest.model_validate(payload)
        except ValidationError as error:
            raise ValueError("ML prediction request is invalid") from error
        capability = await self._validated_capabilities()
        supported = {
            item.property_id.upper(): item
            for item in capability.properties
        }
        property_id = prediction_request.property_id.upper()
        property_capability = supported.get(property_id)
        if property_capability is None:
            raise ValueError(
                f"unsupported property_id: {property_id}"
            )
        if not (
            capability.min_horizon_days
            <= prediction_request.horizon_days
            <= capability.max_horizon_days
        ):
            raise ValueError("unsupported ML prediction horizon_days")
        if not (
            property_capability.min_as_of
            <= prediction_request.as_of
            <= property_capability.max_as_of
        ):
            raise ValueError("unsupported ML prediction as_of")
        request_payload = prediction_request.model_dump(mode="json")
        request_payload["property_id"] = property_id
        raw_result = await self._client.predict(request_payload)
        try:
            prediction = MLRoomDemandPrediction.model_validate(raw_result)
        except ValidationError as error:
            raise RuntimeError("ML prediction response is invalid") from error
        result = prediction.model_dump(mode="json")
        if (
            prediction.model_version != capability.model_version
            or prediction.model_hash != capability.model_hash
        ):
            raise RuntimeError("ML prediction release changed after capability check")
        if (
            prediction.property_id != property_id
            or prediction.as_of != prediction_request.as_of
            or prediction.horizon_days != prediction_request.horizon_days
        ):
            raise RuntimeError("ML prediction response does not match its request")
        provenance = result["provenance"]
        if (
            prediction.provenance.rag_called is not False
            or prediction.provenance.source != "TRINO_HISTORICAL_DAILY_FACTS"
            or prediction.provenance.history_table
            != capability.history_source.table
        ):
            raise RuntimeError(
                "ML response provenance is incomplete or did not prove RAG isolation"
            )
        await session.execute(
            text(
                """
                INSERT INTO governance.ml_prediction_audit_events
                    (
                        execution_id,
                        request_payload,
                        result_payload,
                        provenance,
                        status,
                        rag_called
                    )
                VALUES
                    (
                        :execution_id,
                        CAST(:request_payload AS jsonb),
                        CAST(:result_payload AS jsonb),
                        CAST(:provenance AS jsonb),
                        :status,
                        false
                    )
                """
            ),
            {
                "execution_id": result["execution_id"],
                "request_payload": json.dumps(request_payload, allow_nan=False),
                "result_payload": json.dumps(result, allow_nan=False),
                "provenance": json.dumps(provenance, allow_nan=False),
                "status": result["status"],
            },
        )
        return result
