"""LLM gateway — provider 팩토리.

지원 provider:
- stub: 결정론적 mock (기본값, LLM 불필요)
- ollama: 로컬 Ollama 서버 (http://localhost:11434)
- openai: OpenAI 호환 API (OpenAI, RunPod vLLM, 로컬 vLLM)
"""

from __future__ import annotations

from app.llm.base import LLMProvider
from app.settings import SENSEPLACE_LLM_PROVIDER

# 등록된 provider 목록
_AVAILABLE_PROVIDERS = ["stub", "ollama", "openai"]


class LLMGateway:
    """환경변수 기반 provider 선택 팩토리.

    SENSEPLACE_LLM_PROVIDER 환경변수로 기본 provider를 선택한다.
    런타임에 get_provider("ollama")로 다른 provider를 선택할 수 있다.
    """

    def __init__(self, default_provider: str | None = None) -> None:
        self._default = default_provider or SENSEPLACE_LLM_PROVIDER

    def get_provider(self, provider_name: str | None = None) -> LLMProvider:
        """provider_name에 대응하는 LLMProvider 인스턴스를 반환한다.

        Args:
            provider_name: "stub", "ollama", "openai" 중 하나.
                           None이면 기본 provider 사용.

        Returns:
            LLMProvider 인스턴스
        """
        name = provider_name or self._default

        if name == "stub":
            from app.llm.stub_provider import StubProvider
            return StubProvider()

        if name == "ollama":
            from app.llm.ollama_provider import OllamaProvider
            return OllamaProvider()

        if name in ("openai", "vllm"):
            from app.llm.openai_provider import OpenAIProvider
            return OpenAIProvider()

        raise NotImplementedError(
            f"provider '{name}'는 지원되지 않습니다. "
            f"사용 가능한 provider: {', '.join(_AVAILABLE_PROVIDERS)}"
        )

    def list_providers(self) -> list[str]:
        """사용 가능한 provider 목록을 반환한다."""
        return list(_AVAILABLE_PROVIDERS)
