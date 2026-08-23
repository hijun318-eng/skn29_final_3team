from __future__ import annotations

import asyncio

from infrastructure.acceptance import phase5_node1_grounding as phase5


def test_windows_entrypoint_uses_selector_event_loop(monkeypatch) -> None:
    observed: dict[str, object] = {}

    async def fake_run(_args):
        observed["loop"] = asyncio.get_running_loop()
        return {"status": "PASS"}

    monkeypatch.setattr(phase5, "run", fake_run)
    monkeypatch.setattr(phase5.sys, "platform", "win32")

    result = phase5._run_acceptance(object())

    assert result == {"status": "PASS"}
    assert isinstance(observed["loop"], asyncio.SelectorEventLoop)


def test_sealed_gold_has_non_lowerable_gate() -> None:
    gold = phase5._gold(phase5.GOLD_FILE)

    assert gold["thresholds"]["min_joint_slot_exact_match"] == 1.0
    assert len(gold["cases"]) == 5
