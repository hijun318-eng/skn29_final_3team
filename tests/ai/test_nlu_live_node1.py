"""Node1 유료 평가의 저장소 고정 환경 파일 계약을 검증한다."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

from evals import nlu_live_node1


def test_live_eval_reads_only_fixed_repository_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """임의 dotenv 인자를 받지 않고 고정 경로에서만 credential을 읽는다."""

    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=fixed-secret\n", encoding="utf-8")
    monkeypatch.setattr(nlu_live_node1, "REPOSITORY_ENV", env_path)

    assert nlu_live_node1.read_secret("OPENAI_API_KEY") == "fixed-secret"
    assert tuple(inspect.signature(nlu_live_node1.run_live).parameters) == ("repeat",)


def test_live_eval_rejects_arbitrary_env_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """유료 평가 CLI는 외부 dotenv 선택 인자를 허용하지 않는다."""

    monkeypatch.setattr(
        sys,
        "argv",
        ["nlu_live_node1.py", "--dry-run", "--env-file", "outside.env"],
    )

    with pytest.raises(SystemExit) as error:
        nlu_live_node1.main()

    assert error.value.code == 2
