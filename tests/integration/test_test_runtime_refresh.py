import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "refresh_test_runtime.ps1"
HOOK = ROOT / ".githooks" / "post-merge"


def plan(*paths: str) -> tuple[int, dict[str, object]]:
    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-PlanOnly",
            "-ChangedPathsJson",
            json.dumps(paths),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout.strip())


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh is required")
@pytest.mark.parametrize(
    ("paths", "action", "services", "code"),
    [
        (("app/enterprise-react/src/App.jsx",), "refresh", ["frontend"], 0),
        (("app/backend/app/main.py",), "refresh", ["backend"], 0),
        (("src/ai/node.py", "app/enterprise-react/src/App.jsx"), "refresh", ["backend", "frontend"], 0),
        (("docs/markdown/README.md", "tests/backend/test_api.py"), "no-op", [], 0),
        (("compose.yml",), "manual-review", [], 2),
        (("infrastructure/database/compose.yml",), "manual-review", [], 2),
    ],
)
def test_refresh_plan_is_exact_and_stateful_changes_fail_closed(paths, action, services, code):
    returncode, payload = plan(*paths)
    assert returncode == code
    assert payload["action"] == action
    assert payload["services"] == services


def test_post_merge_hook_is_test_only_and_opt_in():
    source = HOOK.read_text(encoding="utf-8")
    assert '[ "$branch" = test ] || exit 0' in source
    assert "answervice.testAutoRefresh" in source
    assert "refresh_test_runtime.ps1" in source
