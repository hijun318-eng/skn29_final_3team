"""LLM gateway — provider 팩토리."""

from __future__ import annotations

from app.llm.base import LLMProvider
from app.settings import SENSEPLACE_LLM_PROVIDER


class LLMGateway:
    """환경변수 기반 provider 선택 팩토리."""

    def __init__(self, default_provider: str | None = None) -> None:
        self._default = default_provider or SENSEPLACE_LLM_PROVIDER

    def get_provider(self, provider_name: str | None = None) -> LLMProvider:
        """provider_name에 대응하는 LLMProvider 인스턴스를 반환한다."""
        name = provider_name or self._default

        if name == "stub":
            from app.llm.stub_provider import StubProvider

            return StubProvider()

        raise NotImplementedError(
            f"provider '{name}'는 아직 구현되지 않았습니다. "
            f"현재 사용 가능한 provider: stub"
        )
