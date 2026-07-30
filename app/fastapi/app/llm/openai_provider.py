"""OpenAI 호환 LLM provider — 외부 API 및 RunPod vLLM 지원.

OpenAI API(https://api.openai.com/v1)와 호환되는 모든 엔드포인트를 지원한다.
RunPod vLLM Serverless, 로컬 vLLM, OpenAI API 등이 모두 이 provider를 사용한다.

환경변수:
    LLM_API_BASE: API 베이스 URL (기본: https://api.openai.com/v1)
    LLM_API_KEY: API 키
    LLM_MODEL: 모델명 (기본: gpt-4o-mini)
"""

from __future__ import annotations

import os
import time

import httpx

from app.llm.base import LLMProvider, LLMResponse
from app.settings import LLM_API_BASE, LLM_API_KEY, LLM_MODEL


class OpenAIProvider(LLMProvider):
    """OpenAI 호환 API provider.

    OpenAI API, RunPod vLLM, 로컬 vLLM 서버 등
    /v1/chat/completions 엔드포인트를 지원하는 모든 서비스에 연결한다.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._base_url = (base_url or LLM_API_BASE).rstrip("/")
        self._api_key = api_key or LLM_API_KEY
        self._model = model or LLM_MODEL

    async def complete(self, prompt: str, **kwargs: object) -> LLMResponse:
        """OpenAI /v1/chat/completions으로 텍스트 완성을 수행한다."""
        model = kwargs.get("model", self._model)
        system = kwargs.get("system", "당신은 호텔 운영 데이터 분석 전문가입니다.")
        start = time.monotonic()

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": str(system)},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": kwargs.get("max_tokens", 500),
                    "temperature": kwargs.get("temperature", 0.3),
                },
            )
            resp.raise_for_status()
            data = resp.json()

        latency = (time.monotonic() - start) * 1000
        choice = data.get("choices", [{}])[0]
        return LLMResponse(
            text=choice.get("message", {}).get("content", ""),
            usage=data.get("usage", {}),
            model_name=f"openai:{model}",
            latency_ms=round(latency, 2),
        )

    async def embed(self, text: str) -> list[float]:
        """OpenAI /v1/embeddings로 임베딩을 수행한다."""
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/embeddings",
                headers=headers,
                json={"model": "text-embedding-3-small", "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [{}])[0].get("embedding", [])
