from __future__ import annotations

import asyncio

from infrastructure.acceptance import phase4_runtime_catalog_projection as phase4


def test_windows_entrypoint_uses_selector_event_loop(monkeypatch) -> None:
    observed: dict[str, object] = {}

    async def fake_run(_args):
        observed["loop"] = asyncio.get_running_loop()
        return {"status": "PASS"}

    monkeypatch.setattr(phase4, "run", fake_run)
    monkeypatch.setattr(phase4.sys, "platform", "win32")

    result = phase4._run_acceptance(object())

    assert result == {"status": "PASS"}
    assert isinstance(observed["loop"], asyncio.SelectorEventLoop)
