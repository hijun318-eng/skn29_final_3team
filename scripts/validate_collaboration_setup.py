#!/usr/bin/env python3
"""Validate the stack-neutral collaboration environment."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


REQUIRED_PATHS = (
    Path("README.md"),
    Path("AGENTS.md"),
    Path("CONTRIBUTING.md"),
    Path(".env.example"),
    Path(".agents/skills/draft-commit-message/SKILL.md"),
    Path(".claude/README.md"),
    Path(".claude/skills/draft-commit-message/SKILL.md"),
    Path(".github/CODEOWNERS"),
    Path(".github/ISSUE_TEMPLATE/bug.yml"),
    Path(".github/ISSUE_TEMPLATE/data_eval.yml"),
    Path(".github/ISSUE_TEMPLATE/feature.yml"),
    Path(".github/PULL_REQUEST_TEMPLATE.md"),
    Path(".github/workflows/collaboration-guard.yml"),
    Path("docs/engineering/TEAM_DEVELOPMENT_SETUP_GUIDE.md"),
    Path("docs/engineering/PROJECT_OWNER_SETUP_GUIDE.md"),
    Path("docs/engineering/GIT_BRANCH_STRATEGY.md"),
    Path("docs/engineering/PROJECT_STRUCTURE.md"),
    Path("docs/engineering/QUALITY_EVALUATION_GUIDE.md"),
    Path("evals/registry.json"),
    Path("data/raw/.gitkeep"),
    Path("data/processed/.gitkeep"),
    Path("data/samples/.gitkeep"),
    Path("notebooks/.gitkeep"),
    Path("src/.gitkeep"),
    Path("app/.gitkeep"),
    Path("tests/.gitkeep"),
    Path("submission/.gitkeep"),
    Path("requirements.txt"),
    Path("scripts/bootstrap-new-project.ps1"),
    Path("scripts/create-branch-structure.ps1"),
)
IGNORE_PROBES = (
    ".agents/skills/draft-commit-message/SKILL.md",
    ".claude/skills/draft-commit-message/SKILL.md",
    ".env.example",
    "data/raw/.gitkeep",
    "data/processed/.gitkeep",
    "data/samples/.gitkeep",
    "docs/engineering/TEAM_DEVELOPMENT_SETUP_GUIDE.md",
    "notebooks/.gitkeep",
    "src/.gitkeep",
    "app/.gitkeep",
    "tests/.gitkeep",
    "submission/.gitkeep",
    "evals/testsets/.gitkeep",
    "evals/baselines/.gitkeep",
    "evals/reports/.gitkeep",
)
FEATURE_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
REQUIRED_FEATURE_KEYS = {
    "feature_id",
    "owner",
    "testset_version",
    "baseline_version",
    "metrics",
    "status",
    "latest_report",
}


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def is_sensitive_or_generated(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    if name.endswith((".pem", ".key")):
        return True
    blocked_prefixes = (
        "data/raw/",
        "data/interim/",
        "data/processed/",
        "data/mart/",
        "data/ground_truth/",
        "reports/generated/",
        "evals/runs/",
    )
    if normalized.endswith("/.gitkeep"):
        return False
    return normalized.startswith(blocked_prefixes)


def validate_registry(errors: list[str]) -> None:
    try:
        registry = json.loads(Path("evals/registry.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"evals/registry.json is invalid: {exc}")
        return

    if registry.get("schema_version") != "1.0":
        errors.append("evals/registry.json schema_version must be 1.0")
    features = registry.get("features")
    if not isinstance(features, list):
        errors.append("evals/registry.json features must be a list")
        return

    seen: set[str] = set()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            errors.append(f"registry feature[{index}] must be an object")
            continue
        missing = REQUIRED_FEATURE_KEYS - feature.keys()
        if missing:
            errors.append(f"registry feature[{index}] missing: {', '.join(sorted(missing))}")
            continue
        feature_id = feature["feature_id"]
        if not isinstance(feature_id, str) or not FEATURE_ID.fullmatch(feature_id):
            errors.append(f"invalid feature_id at feature[{index}]: {feature_id}")
        elif feature_id in seen:
            errors.append(f"duplicate feature_id: {feature_id}")
        seen.add(feature_id)
        if feature["status"] not in {"planned", "active", "deprecated"}:
            errors.append(f"invalid status for {feature_id}: {feature['status']}")
        if not isinstance(feature["metrics"], list):
            errors.append(f"metrics must be a list for {feature_id}")


def main() -> int:
    errors: list[str] = []

    for path in REQUIRED_PATHS:
        if not path.is_file():
            errors.append(f"required file is missing: {path.as_posix()}")

    for probe in IGNORE_PROBES:
        result = run_git("check-ignore", "--no-index", "--quiet", probe)
        if result.returncode == 0:
            detail = run_git("check-ignore", "-v", "--no-index", probe).stdout.strip()
            errors.append(f"shared asset is ignored: {probe} ({detail})")

    tracked = run_git("ls-files")
    if tracked.returncode == 0:
        for path in tracked.stdout.splitlines():
            if is_sensitive_or_generated(path):
                errors.append(f"sensitive or generated path must not be tracked: {path}")

    validate_registry(errors)

    if errors:
        print("Collaboration setup validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Collaboration setup validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
