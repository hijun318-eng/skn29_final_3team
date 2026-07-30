import argparse
import fnmatch
import os
import re
import subprocess
from pathlib import Path


LEDGER = Path("docs/markdown/collaboration/Gate_실행_카드_원장.md")
REPORTS = {
    "junhee": "docs/markdown/daily_reports/junhee/일일보고.md",
    "seung": "docs/markdown/daily_reports/seung/일일보고.md",
    "daesung": "docs/markdown/daily_reports/daesung/일일보고.md",
    "jaehong": "docs/markdown/daily_reports/jaehong/일일보고.md",
    "minji": "docs/markdown/daily_reports/minji/일일보고.md",
}
TERMINAL_STATUSES = {"MERGED_DEV", "VERIFIED_GATE"}


def bundles(text: str) -> list[dict[str, str]]:
    parsed = []
    for block in re.findall(r"```text\n(.*?)```", text, re.DOTALL):
        values = {}
        for line in block.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        if {"STATUS", "PERSONAL_BRANCH", "EXECUTION_BUNDLE_ID"} <= values.keys():
            parsed.append(values)
    return parsed


def current_bundle(text: str, branch: str) -> dict[str, str] | None:
    candidates = [
        bundle
        for bundle in bundles(text)
        if bundle["PERSONAL_BRANCH"] == branch
        and bundle["STATUS"] != "PLANNED"
        and "ALLOWED_PATHS" in bundle
    ]
    return candidates[-1] if candidates else None


def allowed_paths(bundle: dict[str, str], branch: str) -> list[str]:
    report = REPORTS[branch]
    if bundle["STATUS"] in TERMINAL_STATUSES:
        return [report]
    return [
        *(part.strip() for part in bundle["ALLOWED_PATHS"].split(";")),
        report,
    ]


def path_allowed(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def changed_paths(base: str, head: str, mode: str) -> list[str]:
    separator = "..." if mode == "merge-base" else ".."
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}{separator}{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def write_summary(lines: list[str]) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--mode", choices=("direct", "merge-base"), required=True)
    args = parser.parse_args()

    changed = changed_paths(args.base, args.head, args.mode)
    if args.branch == "dev":
        write_summary([
            "## Role Gate scope",
            "- Branch: `dev`",
            f"- Changed paths: {len(changed)}",
            "- Result: `PASS` — integration branch, role scope enforcement skipped",
        ])
        return 0

    if args.branch not in REPORTS:
        raise SystemExit(f"Unsupported role branch: {args.branch}")

    bundle = current_bundle(LEDGER.read_text(encoding="utf-8"), args.branch)
    if bundle is None:
        raise SystemExit(f"No executable bundle found for branch: {args.branch}")

    patterns = allowed_paths(bundle, args.branch)
    violations = [path for path in changed if not path_allowed(path, patterns)]
    result = "PASS" if not violations else "FAIL"
    lines = [
        "## Role Gate scope",
        f"- Branch: `{args.branch}`",
        f"- Bundle: `{bundle['EXECUTION_BUNDLE_ID']}`",
        f"- Status: `{bundle['STATUS']}`",
        f"- Changed paths: {len(changed)}",
        f"- Result: `{result}`",
    ]
    if violations:
        lines.extend(["", "### Paths outside ALLOWED_PATHS"])
        lines.extend(f"- `{path}`" for path in violations)
    write_summary(lines)
    print("\n".join(lines))
    return int(bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
