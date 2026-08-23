"""Phase 2B acceptance 도구의 mutation boundary를 회귀 검증한다."""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infrastructure" / "acceptance"))

from phase2b_datahub_candidate import (  # noqa: E402
    AcceptanceError,
    _local_https_origin,
    _runner_result,
    _validate_boundary,
)


def _args(**overrides: object) -> Namespace:
    values = {
        "source_server": "https://127.0.0.1:28081",
        "target_server": "https://127.0.0.1:38081",
        "target_project": "answervice-phase2b-datahub",
    }
    values.update(overrides)
    return Namespace(**values)


def test_acceptance_boundary_allows_only_the_approved_isolated_target() -> None:
    _validate_boundary(_args())


@pytest.mark.parametrize(
    "overrides",
    [
        {"target_project": "answervice"},
        {"target_server": "https://127.0.0.1:28081"},
        {"target_server": "https://127.0.0.1:18081"},
        {"target_server": "http://127.0.0.1:38081"},
        {"target_server": "https://datahub-gms:8443"},
    ],
)
def test_acceptance_boundary_rejects_current_or_nonisolated_targets(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(AcceptanceError):
        _validate_boundary(_args(**overrides))


def test_local_origin_rejects_credentials_paths_and_queries() -> None:
    for value in (
        "https://user:secret@127.0.0.1:38081",
        "https://127.0.0.1:38081/api",
        "https://127.0.0.1:38081?target=answervice",
    ):
        with pytest.raises(AcceptanceError):
            _local_https_origin(value, "test")


def test_runner_result_uses_only_the_final_json_object() -> None:
    assert _runner_result(b"bounded runtime log\n{\"status\":\"PASSED\"}\n") == {
        "status": "PASSED"
    }
    with pytest.raises(AcceptanceError):
        _runner_result(b"runtime log only\n")
    assert _runner_result(
        "윈도우 로그\n{\"status\":\"PASSED\"}\n".encode("cp949")
    ) == {"status": "PASSED"}
