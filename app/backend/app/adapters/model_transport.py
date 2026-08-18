"""OpenAI-compatible HTTP 호출을 Basic provider 설정·timeout·응답 metadata가 있는 비동기 transport로 감싼다.

Async OpenAI-compatible transport for production model nodes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.adapters.async_model_client import (
    AsyncProductionModelClient,
    ModelAuthenticationError,
    ModelRateLimitError,
)
from app.adapters.model_schemas import (
    openai_payload,
    qwen_payload,
)
from src.modelops.runtime import _TRANSPORT_META_KEY


def _validated_https_url(url: str, *, label: str) -> str:
    """외부 모델 URL이 credential 없는 절대 HTTPS 주소인지 검증한다.

    Bearer token을 header에 추가하기 전에 이 검증을 수행한다. 따라서 잘못된 scheme이나
    URL 내 credential·query·fragment가 들어오면 HTTP client 또는 네트워크에 도달하지 않는다.
    """
    if not isinstance(url, str) or not url or any(character.isspace() for character in url):
        raise ValueError(f"{label} must be a non-empty URL without whitespace")
    try:
        parsed = httpx.URL(url)
    except (TypeError, httpx.InvalidURL) as error:
        raise ValueError(f"{label} must be a valid absolute HTTPS URL") from error
    if parsed.scheme != "https" or not parsed.host:
        raise ValueError(f"{label} must use HTTPS and include a host")
    if parsed.userinfo:
        raise ValueError(f"{label} must not contain URL credentials")
    # 빈 query/fragment도 endpoint 경계를 흐리므로 구분자 자체를 허용하지 않는다.
    if "?" in url:
        raise ValueError(f"{label} must not contain a query")
    if "#" in url:
        raise ValueError(f"{label} must not contain a fragment")
    return url


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    token: str | None,
    timeout: float,
) -> dict[str, Any]:
    """검증된 HTTPS 모델 URL에 JSON을 보내고 상태 코드와 응답 객체 타입을 확인한다.

    이 함수도 완성된 요청 URL을 다시 검증한다. 상위 endpoint 검증이 누락된 새로운 호출 경로가
    추가되더라도 Bearer token이 평문 HTTP나 URL credential 대상으로 전송되지 않게 하기 위함이다.
    """
    request_url = _validated_https_url(url, label="model request URL")
    headers = {
        "Accept": "application/json",
        "User-Agent": "answervice-control-plane/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        # endpoint별 timeout을 request 단위로 강제해야 응답 없는 provider 하나가 FastAPI
        # worker와 전체 분석 pipeline을 무기한 점유하지 않는다.
        response = await client.request(
            method,
            request_url,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        result = response.json()
    except httpx.TimeoutException as error:
        raise TimeoutError("model endpoint request timed out") from error
    except httpx.HTTPStatusError as error:
        status_code = error.response.status_code
        if status_code in {401, 403}:
            raise ModelAuthenticationError(
                f"model endpoint returned HTTP {status_code}"
            ) from error
        if status_code == 429:
            raise ModelRateLimitError("model endpoint rate limit was reached") from error
        if 400 <= status_code < 500:
            raise ValueError(
                f"model endpoint rejected the request with HTTP {status_code}"
            ) from error
        raise OSError(f"model endpoint returned HTTP {status_code}") from error
    except httpx.RequestError as error:
        raise OSError("model endpoint request failed") from error
    if not isinstance(result, dict):
        raise ValueError("model endpoint response must be a JSON object")
    return result


async def _openai_transport_with_owned_or_mock_client(
    endpoint: str,
    token: str | None,
    node: str,
    payload: dict[str, Any],
    timeout: float,
    *,
    model: str,
    provider: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """소유권이 확인된 client로 OpenAI 호환 요청을 보내고 모델 결과와 trace를 반환한다.

    이 private 함수에는 ``OpenAITransport``가 직접 소유한 pool 또는 public test seam에서
    검증한 ``MockTransport`` client만 전달한다. client가 없으면 proxy를 상속하지 않는 임시
    client를 만들고 호출 종료 시 닫는다.
    """
    base_endpoint = _validated_https_url(endpoint, label="model endpoint").rstrip("/")
    if provider not in {"openai", "qwen"}:
        raise ValueError(f"unsupported model provider: {provider}")
    owns_client = client is None
    transport = client or httpx.AsyncClient(trust_env=False)
    try:
        response = await _request_json(
            transport,
            "POST",
            f"{base_endpoint}/v1/chat/completions",
            qwen_payload(model, node, payload)
            if provider == "qwen"
            else openai_payload(model, node, payload),
            token,
            timeout,
        )
    finally:
        # 호출자가 주입한 pooled client는 그 호출자의 수명주기를 따른다. 여기서 닫으면
        # 병렬 요청을 깨뜨리므로 함수가 직접 만든 임시 client만 종료한다.
        if owns_client:
            await transport.aclose()
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("chat completion response has no valid choice")
    if not isinstance(choices[0], dict):
        raise ValueError("chat completion choice must be an object")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ValueError("chat completion response has no text content")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError("model content must be a JSON object")
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    result[_TRANSPORT_META_KEY] = {
        "model_version": model,
        "model_snapshot": response.get("model") or model,
        "input_tokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
        "output_tokens": usage.get("completion_tokens") or usage.get("output_tokens"),
    }
    return result


async def openai_transport(
    endpoint: str,
    token: str | None,
    node: str,
    payload: dict[str, Any],
    timeout: float,
    *,
    model: str,
    provider: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """HTTPS 모델을 호출하되 외부 client 주입은 네트워크 없는 테스트로 한정한다.

    운영 호출은 client를 생략해 함수가 안전한 임시 client를 소유하거나
    ``OpenAITransport``를 사용해 장기 connection pool을 소유해야 한다. public seam에 실제
    network client가 들어오면 TLS·proxy 정책을 우회할 수 있으므로 ``MockTransport``만 받는다.
    """

    if client is not None and not isinstance(
        getattr(client, "_transport", None),
        httpx.MockTransport,
    ):
        raise ValueError("Only httpx.MockTransport may be injected")
    return await _openai_transport_with_owned_or_mock_client(
        endpoint,
        token,
        node,
        payload,
        timeout,
        model=model,
        provider=provider,
        client=client,
    )


class OpenAITransport:
    """한 모델 endpoint의 HTTPS 연결 pool과 인증 token 수명주기를 소유한다.

    생성 시 endpoint 보안 계약을 먼저 검증한다. 운영 client는 환경 proxy와 인증 정보를 상속하지
    않으며, ``aclose``를 호출할 때까지 여러 모델 요청에서 같은 연결 pool을 재사용한다.
    """

    def __init__(self, endpoint: str, token: str, *, model: str, provider: str) -> None:
        self._endpoint = _validated_https_url(endpoint, label="model endpoint").rstrip("/")
        self._token = token
        self._model = model
        self._provider = provider
        self._client = httpx.AsyncClient(trust_env=False)

    async def __call__(
        self,
        node: str,
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """보유한 HTTPS client로 노드 요청을 전송하고 provider 응답을 계약 객체로 변환한다."""
        return await _openai_transport_with_owned_or_mock_client(
            self._endpoint,
            self._token,
            node,
            payload,
            timeout,
            model=self._model,
            provider=self._provider,
            client=self._client,
        )

    async def aclose(self) -> None:
        """보유한 비동기 HTTP 연결과 transport 자원을 닫아 connection 누수를 막는다."""
        await self._client.aclose()


class RoutedProductionModelClient:
    """SQL 생성·repair와 나머지 active node를 서로 다른 검증 client에 위임한다.

    Node2 두 노드는 전용 provider credential·capacity를 사용하고 나머지는 primary client를
    사용한다. 마지막 호출 trace는 선택된 client에서 복사하며 종료 시 중복 client는 한 번만 닫는다.
    """
    def __init__(
        self,
        openai_client: AsyncProductionModelClient,
        node2_client: AsyncProductionModelClient,
    ) -> None:
        self._openai_client = openai_client
        self._node2_client = node2_client
        self.last_trace: dict[str, Any] = {}

    async def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        """SQL 생성·repair 노드는 전용 client로, 나머지 노드는 기본 client로 분리 호출한다.

        선택된 client의 검증 trace를 그대로 복사해 실제 provider·model evidence가 라우팅 뒤에도
        손실되지 않게 한다.
        """
        client = self._node2_client if node in {"node2", "node2_repair"} else self._openai_client
        result = await client.generate(node, payload)
        self.last_trace = dict(client.last_trace)
        return result

    async def aclose(self) -> None:
        """보유한 비동기 HTTP 연결과 transport 자원을 닫아 connection 누수를 막는다."""
        clients = [self._openai_client]
        if self._node2_client is not self._openai_client:
            clients.append(self._node2_client)
        results = await asyncio.gather(*(client.aclose() for client in clients), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
