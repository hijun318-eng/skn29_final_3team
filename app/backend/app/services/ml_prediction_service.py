"""ML runtime 응답을 검증하고 예측 provenance를 App DB에 기록한다."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.ml_prediction_client import MLPredictionClient


class MLPredictionService:
    """지원 대상 검증, runtime 호출과 append-only 감사 저장을 조정한다."""

    def __init__(
        self,
        client: MLPredictionClient | None = None,
    ) -> None:
        self._client = client or MLPredictionClient()

    async def capabilities(self) -> dict[str, Any]:
        """runtime capability 응답의 최소 wire 형식을 검증해 반환한다."""
        capabilities = await self._client.capabilities()
        if not isinstance(capabilities, dict) or not isinstance(
            capabilities.get("properties"), list
        ):
            raise RuntimeError("ML capability response is invalid")
        return capabilities

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
        provenance = result.get("provenance")
        if not isinstance(provenance, dict) or provenance.get("rag_called") is not False:
            raise RuntimeError(
                "ML response provenance did not prove RAG isolation"
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
