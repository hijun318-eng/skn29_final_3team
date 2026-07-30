"""Ollama LLM provider — 로컬 모델 지원.

Ollama(https://ollama.ai)는 로컬에서 sLLM을 실행하는 도구다.
http://localhost:11434/api/generate 엔드포인트를 사용한다.

환경변수:
    OLLAMA_BASE_URL: Ollama 서버 URL (기본: http://localhost:11434)
    OLLAMA_MODEL: 모델명 (기본: qwen2.5:4b)
"""

from __future__ import annotations

import time

import httpx

from app.llm.base import LLMProvider, LLMResponse
from app.settings import OLLAMA_BASE_URL, OLLAMA_MODEL


class OllamaProvider(LLMProvider):
    """로컬 Ollama 모델 provider.

    로컬에서 실행 중인 Ollama 서버에 연결한다.
    모델은 OLLAMA_MODEL 환경변수로 선택한다.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self._base_url = (base_url or OLLAMA_BASE_URL).rstrip("/")
        self._model = model or OLLAMA_MODEL

    async def complete(self, prompt: str, **kwargs: object) -> LLMResponse:
        """Ollama /api/generate로 텍스트 완성을 수행한다."""
        model = kwargs.get("model", self._model)
        start = time.monotonic()

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": kwargs.get("temperature", 0.3),
                        "num_predict": kwargs.get("max_tokens", 500),
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()

        latency = (time.monotonic() - start) * 1000
        return LLMResponse(
            text=data.get("response", ""),
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
            model_name=f"ollama:{model}",
            latency_ms=round(latency, 2),
        )

    async def embed(self, text: str) -> list[float]:
        """Ollama /api/embeddings로 임베딩을 수행한다."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/api/embeddings",
                json={"model": self._model, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json().get("embedding", [])
