"""선택 기능 공개와 실제 실행 경계가 같은 서버 feature flag를 사용함을 검증한다."""

from __future__ import annotations

import pytest

from app.contracts import RuntimeFeature
from app.runtime_features import (
    enabled_runtime_features,
    runtime_feature_enabled,
    supervisor_feature_enabled,
)


def test_runtime_features_are_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_FEATURE_ENABLED", raising=False)
    monkeypatch.delenv("ML_FEATURE_ENABLED", raising=False)

    assert enabled_runtime_features() == ()


def test_runtime_features_require_explicit_truthy_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_FEATURE_ENABLED", "true")
    monkeypatch.setenv("ML_FEATURE_ENABLED", "1")

    assert enabled_runtime_features() == (
        RuntimeFeature.INTERNAL_GUIDELINE,
        RuntimeFeature.ML_PREDICTION,
    )
    assert runtime_feature_enabled(RuntimeFeature.INTERNAL_GUIDELINE) is True
    assert runtime_feature_enabled(RuntimeFeature.ML_PREDICTION) is True


def test_runtime_features_fail_closed_on_unapproved_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_FEATURE_ENABLED", "enabled")
    monkeypatch.setenv("ML_FEATURE_ENABLED", "on")

    assert enabled_runtime_features() == ()


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_supervisor_feature_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("SUPERVISOR_FEATURE_ENABLED", value)

    assert supervisor_feature_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "on", "enabled", "truthy"])
def test_supervisor_feature_fails_closed_on_other_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("SUPERVISOR_FEATURE_ENABLED", value)

    assert supervisor_feature_enabled() is False
