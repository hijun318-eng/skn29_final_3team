"""승인된 ML runtime의 capability와 예측 endpoint만 호출하는 HTTP adapter다."""

from __future__ import annotations

import math
import os
from typing import Any

import httpx


class MLPredictionClient:
    """서버가 구성한 ML runtime URL과 timeout으로 제한된 요청을 전송한다."""

    def __init__(self) -> None:
        self._base_url = os.getenv(
            "ML_RUNTIME_URL",
            "http://ml-runtime:8000",
        ).rstrip("/")
        try:
            timeout = float(os.getenv("ML_RUNTIME_TIMEOUT_SECONDS", "45"))
        except ValueError as error:
            raise RuntimeError("ML_RUNTIME_TIMEOUT_SECONDS is invalid") from error
        if not math.isfinite(timeout) or not 0.1 <= timeout <= 300:
            raise RuntimeError("ML_RUNTIME_TIMEOUT_SECONDS is invalid")
        self._timeout = timeout
        endpoint = httpx.URL(self._base_url)
        if endpoint.scheme not in {"http", "https"} or not endpoint.host or endpoint.userinfo:
            raise RuntimeError("ML_RUNTIME_URL is invalid")

    async def capabilities(self) -> dict[str, Any]:
        """runtime이 현재 제공하는 모델·대상·기간 capability를 조회한다."""
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            response = await client.get(
                f"{self._base_url}/capabilities"
            )
            response.raise_for_status()
            return response.json()

    async def predict(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """검증된 예측 요청을 runtime에 전달하고 원시 응답을 반환한다."""
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            response = await client.post(
                f"{self._base_url}/predictions/room-demand",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
