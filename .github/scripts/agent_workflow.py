import argparse
import json
import shutil
import subprocess
from pathlib import Path

import gate_scope


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False
        )
    except FileNotFoundError as error:
        raise RuntimeError("git tool is not available") from error
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result


def is_ancestor(ancestor: str, descendant: str) -> bool:
    result = git("merge-base", "--is-ancestor", ancestor, descendant, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "git merge-base failed")
    return result.returncode == 0


def run(branch: str, ff_only_dev: bool = False) -> dict[str, object]:
    errors: list[str] = []
    if shutil.which("git") is None:
        return {"result": "FAIL", "action": "none", "errors": ["git tool is not available"]}
    if branch not in gate_scope.REPORTS:
        return {"result": "FAIL", "action": "none", "errors": [f"unsupported personal branch: {branch}"]}

    try:
        root = git("rev-parse", "--show-toplevel").stdout.strip()
        current_branch = git("branch", "--show-current").stdout.strip()
        dirty = bool(git("status", "--porcelain").stdout.strip())
        ledger = Path(root) / gate_scope.LEDGER
        text = ledger.read_text(encoding="utf-8")
        git("rev-parse", "--verify", "origin/dev")

        behind = is_ancestor("HEAD", "origin/dev")
        dev_is_ancestor = is_ancestor("origin/dev", "HEAD")
        action = "none"
        if (
            ff_only_dev
            and current_branch == branch
            and not dirty
            and behind
            and not dev_is_ancestor
        ):
            git("merge", "--ff-only", "origin/dev")
            action = "fast-forwarded"
            payload = gate_scope.preflight_payload(
                ledger.read_text(encoding="utf-8"),
                branch,
                git("branch", "--show-current").stdout.strip(),
                root,
                bool(git("status", "--porcelain").stdout.strip()),
                [],
            )
        else:
            payload = gate_scope.preflight_payload(
                text, branch, current_branch, root, dirty, []
            )
        errors.extend(payload["errors"])
        if not behind and not dev_is_ancestor:
            errors.append("personal branch and origin/dev have diverged")
        elif (
            action == "none"
            and current_branch == branch
            and not dirty
            and behind
            and not dev_is_ancestor
        ):
            action = "fast-forward-available"

        return {
            **payload,
            "result": "FAIL" if errors else "PASS",
            "action": action,
            "errors": errors,
        }
    except (OSError, RuntimeError) as error:
        return {"result": "FAIL", "action": "none", "errors": [str(error)]}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose a personal branch and optionally fast-forward it to origin/dev."
    )
    parser.add_argument("--branch", required=True)
    parser.add_argument("--ff-only-dev", action="store_true")
    args = parser.parse_args()
    payload = run(args.branch, args.ff_only_dev)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return int(payload["result"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
