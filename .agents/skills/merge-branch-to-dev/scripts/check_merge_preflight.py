#!/usr/bin/env python3
"""Read-only preflight checks for a guarded personal-branch-to-dev merge."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


PERSONAL_BRANCHES = {"junhee", "minji", "seung", "daesung", "jaehong"}
OPERATION_MARKERS = {
    "MERGE_HEAD": "merge",
    "REBASE_HEAD": "rebase",
    "CHERRY_PICK_HEAD": "cherry-pick",
    "REVERT_HEAD": "revert",
    "BISECT_HEAD": "bisect",
    "BISECT_START": "bisect",
}


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def ref(name: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", name],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, choices=sorted(PERSONAL_BRANCHES))
    parser.add_argument("--phase", required=True, choices=["source", "dev"])
    args = parser.parse_args()

    errors: list[str] = []
    current = git("branch", "--show-current")
    status = git("status", "--porcelain")
    if status:
        errors.append("working tree가 깨끗하지 않습니다.")
    operations = sorted({label for marker, label in OPERATION_MARKERS.items() if ref(marker)})
    if operations:
        errors.append(f"진행 중인 Git 작업이 있습니다: {', '.join(operations)}")

    source_local = ref(args.source)
    source_remote = ref(f"origin/{args.source}")
    if not source_local or not source_remote:
        errors.append("source local/remote ref를 모두 확인할 수 없습니다.")
    elif source_local != source_remote:
        errors.append("source local과 origin commit이 다릅니다.")

    dev_local = ref("dev")
    dev_remote = ref("origin/dev")
    if args.phase == "source" and current != args.source:
        errors.append(f"source 단계의 현재 branch가 {args.source}가 아닙니다.")
    if args.phase == "dev":
        if current != "dev":
            errors.append("dev 단계의 현재 branch가 dev가 아닙니다.")
        if not dev_local or not dev_remote:
            errors.append("dev local/remote ref를 모두 확인할 수 없습니다.")
        elif dev_local != dev_remote:
            errors.append("병합 전 dev와 origin/dev가 정확히 같지 않습니다.")

    payload = {
        "phase": args.phase,
        "source": args.source,
        "current_branch": current,
        "source_local": source_local,
        "source_remote": source_remote,
        "dev_local": dev_local,
        "dev_remote": dev_remote,
        "clean": not status,
        "operations": operations,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
