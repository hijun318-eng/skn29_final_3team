"""LLM provider abstraction — ABC + response model."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    """LLM 호출 결과."""

    text: str
    usage: dict[str, int] = Field(default_factory=dict)
    model_name: str = ""
    latency_ms: float = 0.0


class LLMProvider(ABC):
    """모든 LLM provider가 구현해야 할 추상 베이스 클래스."""

    @abstractmethod
    async def complete(self, prompt: str, **kwargs: object) -> LLMResponse:
        """프롬프트를 받아 텍스트 완성을 수행한다."""

    async def embed(self, text: str) -> list[float]:
        """텍스트 임베딩 (필요 시 구현). 기본적으로 NotImplementedError."""
        raise NotImplementedError("이 provider는 임베딩을 지원하지 않습니다.")
