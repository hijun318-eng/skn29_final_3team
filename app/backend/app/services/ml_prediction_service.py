"""ML runtime 응답을 검증하고 예측 provenance를 App DB에 기록한다."""

from __future__ import annotations

from datetime import date, timedelta
import json
import math
import os
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictStr, ValidationError, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.ml_prediction_client import MLPredictionClient
from app.contract_core import ContractModel


ML_RUNTIME_CAPABILITY_VERSION = "MLRuntimeCapability.v2"
ML_PREDICTION_RESULT_VERSION = "MLRoomDemandPrediction.v1"
ML_ABSOLUTE_MAX_HORIZON_DAYS = 366
_ENABLED_VALUES = frozenset({"1", "true", "yes"})


class MLDeploymentPolicyError(RuntimeError):
    """유효한 후보 release가 운영 노출 정책을 통과하지 못했음을 나타낸다."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


class MLApprovedRelease(ContractModel):
    """Backend 배포 환경이 독립적으로 고정한 승인 ML release다."""

    model_version: str = Field(min_length=1, max_length=160)
    model_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_env(cls) -> "MLApprovedRelease":
        """Backend가 독립적으로 고정한 승인 release pin 세 개를 검증한다."""

        try:
            return cls.model_validate(
                {
                    "model_version": os.getenv("ML_APPROVED_MODEL_VERSION", ""),
                    "model_hash": os.getenv("ML_APPROVED_MODEL_SHA256", ""),
                    "feature_contract_sha256": os.getenv(
                        "ML_APPROVED_FEATURE_CONTRACT_SHA256",
                        "",
                    ),
                }
            )
        except ValidationError as error:
            raise RuntimeError("ML approved release pins are invalid") from error


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
    signal_rows: int | None = Field(default=None, ge=1)

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
    synthetic_only: StrictBool
    summary_query_id: str = Field(min_length=1, max_length=256)
    continuity_query_id: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_history_window(self) -> "MLHistorySourceCapability":
        """시작일이 종료일보다 늦은 history 영수증은 거부한다."""

        if self.min_date > self.max_date:
            raise ValueError("ML history source date window is invalid")
        return self


class MLSignalSourceCapability(ContractModel):
    """Runtime 시작 시 검증한 목표일 운영 신호 영수증이다."""

    table: str = Field(
        min_length=5,
        max_length=256,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$",
    )
    row_count: int = Field(ge=1)
    property_count: int = Field(ge=1)
    min_cutoff_date: date
    max_cutoff_date: date
    signal_source_kind: Literal["OBSERVED_PIT", "SYNTHETIC_PIT"]
    synthetic_only: StrictBool
    summary_query_id: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_signal_window(self) -> "MLSignalSourceCapability":
        """신호 기준일 시작과 종료 순서가 올바른지 검증한다."""

        if self.min_cutoff_date > self.max_cutoff_date:
            raise ValueError("ML signal source date window is invalid")
        return self


class MLRuntimeCapability(ContractModel):
    """Backend가 호출할 수 있는 객실 수요 Runtime의 release receipt다."""

    schema_version: Literal["MLRuntimeCapability.v2"]
    prediction_contract_version: Literal["MLRoomDemandPrediction.v1"]
    model_version: str = Field(min_length=1, max_length=160)
    model_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_type: str = Field(min_length=1, max_length=160)
    feature_profile: str = Field(
        default="historical_daily_v1",
        min_length=1,
        max_length=160,
    )
    estimator_type: str = Field(min_length=1, max_length=160)
    approval: Literal["APPROVED", "CONDITIONAL_PASS"]
    approval_status: StrictStr = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    min_horizon_days: int = Field(ge=1, le=ML_ABSOLUTE_MAX_HORIZON_DAYS)
    max_horizon_days: int = Field(ge=1, le=ML_ABSOLUTE_MAX_HORIZON_DAYS)
    model_max_horizon_days: int = Field(ge=1, le=ML_ABSOLUTE_MAX_HORIZON_DAYS)
    properties: tuple[MLPropertyCapability, ...] = Field(min_length=1)
    synthetic_training_data: StrictBool
    history_source: MLHistorySourceCapability
    signal_source: MLSignalSourceCapability | None = None
    query_id: str = Field(min_length=1, max_length=256)
    signal_query_id: str | None = Field(default=None, min_length=1, max_length=256)

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
        operational = self.feature_profile == "point_in_time_demand_v1"
        if operational != (self.signal_source is not None):
            raise ValueError("ML operational feature profile and signal source differ")
        if operational != (self.signal_query_id is not None):
            raise ValueError("ML operational signal query receipt is incomplete")
        if operational and any(item.signal_rows is None for item in self.properties):
            raise ValueError("ML operational property signal rows are incomplete")
        if (
            operational
            and self.signal_source is not None
            and self.signal_source.synthetic_only != self.synthetic_training_data
        ):
            raise ValueError("ML release and signal source synthetic mode differ")
        return self


def require_production_ml_capability(
    capability: MLRuntimeCapability,
) -> MLRuntimeCapability:
    """후보 검증과 분리해 운영에 노출 가능한 ML release만 반환한다."""

    if (
        capability.approval != "APPROVED"
        or capability.approval_status != "APPROVED"
    ):
        raise MLDeploymentPolicyError(
            "ML_RELEASE_NOT_PRODUCTION_APPROVED",
            "ML 모델 release가 운영 승인을 완료하지 않았습니다.",
        )
    if capability.synthetic_training_data:
        raise MLDeploymentPolicyError(
            "ML_SYNTHETIC_TRAINING_DATA_BLOCKED",
            "합성 학습 데이터로 검증된 ML release는 운영에 노출할 수 없습니다.",
        )
    if (
        capability.signal_source is not None
        and (
            capability.signal_source.signal_source_kind != "OBSERVED_PIT"
            or capability.signal_source.synthetic_only
        )
    ):
        raise MLDeploymentPolicyError(
            "ML_SIGNAL_PROVENANCE_BLOCKED",
            "시점이 증명된 실운영 신호만 운영에 노출할 수 있습니다.",
        )
    return capability


def require_deployed_ml_capability(
    capability: MLRuntimeCapability,
) -> MLRuntimeCapability:
    """운영 승인 release 또는 명시적으로 연 로컬 합성 후보만 반환한다."""

    try:
        return require_production_ml_capability(capability)
    except MLDeploymentPolicyError:
        allow_conditional = (
            os.getenv("ML_ALLOW_CONDITIONAL", "").strip().lower()
            in _ENABLED_VALUES
        )
        if (
            allow_conditional
            and capability.approval == "CONDITIONAL_PASS"
            and capability.approval_status == "VALIDATED_SYNTHETIC"
            and capability.synthetic_training_data is True
            and capability.history_source.synthetic_only is True
        ):
            return capability
        raise


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
    signal_table: str | None = Field(
        default=None,
        min_length=5,
        max_length=256,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$",
    )
    signal_query_id: str | None = Field(default=None, min_length=1, max_length=256)
    feature_as_of: date
    request_as_of: date
    rag_called: Literal[False]

    @model_validator(mode="after")
    def validate_signal_receipt(self) -> "MLPredictionProvenance":
        """운영 신호 테이블과 조회 식별자가 함께 존재하는지 검증한다."""

        if (self.signal_table is None) != (self.signal_query_id is None):
            raise ValueError("ML signal provenance is incomplete")
        return self


class MLPredictionInterval(ContractModel):
    """예측값 주변의 보정 80%·95% 범위다."""

    lower_80: float = Field(ge=0)
    upper_80: float = Field(ge=0)
    lower_95: float = Field(ge=0)
    upper_95: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> "MLPredictionInterval":
        """모든 범위가 유한하며 95% 범위가 80% 범위를 포함하는지 검증한다."""

        values = (self.lower_95, self.lower_80, self.upper_80, self.upper_95)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("ML prediction interval contains a non-finite value")
        if not self.lower_95 <= self.lower_80 <= self.upper_80 <= self.upper_95:
            raise ValueError("ML prediction interval bounds are inconsistent")
        return self


class MLInfluencingFactor(ContractModel):
    """개별 예측에서 기준값 대비 객실 수 변화가 큰 요인이다."""

    feature_code: str = Field(min_length=1, max_length=96)
    label: str = Field(min_length=1, max_length=96)
    value: float
    reference_value: float
    impact_rooms: float
    direction: Literal["INCREASE", "DECREASE"]

    @model_validator(mode="after")
    def validate_values(self) -> "MLInfluencingFactor":
        """영향 요인의 값·기준값·객실 수 영향이 유한한지 검증한다."""

        if not all(
            math.isfinite(value)
            for value in (self.value, self.reference_value, self.impact_rooms)
        ):
            raise ValueError("ML influencing factor contains a non-finite value")
        return self


class MLQualityScope(ContractModel):
    """객실 유형별 독립 검증 상태와 평가 단위를 보존한다."""

    status: Literal["APPROVED", "NOT_APPROVED"]
    volume_class: Literal["HIGH", "LOW"]
    wape: float = Field(ge=0)
    mae: float = Field(ge=0)
    baseline_wape: float = Field(ge=0)
    baseline_mae: float = Field(ge=0)


class MLDailyForecast(ContractModel):
    """한 영업일의 객실 수요·잔여·점유율 예측을 동일 capacity에 결속한다."""

    target_date: date
    total_available_rooms: float = Field(gt=0)
    predicted_occupied_rooms: float = Field(ge=0)
    predicted_available_rooms: float = Field(ge=0)
    predicted_occupancy_rate: float = Field(ge=0, le=1)
    prediction_interval: MLPredictionInterval | None = None

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
        if (
            self.prediction_interval is not None
            and self.prediction_interval.upper_95 > self.total_available_rooms + 0.02
        ):
            raise ValueError("ML daily prediction interval exceeds available capacity")
        return self


class MLRoomTypeForecast(ContractModel):
    """일자·객실 유형별 raw·capacity-clipped 예측값을 보존한다."""

    target_date: date
    room_type_code: str = Field(min_length=1, max_length=64)
    available_rooms: float = Field(gt=0)
    predicted_rooms_raw: float
    predicted_rooms: float = Field(ge=0)
    occupancy_rate: float = Field(ge=0, le=1)
    prediction_interval: MLPredictionInterval | None = None
    influencing_factors: tuple[MLInfluencingFactor, ...] | None = None
    quality_scope: MLQualityScope | None = None

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
        if (
            self.prediction_interval is not None
            and self.prediction_interval.upper_95 > self.available_rooms + 0.02
        ):
            raise ValueError("ML room-type prediction interval exceeds available capacity")
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
    feature_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
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
        self._client = client

    def _runtime_client(self) -> MLPredictionClient:
        """선택 기능이 실제 호출될 때만 환경 검증과 HTTP client를 구성한다."""

        if self._client is None:
            self._client = MLPredictionClient()
        return self._client

    async def capabilities(self) -> dict[str, Any]:
        """배포 정책까지 통과한 운영 Runtime receipt만 반환한다."""

        return (await self._production_capabilities()).model_dump(mode="json")

    async def _validated_capabilities(self) -> MLRuntimeCapability:
        """원시 runtime 응답을 versioned capability 계약으로 한 번 검증한다."""

        approved = MLApprovedRelease.from_env()
        try:
            capabilities = MLRuntimeCapability.model_validate(
                await self._runtime_client().capabilities()
            )
        except ValidationError as error:
            raise RuntimeError("ML capability response is invalid") from error
        if (
            capabilities.model_version != approved.model_version
            or capabilities.model_hash != approved.model_hash
            or capabilities.feature_contract_sha256
            != approved.feature_contract_sha256
        ):
            raise RuntimeError("ML runtime capability does not match approved release pins")
        return capabilities

    async def _production_capabilities(self) -> MLRuntimeCapability:
        """정확한 release pin과 현재 배포의 운영·후보 정책을 함께 검사한다."""

        return require_deployed_ml_capability(
            await self._validated_capabilities()
        )

    async def predict(
        self,
        session: AsyncSession,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """지원 대상만 예측하고 RAG 격리 근거가 있는 결과만 저장한다."""

        result = await self.generate_prediction(payload)
        await self.persist_prediction(session, result)
        return result

    async def generate_prediction(self, payload: dict[str, Any]) -> dict[str, Any]:
        """외부 호출과 결과 검증을 끝내되 caller의 DB transaction은 열지 않는다."""

        try:
            prediction_request = MLPredictionRequest.model_validate(payload)
        except ValidationError as error:
            raise ValueError("ML prediction request is invalid") from error
        capability = await self._production_capabilities()
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
        raw_result = await self._runtime_client().predict(request_payload)
        try:
            prediction = MLRoomDemandPrediction.model_validate(raw_result)
        except ValidationError as error:
            raise RuntimeError("ML prediction response is invalid") from error
        result = prediction.model_dump(mode="json")
        if (
            prediction.model_version != capability.model_version
            or prediction.model_hash != capability.model_hash
            or prediction.feature_contract_sha256
            != capability.feature_contract_sha256
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
        if capability.signal_source is not None and (
            prediction.provenance.signal_table != capability.signal_source.table
            or prediction.provenance.signal_query_id is None
        ):
            raise RuntimeError("ML operational signal provenance is incomplete")
        return result

    @staticmethod
    async def persist_prediction(
        session: AsyncSession,
        result: dict[str, Any],
    ) -> None:
        """검증된 예측 감사 이벤트를 caller의 terminal transaction에 추가한다."""

        try:
            prediction = MLRoomDemandPrediction.model_validate(result)
        except ValidationError as error:
            raise RuntimeError("ML prediction audit payload is invalid") from error
        canonical_result = prediction.model_dump(mode="json")
        request_payload = {
            "property_id": prediction.property_id,
            "as_of": prediction.as_of.isoformat(),
            "horizon_days": prediction.horizon_days,
        }
        provenance = canonical_result["provenance"]
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
                "execution_id": canonical_result["execution_id"],
                "request_payload": json.dumps(request_payload, allow_nan=False),
                "result_payload": json.dumps(canonical_result, allow_nan=False),
                "provenance": json.dumps(provenance, allow_nan=False),
                "status": canonical_result["status"],
            },
        )
