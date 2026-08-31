"""서버가 활성화한 선택 기능을 하나의 fail-closed 환경 계약으로 판정한다."""

from __future__ import annotations

import os

from app.contracts import RuntimeFeature


_FEATURE_ENVIRONMENT = {
    RuntimeFeature.INTERNAL_GUIDELINE: "RAG_FEATURE_ENABLED",
    RuntimeFeature.ML_PREDICTION: "ML_FEATURE_ENABLED",
}
_ENABLED_VALUES = frozenset({"1", "true", "yes"})
_SUPERVISOR_FEATURE_ENVIRONMENT = "SUPERVISOR_FEATURE_ENABLED"


def runtime_feature_enabled(feature: RuntimeFeature) -> bool:
    """명시적으로 활성화된 기능만 true로 판정하며 누락·오타는 비활성으로 닫는다."""

    value = os.getenv(_FEATURE_ENVIRONMENT[feature], "").strip().lower()
    return value in _ENABLED_VALUES


def enabled_runtime_features() -> tuple[RuntimeFeature, ...]:
    """현재 서버에서 활성화된 선택 기능을 안정적인 enum 순서로 반환한다."""

    return tuple(feature for feature in RuntimeFeature if runtime_feature_enabled(feature))


def supervisor_feature_enabled() -> bool:
    """명시적 opt-in에서만 외부 Supervisor 계획과 capability route를 연다."""

    value = os.getenv(_SUPERVISOR_FEATURE_ENVIRONMENT, "").strip().lower()
    return value in _ENABLED_VALUES
