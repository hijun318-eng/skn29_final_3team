from __future__ import annotations

import os
from typing import Any

import httpx


class MLPredictionClient:
    def __init__(self) -> None:
        self._base_url = os.getenv(
            "ML_RUNTIME_URL",
            "http://ml-runtime:8000",
        ).rstrip("/")
        self._timeout = float(
            os.getenv("ML_RUNTIME_TIMEOUT_SECONDS", "45")
        )

    async def capabilities(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._base_url}/capabilities"
            )
            response.raise_for_status()
            return response.json()

    async def predict(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/predictions/room-demand",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
