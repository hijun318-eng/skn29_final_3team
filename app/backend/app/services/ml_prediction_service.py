"""ML runtime 응답을 검증하고 예측 provenance를 App DB에 기록한다."""

from __future__ import annotations

from datetime import date
import json
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.ml_prediction_client import MLPredictionClient
from app.contract_core import ContractModel


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


class MLRuntimeCapability(ContractModel):
    """Backend가 호출할 수 있는 객실 수요 Runtime의 release receipt다."""

    model_version: str = Field(min_length=1, max_length=160)
    model_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_type: str = Field(min_length=1, max_length=160)
    estimator_type: Literal["HistGradientBoostingRegressor"]
    approval: Literal["APPROVED", "CONDITIONAL_PASS"]
    max_horizon: int = Field(ge=1, le=7)
    model_max_horizon: int = Field(ge=1, le=31)
    properties: tuple[MLPropertyCapability, ...] = Field(min_length=1)
    synthetic_training_data: bool
    query_id: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_release_scope(self) -> "MLRuntimeCapability":
        """요청 horizon과 호텔 식별자의 중복을 release 단계에서 차단한다."""

        if self.max_horizon > self.model_max_horizon:
            raise ValueError("ML runtime horizon exceeds the model contract")
        property_ids = [item.property_id.upper() for item in self.properties]
        if len(property_ids) != len(set(property_ids)):
            raise ValueError("ML runtime property capability is duplicated")
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

        try:
            capabilities = MLRuntimeCapability.model_validate(
                await self._client.capabilities()
            )
        except ValidationError as error:
            raise RuntimeError("ML capability response is invalid") from error
        return capabilities.model_dump(mode="json")

    async def predict(
        self,
        session: AsyncSession,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """지원 대상만 예측하고 RAG 격리 근거가 있는 결과만 저장한다."""
        capabilities = await self.capabilities()
        supported = {
            str(item.get("property_id")).upper()
            for item in capabilities["properties"]
            if isinstance(item, dict) and str(item.get("property_id") or "").strip()
        }
        property_id = str(payload["property_id"]).upper()
        if property_id not in supported:
            raise ValueError(
                f"unsupported property_id: {property_id}"
            )
        request_payload = {**payload, "property_id": property_id}
        result = await self._client.predict(request_payload)
        if not isinstance(result, dict):
            raise RuntimeError("ML prediction response is invalid")
        if (
            result.get("model_version") != capabilities["model_version"]
            or result.get("model_hash") != capabilities["model_hash"]
        ):
            raise RuntimeError("ML prediction release changed after capability check")
        if (
            result.get("property_id") != property_id
            or result.get("as_of") != request_payload["as_of"]
            or result.get("horizon") != request_payload["horizon"]
        ):
            raise RuntimeError("ML prediction response does not match its request")
        provenance = result.get("provenance")
        if (
            not isinstance(provenance, dict)
            or provenance.get("rag_called") is not False
            or provenance.get("source") != "TRINO_HISTORICAL_DAILY_FACTS"
            or provenance.get("request_as_of") != request_payload["as_of"]
            or not str(provenance.get("history_table") or "").strip()
            or not str(provenance.get("trino_query_id") or "").strip()
        ):
            raise RuntimeError(
                "ML response provenance is incomplete or did not prove RAG isolation"
            )
        if not str(result.get("execution_id") or "").strip() or result.get(
            "status"
        ) != "SUCCEEDED":
            raise RuntimeError("ML prediction receipt is incomplete")
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
                "request_payload": json.dumps(request_payload),
                "result_payload": json.dumps(result),
                "provenance": json.dumps(provenance),
                "status": result["status"],
            },
        )
        return result
