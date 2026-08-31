from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import app.api.analysis_router_runtime as analysis_router_runtime
import app.api.router as router_module
from app.context import ContextValidationError
from app.contracts import ErrorCode
from app.ports.data_platform import MetadataUnavailableError


def test_create_conversation_maps_release_failure_to_retryable_dependency_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """활성 release 확인 실패는 원문 500 대신 안전한 typed 503으로 닫는다."""

    class UnavailableConversationOrchestrator:
        async def create_conversation(self, _context: object, _title: str) -> dict[str, object]:
            raise MetadataUnavailableError("private upstream detail")

    monkeypatch.setattr(router_module, "_controller", lambda: object())
    monkeypatch.setattr(
        analysis_router_runtime,
        "conversation_orchestrator",
        lambda _controller: UnavailableConversationOrchestrator(),
    )

    with pytest.raises(ContextValidationError) as captured:
        asyncio.run(
            router_module.create_conversation({}, SimpleNamespace())  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 503
    assert captured.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert "private upstream detail" not in captured.value.message
