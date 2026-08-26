from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.ml_prediction_client import MLPredictionClient


class MLPredictionService:
    def __init__(
        self,
        client: MLPredictionClient | None = None,
    ) -> None:
        self._client = client or MLPredictionClient()

    async def capabilities(self) -> dict[str, Any]:
        return await self._client.capabilities()

    async def predict(
        self,
        session: AsyncSession,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        capabilities = await self._client.capabilities()
        supported = {
            str(item["property_id"]).upper()
            for item in capabilities.get("properties", [])
        }
        property_id = str(payload["property_id"]).upper()
        if property_id not in supported:
            raise ValueError(
                f"unsupported property_id: {property_id}"
            )
        request_payload = {**payload, "property_id": property_id}
        result = await self._client.predict(request_payload)
        if result.get("provenance", {}).get("rag_called") is not False:
            raise RuntimeError(
                "ML response provenance did not prove RAG isolation"
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
                "request_payload": json.dumps(request_payload),
                "result_payload": json.dumps(result),
                "provenance": json.dumps(result["provenance"]),
                "status": result["status"],
            },
        )
        return result
