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
        encoding="utf-8",
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout.strip())


def identity(inventory: list[dict[str, object]]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-RuntimeInventoryJson",
            json.dumps(inventory),
            "-EnvFilePath",
            str(ROOT / ".env.example"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def identity_with_env(env_path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "pwsh", "-NoProfile", "-File", str(SCRIPT),
            "-RuntimeInventoryJson", "[]", "-EnvFilePath", env_path,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


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
    assert "answervice.testEnvFile" in source
    assert 'env_file="$(git rev-parse --show-toplevel)/.env"' in source
    assert '-EnvFilePath "$env_file"' in source


def test_external_env_and_runtime_conflicts_fail_closed_without_secret_output():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "IsPathFullyQualified" in source
    assert "test env path must be a regular file" in source
    assert "required env variable names are missing" in source
    assert "Get-Content -LiteralPath" in source
    assert "docker ps -aq --filter" in source
    assert "fixed container name conflict" in source
    assert "docker ps -q --filter" in source
    assert "fixed port conflict" in source
    for invalid in (".env.example", str(ROOT / "missing.env")):
        completed = identity_with_env(invalid)
        assert completed.returncode != 0
        assert "APP_ADMIN_PASSWORD" not in completed.stderr


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh is required")
def test_runtime_identity_requires_one_checkout_config_and_env():
    assert 'throw "runtime identity mismatch: service=$service label=$($entry.Key)' in SCRIPT.read_text(
        encoding="utf-8"
    )
    expected = {
        "com.docker.compose.project": "answervice",
        "com.docker.compose.project.working_dir": str(ROOT),
        "com.docker.compose.project.config_files": str(ROOT / "compose.yml"),
        "com.docker.compose.project.environment_file": str(ROOT / ".env.example"),
    }
    inventory = [
        {"service": service, "labels": expected}
        for service in ("app-postgres", "backend", "frontend")
    ]
    assert identity(inventory).returncode == 0

    for label in (
        "com.docker.compose.project.working_dir",
        "com.docker.compose.project.config_files",
        "com.docker.compose.project.environment_file",
    ):
        mismatched = json.loads(json.dumps(inventory))
        mismatched[1]["labels"][label] = str(ROOT / ".wt" / "other")
        completed = identity(mismatched)
        assert completed.returncode != 0

    missing = json.loads(json.dumps(inventory))
    del missing[1]["labels"]["com.docker.compose.project.working_dir"]
    assert identity(missing).returncode != 0

    duplicate = inventory + [inventory[0]]
    assert identity(duplicate).returncode != 0
