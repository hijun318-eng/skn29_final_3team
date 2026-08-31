"""선택 RAG·ML 기능의 flag와 실제 runtime readiness 교집합을 제공한다."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import math
import os
from time import monotonic

from app.authorization import has_capability
from app.contracts import Capability, Role, RuntimeFeature
from app.runtime_features import runtime_feature_enabled
from app.services.ml_prediction_service import MLPredictionService
from app.services.rag_gateway import InternalManualAgent


FeatureProbe = Callable[[Role | None], Awaitable[str]]


class RuntimeFeatureAvailability:
    """느린 외부 probe를 bounded TTL cache로 감싸 session/UI 경계를 fail-closed한다."""

    def __init__(
        self,
        *,
        rag_probe: FeatureProbe | None = None,
        ml_probe: FeatureProbe | None = None,
    ) -> None:
        self._probes = {
            RuntimeFeature.INTERNAL_GUIDELINE: rag_probe or self._rag_probe,
            RuntimeFeature.ML_PREDICTION: ml_probe or self._ml_probe,
        }
        self._cache: dict[tuple[RuntimeFeature, Role | None], tuple[float, str]] = {}
        self._locks: dict[tuple[RuntimeFeature, Role | None], asyncio.Lock] = {}

    @staticmethod
    def _probe_timeout() -> float:
        try:
            value = float(os.getenv("OPTIONAL_RUNTIME_PROBE_TIMEOUT_SECONDS", "2"))
        except ValueError:
            return 2.0
        if not math.isfinite(value):
            return 2.0
        return min(10.0, max(0.1, value))

    @staticmethod
    def _cache_ttl() -> float:
        try:
            value = float(os.getenv("OPTIONAL_RUNTIME_READINESS_TTL_SECONDS", "15"))
        except ValueError:
            return 15.0
        if not math.isfinite(value):
            return 15.0
        return min(60.0, max(1.0, value))

    async def check(self, role: Role | None = None) -> dict[str, str]:
        """비활성 기능은 not_required, 활성 기능은 실제 receipt 기준으로 반환한다."""

        entries = tuple(self._probes)
        states = await asyncio.gather(
            *(self._status(feature, role) for feature in entries)
        )
        return {
            (
                "rag_runtime"
                if feature is RuntimeFeature.INTERNAL_GUIDELINE
                else "ml_runtime"
            ): state
            for feature, state in zip(entries, states, strict=True)
        }

    async def available_features(
        self,
        role: Role,
    ) -> tuple[RuntimeFeature, ...]:
        """UI/session에는 flag가 켜지고 runtime이 ready인 기능만 노출한다."""

        if not has_capability(role, Capability.RUN_ANALYSIS):
            return ()
        states = await self.check(role)
        available = []
        if states["rag_runtime"] == "ready":
            available.append(RuntimeFeature.INTERNAL_GUIDELINE)
        if states["ml_runtime"] == "ready":
            available.append(RuntimeFeature.ML_PREDICTION)
        return tuple(available)

    async def _status(self, feature: RuntimeFeature, role: Role | None) -> str:
        cache_role = (
            role
            if feature is RuntimeFeature.INTERNAL_GUIDELINE
            else None
        )
        cache_key = (feature, cache_role)
        if not runtime_feature_enabled(feature):
            self._cache.pop(cache_key, None)
            return "not_required"
        now = monotonic()
        cached = self._cache.get(cache_key)
        if cached is not None and now < cached[0]:
            return cached[1]
        lock = self._locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            now = monotonic()
            cached = self._cache.get(cache_key)
            if cached is not None and now < cached[0]:
                return cached[1]
            try:
                async with asyncio.timeout(self._probe_timeout()):
                    state = await self._probes[feature](cache_role)
            except Exception:
                state = "not_ready"
            if state not in {"ready", "not_ready"}:
                state = "not_ready"
            self._cache[cache_key] = (now + self._cache_ttl(), state)
            return state

    @staticmethod
    async def _rag_probe(role: Role | None) -> str:
        database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "").strip()
        if not database_url:
            return "not_ready"
        effective_role = role or Role.ANALYST
        await InternalManualAgent(database_url).runtime_receipt(effective_role.value)
        return "ready"

    @staticmethod
    async def _ml_probe(_role: Role | None) -> str:
        readiness = await MLPredictionService().readiness()
        return readiness.status


runtime_feature_availability = RuntimeFeatureAvailability()


async def available_runtime_features(role: Role) -> tuple[RuntimeFeature, ...]:
    """인증 session과 프론트가 공유할 실제 사용 가능 기능 목록을 반환한다."""

    return await runtime_feature_availability.available_features(role)
