"""승인된 ML runtime의 capability와 예측 endpoint만 호출하는 HTTP adapter다."""

from __future__ import annotations

import math
import os
from typing import Any

import httpx

from src.ml.runtime_trust import (
    ML_RUNTIME_NONCE_HEADER,
    canonical_json_bytes,
    request_auth_headers,
    runtime_hmac_secret,
    verify_response_auth,
)


class MLPredictionClient:
    """서버가 구성한 ML runtime URL과 timeout으로 제한된 요청을 전송한다."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
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
        self._secret = runtime_hmac_secret()
        self._transport = transport

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = b"" if payload is None else canonical_json_bytes(payload)
        headers = request_auth_headers(self._secret, method, path, body)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(
            timeout=self._timeout,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                content=body,
                headers=headers,
            )
        verify_response_auth(
            self._secret,
            response.headers,
            path,
            response.status_code,
            headers[ML_RUNTIME_NONCE_HEADER],
            response.content,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("ML runtime response must be a JSON object")
        return result

    async def capabilities(self) -> dict[str, Any]:
        """runtime이 현재 제공하는 모델·대상·기간 capability를 조회한다."""
        return await self._request("GET", "/capabilities")

    async def predict(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """검증된 예측 요청을 runtime에 전달하고 원시 응답을 반환한다."""
        return await self._request("POST", "/predictions/room-demand", payload)

    async def actuals(self, payload: dict[str, Any]) -> dict[str, Any]:
        """예측 목표기간에 새로 들어온 실적을 runtime에서 조회한다."""

        return await self._request("POST", "/actuals/room-demand", payload)
