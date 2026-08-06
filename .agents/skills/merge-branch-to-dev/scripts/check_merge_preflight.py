#!/usr/bin/env python3
"""Guarded preflight checks for a personal-branch-to-dev merge."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[4]
GATE_SCOPE_SPEC = importlib.util.spec_from_file_location(
    "gate_scope", ROOT / ".github/scripts/gate_scope.py"
)
gate_scope = importlib.util.module_from_spec(GATE_SCOPE_SPEC)
GATE_SCOPE_SPEC.loader.exec_module(gate_scope)

PERSONAL_BRANCHES = set(gate_scope.ROLES)
OPERATION_MARKERS = {
    "MERGE_HEAD": "merge",
    "REBASE_HEAD": "rebase",
    "CHERRY_PICK_HEAD": "cherry-pick",
    "REVERT_HEAD": "revert",
    "BISECT_HEAD": "bisect",
    "BISECT_START": "bisect",
}
LEDGER = gate_scope.LEDGER
TERMINAL_STATUSES = gate_scope.TERMINAL_STATUSES


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
    bundle = gate_scope.current_bundle(LEDGER.read_text(encoding="utf-8"), branch)
    return bundle["STATUS"] if bundle else None


def merge_session_path() -> Path:
    return Path(git("rev-parse", "--git-common-dir")) / "answervice-merge-session.json"


def load_session(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": 1, "sources": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("sources"), dict):
        raise ValueError("지원하지 않는 병합 session 형식입니다.")
    if data.get("base") is not None and not isinstance(data["base"], str):
        raise ValueError("병합 session의 base SHA 형식이 잘못되었습니다.")
    for saved in data["sources"].values():
        if (
            not isinstance(saved, dict)
            or not isinstance(saved.get("sha"), str)
            or not isinstance(saved.get("ci"), dict)
        ):
            raise ValueError("병합 session의 source 결과 형식이 잘못되었습니다.")
    return data


def save_session(path: Path, data: dict[str, object]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def result_fields(session: dict[str, object], source: str) -> dict[str, str] | None:
    saved = session.get("sources", {}).get(source)
    if not saved:
        return None
    ci = saved["ci"]
    return {
        "RESULT_SHA": saved["sha"],
        "RESULT_CI": f"branch {ci['databaseId']} PASS",
    }


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
    parser.add_argument("--base", help="병합 직전 dev commit; session 미사용 final에 필수")
    parser.add_argument(
        "--session",
        action="store_true",
        help="Git 공용 디렉터리의 병합 session에서 SHA와 CI 결과를 재사용",
    )
    args = parser.parse_args()

    if args.phase == "batch":
        if not args.sources or args.source:
            parser.error("batch 단계에는 --sources만 사용합니다.")
        payload = batch_payload(args.sources)
        if args.session and not payload["errors"]:
            path = merge_session_path()
            session = {
                "version": 1,
                "base": payload["dev_local"],
                "sources": {
                    item["source"]: {"sha": item["sha"], "ci": item["source_ci"]}
                    for item in payload["sources"]
                },
            }
            save_session(path, session)
            payload["session"] = str(path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return int(bool(payload["errors"]))
    if not args.source or args.sources:
        parser.error("source/dev/final 단계에는 --source 하나가 필요합니다.")

    errors: list[str] = []
    path = merge_session_path() if args.session else None
    try:
        session = load_session(path) if path else {"version": 1, "sources": {}}
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        session = {"version": 1, "sources": {}}
        errors.append(f"병합 session을 읽을 수 없습니다: {exc}")
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
        base = args.base or session.get("base")
        base_ref = ref(base) if base else None
        if not base or not base_ref:
            errors.append("final 단계에는 session 또는 유효한 --base commit이 필요합니다.")
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
        if path:
            saved = session["sources"].get(args.source)
            if not saved:
                errors.append("병합 session에 source 결과가 없습니다.")
            elif saved.get("sha") != source_remote:
                errors.append("병합 session의 source SHA가 origin과 다릅니다.")
            elif saved.get("ci", {}).get("conclusion") != "success":
                errors.append("병합 session의 source CI가 성공 상태가 아닙니다.")

    if path and not errors:
        if args.phase == "source":
            session["sources"][args.source] = {"sha": source_remote, "ci": ci}
            save_session(path, session)
        elif args.phase == "dev":
            session["base"] = dev_local
            save_session(path, session)

    payload = {
        "phase": args.phase,
        "source": args.source,
        "base": args.base or session.get("base"),
        "current_branch": current,
        "source_local": source_local,
        "source_remote": source_remote,
        "dev_local": dev_local,
        "dev_remote": dev_remote,
        "clean": not status,
        "operations": operations,
        "source_ci": ci,
        "session": str(path) if path else None,
        "result_fields": result_fields(session, args.source) if path else None,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
