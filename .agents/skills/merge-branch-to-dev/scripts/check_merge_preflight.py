#!/usr/bin/env python3
"""Read-only preflight checks for a guarded personal-branch-to-dev merge."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

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
LEDGER = Path("docs/markdown/collaboration/Gate_실행_카드_원장.md")
TERMINAL_STATUSES = {"MERGED_DEV", "VERIFIED_GATE"}


def git(*args: str, check: bool = True, cwd: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
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


def is_ancestor(ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
    )
    return result.returncode == 0


def source_ci(branch: str, sha: str) -> dict[str, object]:
    try:
        result = subprocess.run(
            [
                "gh", "run", "list", "--workflow", "CI", "--branch", branch,
                "--commit", sha, "--event", "push", "--limit", "1",
                "--json", "databaseId,status,conclusion,url",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError:
        return {"status": "unavailable", "error": "gh command를 찾을 수 없습니다."}
    if result.returncode != 0:
        return {
            "status": "unavailable",
            "error": result.stderr.strip() or "GitHub Actions 조회에 실패했습니다.",
        }
    try:
        runs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "unavailable", "error": "GitHub Actions 응답이 JSON이 아닙니다."}
    if not runs:
        return {"status": "missing", "error": "source SHA의 CI 실행이 없습니다."}
    return runs[0]


def worktree_roots() -> dict[str, str]:
    roots = {}
    for block in git("worktree", "list", "--porcelain").split("\n\n"):
        values = dict(
            line.split(" ", 1) for line in block.splitlines() if " " in line
        )
        branch = values.get("branch", "").removeprefix("refs/heads/")
        if branch:
            roots[branch] = values["worktree"]
    return roots


def current_bundle_status(branch: str) -> str | None:
    if not LEDGER.exists():
        return None
    matches = []
    for block in re.findall(
        r"```text\n(.*?)```", LEDGER.read_text(encoding="utf-8"), re.DOTALL
    ):
        values = dict(
            line.split("=", 1) for line in block.splitlines() if "=" in line
        )
        if values.get("PERSONAL_BRANCH") == branch and values.get("STATUS") != "PLANNED":
            matches.append(values.get("STATUS"))
    return matches[-1] if matches else None


def batch_payload(sources: list[str]) -> dict[str, object]:
    current = git("branch", "--show-current")
    status = git("status", "--porcelain")
    errors = []
    if current != "dev":
        errors.append("batch 단계의 현재 branch가 dev가 아닙니다.")
    if status:
        errors.append("dev working tree가 깨끗하지 않습니다.")
    dev_local = ref("dev")
    dev_remote = ref("origin/dev")
    if not dev_local or dev_local != dev_remote:
        errors.append("dev와 origin/dev가 정확히 같지 않습니다.")
    roots = worktree_roots()
    items = []
    for source in sources:
        local = ref(source)
        remote = ref(f"origin/{source}")
        root = roots.get(source)
        ci = source_ci(source, remote) if remote else None
        item_errors = []
        if not local or local != remote:
            item_errors.append("local과 origin commit이 다르거나 없습니다.")
        if not root:
            item_errors.append("개인 branch worktree를 찾을 수 없습니다.")
        elif git("status", "--porcelain", cwd=root):
            item_errors.append("개인 branch working tree가 깨끗하지 않습니다.")
        if not ci or ci.get("status") != "completed" or ci.get("conclusion") != "success":
            item_errors.append("source SHA의 CI가 성공하지 않았습니다.")
        items.append(
            {"source": source, "root": root, "sha": remote, "source_ci": ci, "errors": item_errors}
        )
        errors.extend(f"{source}: {error}" for error in item_errors)
    return {
        "phase": "batch",
        "current_branch": current,
        "dev_local": dev_local,
        "dev_remote": dev_remote,
        "sources": items,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=sorted(PERSONAL_BRANCHES))
    parser.add_argument("--sources", nargs="+", choices=sorted(PERSONAL_BRANCHES))
    parser.add_argument("--phase", required=True, choices=["source", "dev", "final", "batch"])
    parser.add_argument("--base", help="병합 직전 dev commit; final 단계에서 필수")
    args = parser.parse_args()

    if args.phase == "batch":
        if not args.sources or args.source:
            parser.error("batch 단계에는 --sources만 사용합니다.")
        payload = batch_payload(args.sources)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return int(bool(payload["errors"]))
    if not args.source or args.sources:
        parser.error("source/dev/final 단계에는 --source 하나가 필요합니다.")

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
    ci: dict[str, object] | None = None
    if not source_local or not source_remote:
        errors.append("source local/remote ref를 모두 확인할 수 없습니다.")
    elif source_local != source_remote:
        errors.append("source local과 origin commit이 다릅니다.")

    dev_local = ref("dev")
    dev_remote = ref("origin/dev")
    if args.phase == "source" and current != args.source:
        errors.append(f"source 단계의 현재 branch가 {args.source}가 아닙니다.")
    if args.phase == "source" and source_remote:
        ci = source_ci(args.source, source_remote)
        if ci.get("status") != "completed" or ci.get("conclusion") != "success":
            errors.append(
                "source SHA의 CI가 성공하지 않았습니다: "
                f"status={ci.get('status')}, conclusion={ci.get('conclusion')}"
            )
    if args.phase == "dev":
        if current != "dev":
            errors.append("dev 단계의 현재 branch가 dev가 아닙니다.")
        if not dev_local or not dev_remote:
            errors.append("dev local/remote ref를 모두 확인할 수 없습니다.")
        elif dev_local != dev_remote:
            errors.append("병합 전 dev와 origin/dev가 정확히 같지 않습니다.")
        elif source_remote and is_ancestor(source_remote, dev_local):
            errors.append("source branch가 이미 dev에 반영되어 있습니다.")
    if args.phase == "final":
        if current != "dev":
            errors.append("final 단계의 현재 branch가 dev가 아닙니다.")
        base_ref = ref(args.base) if args.base else None
        if not args.base or not base_ref:
            errors.append("final 단계에는 유효한 --base commit이 필요합니다.")
        elif not dev_remote or dev_remote != base_ref:
            errors.append("origin/dev가 병합 직전 base에서 변경되었습니다.")
        elif not dev_local or not is_ancestor(base_ref, dev_local):
            errors.append("병합 직전 base가 local dev의 ancestor가 아닙니다.")
        if source_remote and dev_local and not is_ancestor(source_remote, dev_local):
            errors.append("source branch가 local dev에 반영되지 않았습니다.")
        bundle_status = current_bundle_status(args.source)
        if bundle_status not in TERMINAL_STATUSES:
            errors.append(
                "source 실행 카드가 MERGED_DEV 또는 VERIFIED_GATE가 아닙니다: "
                f"{bundle_status or 'missing'}"
            )

    payload = {
        "phase": args.phase,
        "source": args.source,
        "base": args.base,
        "current_branch": current,
        "source_local": source_local,
        "source_remote": source_remote,
        "dev_local": dev_local,
        "dev_remote": dev_remote,
        "clean": not status,
        "operations": operations,
        "source_ci": ci,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
