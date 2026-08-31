"""선택 Agent runtime의 flag∩readiness·cache 경계를 검증한다."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.contracts import Role, RuntimeFeature
from app.services.runtime_feature_availability import RuntimeFeatureAvailability


def test_disabled_features_do_not_probe_external_runtimes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"rag": 0, "ml": 0}

    async def rag_probe(_role: Role | None) -> str:
        calls["rag"] += 1
        return "ready"

    async def ml_probe(_role: Role | None) -> str:
        calls["ml"] += 1
        return "ready"

    monkeypatch.setenv("RAG_FEATURE_ENABLED", "0")
    monkeypatch.setenv("ML_FEATURE_ENABLED", "0")
    availability = RuntimeFeatureAvailability(
        rag_probe=rag_probe,
        ml_probe=ml_probe,
    )

    states = asyncio.run(availability.check())

    assert states == {
        "rag_runtime": "not_required",
        "ml_runtime": "not_required",
    }
    assert calls == {"rag": 0, "ml": 0}


def test_session_features_are_flag_and_actual_readiness_intersection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ready(_role: Role | None) -> str:
        return "ready"

    async def unavailable(_role: Role | None) -> str:
        return "not_ready"

    monkeypatch.setenv("RAG_FEATURE_ENABLED", "1")
    monkeypatch.setenv("ML_FEATURE_ENABLED", "1")
    availability = RuntimeFeatureAvailability(
        rag_probe=ready,
        ml_probe=unavailable,
    )

    features = asyncio.run(availability.available_features(Role.ANALYST))

    assert features == (RuntimeFeature.INTERNAL_GUIDELINE,)


def test_role_without_analysis_capability_never_probes_optional_runtimes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def ready(_role: Role | None) -> str:
        nonlocal calls
        calls += 1
        return "ready"

    monkeypatch.setenv("RAG_FEATURE_ENABLED", "1")
    monkeypatch.setenv("ML_FEATURE_ENABLED", "1")
    availability = RuntimeFeatureAvailability(rag_probe=ready, ml_probe=ready)

    features = asyncio.run(availability.available_features(Role.REPORT_ADMIN))

    assert features == ()
    assert calls == 0


def test_runtime_readiness_is_cached_within_the_bounded_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def ready(_role: Role | None) -> str:
        nonlocal calls
        calls += 1
        return "ready"

    monkeypatch.setenv("RAG_FEATURE_ENABLED", "1")
    monkeypatch.setenv("ML_FEATURE_ENABLED", "0")
    monkeypatch.setenv("OPTIONAL_RUNTIME_READINESS_TTL_SECONDS", "30")
    availability = RuntimeFeatureAvailability(
        rag_probe=ready,
        ml_probe=ready,
    )

    async def concurrent_and_cached() -> None:
        states = await asyncio.gather(
            *(availability.check() for _ in range(5))
        )
        assert all(state["rag_runtime"] == "ready" for state in states)
        assert (await availability.check())["rag_runtime"] == "ready"

    asyncio.run(concurrent_and_cached())

    assert calls == 1


def test_rag_readiness_is_probed_and_cached_per_authenticated_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles: list[Role | None] = []

    async def role_probe(role: Role | None) -> str:
        roles.append(role)
        return "ready" if role is Role.ANALYST else "not_ready"

    monkeypatch.setenv("RAG_FEATURE_ENABLED", "1")
    monkeypatch.setenv("ML_FEATURE_ENABLED", "0")
    availability = RuntimeFeatureAvailability(
        rag_probe=role_probe,
        ml_probe=role_probe,
    )

    async def probe_roles() -> tuple[tuple[RuntimeFeature, ...], ...]:
        analyst, administrator = await asyncio.gather(
            availability.available_features(Role.ANALYST),
            availability.available_features(Role.PLATFORM_ADMIN),
        )
        return (
            analyst,
            administrator,
            await availability.available_features(Role.ANALYST),
        )

    features = asyncio.run(probe_roles())

    assert features == (
        (RuntimeFeature.INTERNAL_GUIDELINE,),
        (),
        (RuntimeFeature.INTERNAL_GUIDELINE,),
    )
    assert sorted(role.value for role in roles if role is not None) == [
        Role.ANALYST.value,
        Role.PLATFORM_ADMIN.value,
    ]


@pytest.mark.parametrize("failure_mode", ["timeout", "error"])
def test_probe_failure_fails_closed_without_exposing_the_feature(
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    async def failing(_role: Role | None) -> str:
        if failure_mode == "timeout":
            await asyncio.Event().wait()
            return "ready"
        raise RuntimeError("runtime unavailable")

    monkeypatch.setenv("RAG_FEATURE_ENABLED", "1")
    monkeypatch.setenv("ML_FEATURE_ENABLED", "0")
    monkeypatch.setenv("OPTIONAL_RUNTIME_PROBE_TIMEOUT_SECONDS", "0.1")
    availability = RuntimeFeatureAvailability(
        rag_probe=failing,
        ml_probe=failing,
    )

    features = asyncio.run(availability.available_features(Role.ANALYST))

    assert features == ()


def test_invalid_probe_state_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def invalid(_role: Role | None) -> str:
        return "healthy"

    monkeypatch.setenv("RAG_FEATURE_ENABLED", "1")
    monkeypatch.setenv("ML_FEATURE_ENABLED", "0")
    availability = RuntimeFeatureAvailability(
        rag_probe=invalid,
        ml_probe=invalid,
    )

    states = asyncio.run(availability.check())

    assert states["rag_runtime"] == "not_ready"
