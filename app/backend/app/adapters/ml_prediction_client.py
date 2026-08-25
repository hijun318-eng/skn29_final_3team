"""인증된 Backend와 내부 ML runtime 사이의 bounded async 예측 transport를 소유한다."""

from __future__ import annotations

from typing import Any

import httpx


class MLPredictionUnavailable(RuntimeError):
    """ML runtime 연결·계약·응답 실패를 Backend의 fail-closed 경계로 전달한다."""


class MLPredictionRejected(ValueError):
    """runtime이 요청 scope를 거절한 422 응답을 dependency 장애와 구분한다."""


class MLPredictionClient:
    """Docker 내부 단일 origin의 ML prediction API만 호출한다."""

    def __init__(self, endpoint: str, timeout_seconds: float) -> None:
        url = httpx.URL(endpoint)
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.username
            or url.password
            or url.query
            or url.fragment
            or timeout_seconds <= 0
        ):
            raise ValueError("ML runtime configuration is invalid")
        if url.scheme == "http" and url.host != "ml-runtime":
            raise ValueError("plain HTTP ML runtime must use the private ml-runtime host")
        self._endpoint = str(url).rstrip("/")
        self._client = httpx.AsyncClient(trust_env=False, timeout=timeout_seconds)

    async def capability(self, trace_id: str) -> dict[str, Any]:
        """준비된 승인 모델의 실행 scope만 반환한다."""

        try:
            response = await self._client.get(
                f"{self._endpoint}/health",
                headers={"X-Trace-Id": trace_id},
            )
            response.raise_for_status()
            value = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise MLPredictionUnavailable("ML prediction runtime is unavailable") from error
        required = {"metric", "model_name", "model_version", "property_id", "feature_as_of", "max_horizon"}
        if not isinstance(value, dict) or value.get("status") != "READY" or not required.issubset(value):
            raise MLPredictionUnavailable("ML capability response contract is invalid")
        return value

    async def predict(self, payload: dict[str, Any], trace_id: str, request_id: str) -> dict[str, Any]:
        """예측 요청을 전달하고 성공 object 계약만 반환한다."""

        try:
            response = await self._client.post(
                f"{self._endpoint}/v1/predictions",
                json={**payload, "request_id": request_id, "trace_id": trace_id},
                headers={"X-Trace-Id": trace_id},
            )
        except httpx.HTTPError as error:
            raise MLPredictionUnavailable("ML prediction runtime is unavailable") from error
        if response.status_code == 422:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            raise MLPredictionRejected(str(detail or "ML prediction request is outside the approved scope"))
        try:
            response.raise_for_status()
            value = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise MLPredictionUnavailable("ML prediction runtime is unavailable") from error
        required = {"execution_id", "artifact_hash", "trino_query_ids"}
        if (
            not isinstance(value, dict)
            or value.get("status") != "SUCCESS"
            or not required.issubset(value)
            or not isinstance(value["trino_query_ids"], list)
            or not value["trino_query_ids"]
        ):
            raise MLPredictionUnavailable("ML prediction response contract is invalid")
        return value
