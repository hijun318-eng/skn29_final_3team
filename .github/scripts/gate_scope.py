import argparse
import fnmatch
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


LEDGER = Path("docs/markdown/collaboration/Gate_실행_카드_원장.md")
HANDOFFS = Path("handoffs")
REPORTS = {
    "junhee": "docs/markdown/daily_reports/junhee/일일보고.md",
    "seung": "docs/markdown/daily_reports/seung/일일보고.md",
    "daesung": "docs/markdown/daily_reports/daesung/일일보고.md",
    "jaehong": "docs/markdown/daily_reports/jaehong/일일보고.md",
    "minji": "docs/markdown/daily_reports/minji/일일보고.md",
}
SHARED_NON_PRODUCT_PATHS = (
    ".agents/skills/update-project-reports/**",
    "docs/markdown/daily_reports/README.md",
    "docs/markdown/daily_reports/team_summaries/**",
    "tests/integration/test_report_validation.py",
)
ROLES = {
    "junhee": "R1",
    "seung": "R2",
    "daesung": "R3",
    "jaehong": "R4",
    "minji": "R5",
}
TERMINAL_STATUSES = {"MERGED_DEV", "VERIFIED_GATE"}
TEST_STATUSES = {"PASS", "FAIL", "NOT_RUN", "BLOCKED", "REVIEW_REQUIRED"}
REQUIRED_HANDOFF_FIELDS = {
    "EXECUTION_BUNDLE_ID": str,
    "ROLE": str,
    "BRANCH": str,
    "BASE_SHA": str,
    "RESULT_SHA": str,
    "COMPLETED_CARDS": list,
    "CHANGED_FILES": list,
    "CONTRACT_VERSIONS": dict,
    "TEST_RESULTS": list,
    "NOT_RUN": list,
    "CHANGE_REQUESTS": list,
    "RESIDUAL_RISKS": list,
    "EXTERNAL_APPROVAL_REQUIRED": list,
}


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
    active = [
        bundle for bundle in candidates
        if bundle["STATUS"] not in TERMINAL_STATUSES
    ]
    return (active or candidates)[-1] if candidates else None


def allowed_paths(bundle: dict[str, str], branch: str) -> list[str]:
    report = REPORTS[branch]
    if bundle["STATUS"] in TERMINAL_STATUSES:
        return [report, *SHARED_NON_PRODUCT_PATHS]
    return [
        *(part.strip() for part in bundle["ALLOWED_PATHS"].split(";")),
        report,
        *SHARED_NON_PRODUCT_PATHS,
        str(manifest_path(bundle)).replace("\\", "/"),
    ]


def path_allowed(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def changed_paths(base: str, head: str, mode: str) -> list[str]:
    separator = "..." if mode == "merge-base" else ".."
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "-z",
            "--diff-filter=ACMR",
            f"{base}{separator}{head}",
        ],
        check=True,
        capture_output=True,
    )
    return [
        path.decode("utf-8")
        for path in result.stdout.split(b"\0")
        if path
    ]


def manifest_path(bundle: dict[str, str]) -> Path:
    return HANDOFFS / f"{bundle['EXECUTION_BUNDLE_ID']}.json"


def git_sha(ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def result_sha_matches_checked_head(
    manifest_sha: str,
    checked_head: str,
    output_path: str,
    role_changed_paths: list[str],
) -> bool:
    if manifest_sha == checked_head:
        return True
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest_sha, checked_head],
        check=False,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        return False
    changed_after_result = changed_paths(manifest_sha, checked_head, "direct")
    role_changes_after_result = [
        path for path in changed_after_result if path in role_changed_paths
    ]
    return role_changes_after_result == [output_path]


def handoff_template(
    bundle: dict[str, str],
    branch: str,
    result_sha: str,
    changed: list[str],
) -> dict[str, Any]:
    output_path = str(manifest_path(bundle)).replace("\\", "/")
    return {
        "EXECUTION_BUNDLE_ID": bundle["EXECUTION_BUNDLE_ID"],
        "ROLE": ROLES[branch],
        "BRANCH": branch,
        "BASE_SHA": bundle["BASE_SHA"],
        "RESULT_SHA": result_sha,
        "COMPLETED_CARDS": [],
        "CHANGED_FILES": [path for path in changed if path != output_path],
        "CONTRACT_VERSIONS": {},
        "TEST_RESULTS": [{"name": "필수 검증 결과 입력", "status": "NOT_RUN"}],
        "NOT_RUN": ["실제 미실행 검증을 입력하고 이 안내 문구를 삭제하세요."],
        "CHANGE_REQUESTS": [],
        "RESIDUAL_RISKS": [],
        "EXTERNAL_APPROVAL_REQUIRED": [],
    }


def validate_handoff(
    handoff: Any,
    bundle: dict[str, str],
    branch: str,
    changed: list[str] | None = None,
    result_sha: str | None = None,
) -> tuple[list[str], list[str]]:
    errors = []
    reviews = []
    if not isinstance(handoff, dict):
        return ["manifest root must be an object"], reviews

    for field, field_type in REQUIRED_HANDOFF_FIELDS.items():
        if field not in handoff:
            errors.append(f"missing field: {field}")
        elif not isinstance(handoff[field], field_type):
            errors.append(f"{field} must be {field_type.__name__}")
    if errors:
        return errors, reviews

    expected = {
        "EXECUTION_BUNDLE_ID": bundle["EXECUTION_BUNDLE_ID"],
        "ROLE": ROLES[branch],
        "BRANCH": branch,
        "BASE_SHA": bundle["BASE_SHA"],
    }
    for field, value in expected.items():
        if handoff[field] != value:
            errors.append(f"{field} must be {value}")

    valid_result_sha = bool(re.fullmatch(r"[0-9a-f]{40}", handoff["RESULT_SHA"]))
    if not valid_result_sha:
        errors.append("RESULT_SHA must be a 40-character lowercase git SHA")
    if not handoff["COMPLETED_CARDS"]:
        errors.append("COMPLETED_CARDS must not be empty")
    if not handoff["TEST_RESULTS"]:
        errors.append("TEST_RESULTS must not be empty")

    for result in handoff["TEST_RESULTS"]:
        if (
            not isinstance(result, dict)
            or not {"name", "status"} <= result.keys()
            or not isinstance(result["name"], str)
            or not isinstance(result["status"], str)
        ):
            errors.append("each TEST_RESULTS item needs name and status")
            continue
        if result["status"] not in TEST_STATUSES:
            errors.append(f"unsupported test status: {result['status']}")
        elif result["status"] in {"FAIL", "BLOCKED"}:
            errors.append(f"test {result['name']} is {result['status']}")
        elif result["status"] in {"NOT_RUN", "REVIEW_REQUIRED"}:
            reviews.append(f"test {result['name']} is {result['status']}")

    for field in ("COMPLETED_CARDS", "CHANGED_FILES", "NOT_RUN",
                  "CHANGE_REQUESTS", "RESIDUAL_RISKS",
                  "EXTERNAL_APPROVAL_REQUIRED"):
        if not all(isinstance(value, str) and value.strip() for value in handoff[field]):
            errors.append(f"{field} entries must be non-empty strings")

    if changed is not None:
        output_path = str(manifest_path(bundle)).replace("\\", "/")
        expected_paths = sorted(path for path in changed if path != output_path)
        if sorted(handoff["CHANGED_FILES"]) != expected_paths:
            errors.append("CHANGED_FILES does not match the git diff")
    if (
        result_sha is not None
        and valid_result_sha
        and not result_sha_matches_checked_head(
            handoff["RESULT_SHA"],
            result_sha,
            str(manifest_path(bundle)).replace("\\", "/"),
            changed or [],
        )
    ):
        errors.append(
            "RESULT_SHA must match the checked git head or precede only "
            "its handoff manifest in the role diff"
        )

    if handoff["NOT_RUN"]:
        reviews.append("Not Run verification exists")
    if handoff["CHANGE_REQUESTS"]:
        reviews.append("change request exists")
    if handoff["RESIDUAL_RISKS"]:
        reviews.append("residual risk exists")
    if handoff["EXTERNAL_APPROVAL_REQUIRED"]:
        reviews.append("external approval is required")
    return errors, reviews


def handoff_status(
    bundle: dict[str, str],
    branch: str,
    changed: list[str] | None = None,
    result_sha: str | None = None,
) -> tuple[str, list[str]]:
    if bundle["STATUS"] in TERMINAL_STATUSES:
        return "N/A", []
    path = manifest_path(bundle)
    if not path.exists():
        if bundle["STATUS"] == "REVIEW":
            return "FAIL", [f"required manifest is missing: {path}"]
        return "NOT_RUN", [f"manifest not submitted: {path}"]
    try:
        handoff = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return "FAIL", [f"cannot read manifest: {error}"]
    errors, reviews = validate_handoff(
        handoff,
        bundle,
        branch,
        changed,
        result_sha,
    )
    if errors:
        return "FAIL", errors
    if reviews:
        return "REVIEW_REQUIRED", reviews
    return "PASS", []


def next_gate_lines(text: str, target_gate: str) -> list[str]:
    match = re.fullmatch(r"I([1-5])", target_gate)
    if not match or match.group(1) == "1":
        raise ValueError("next gate must be I2 through I5")
    previous_gate = f"I{int(match.group(1)) - 1}"
    parsed = bundles(text)
    blockers = []
    for branch, role in ROLES.items():
        bundle = current_bundle(text, branch)
        if (
            bundle
            and bundle.get("TARGET_INTEGRATION_GATE") == previous_gate
            and bundle["STATUS"] not in TERMINAL_STATUSES
        ):
            blockers.append(
                f"{role} {bundle['EXECUTION_BUNDLE_ID']}={bundle['STATUS']}"
            )
    verified = any(
        bundle.get("TARGET_INTEGRATION_GATE") == previous_gate
        and bundle["STATUS"] == "VERIFIED_GATE"
        for bundle in parsed
    )
    candidates = [
        bundle["EXECUTION_BUNDLE_ID"]
        for bundle in parsed
        if bundle.get("TARGET_INTEGRATION_GATE") == target_gate
        and bundle["STATUS"] == "PLANNED"
        and re.fullmatch(r"R[1-5]-W\d+(?:-[A-Z0-9]+)?", bundle["EXECUTION_BUNDLE_ID"])
    ]
    ready = not blockers and verified
    lines = [
        f"## {target_gate} issue readiness",
        f"- Previous gate: `{previous_gate}`",
        f"- Latest dev SHA: `{git_sha('HEAD')}`",
        f"- Result: `{'READY_TO_ISSUE' if ready else 'BLOCKED'}`",
    ]
    if blockers:
        lines.extend(f"- Blocker: {blocker}" for blocker in blockers)
    if not verified:
        lines.append(f"- Blocker: `{previous_gate}` has no VERIFIED_GATE bundle")
    if candidates:
        lines.append(f"- Planned candidates: {', '.join(candidates)}")
    lines.append("- READY publication remains an R1 manual decision.")
    return lines


def dashboard_lines(text: str) -> list[str]:
    lines = [
        "## R1 Gate dashboard",
        "| Role | Bundle | Status | Handoff | R1 action |",
        "|---|---|---|---|---|",
    ]
    for branch, role in ROLES.items():
        bundle = current_bundle(text, branch)
        if bundle is None:
            lines.append(f"| {role} | - | PLANNED | NOT_RUN | Issue bundle |")
            continue
        handoff = handoff_status(bundle, branch)[0]
        if bundle["STATUS"] == "REVIEW":
            action = "Review submission"
        elif bundle["STATUS"] == "BLOCKED":
            action = "Resolve blocker"
        elif handoff == "REVIEW_REQUIRED":
            action = "Review exception"
        elif bundle["STATUS"] in TERMINAL_STATUSES:
            action = "No action"
        else:
            action = "Wait for submission"
        lines.append(
            f"| {role} | {bundle['EXECUTION_BUNDLE_ID']} | "
            f"{bundle['STATUS']} | {handoff} | {action} |"
        )
    return lines


def write_summary(lines: list[str]) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")


def write_outputs(**values: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--mode", choices=("direct", "merge-base"))
    parser.add_argument("--write-handoff", action="store_true")
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--next-gate", choices=("I2", "I3", "I4", "I5"))
    args = parser.parse_args()

    text = LEDGER.read_text(encoding="utf-8")
    if args.dashboard:
        lines = dashboard_lines(text)
        if args.next_gate:
            lines.extend(["", *next_gate_lines(text, args.next_gate)])
        write_summary(lines)
        print("\n".join(lines))
        return 0

    missing = [
        name
        for name in ("branch", "base", "head", "mode")
        if getattr(args, name) is None
    ]
    if missing:
        parser.error(f"required arguments: {', '.join('--' + name for name in missing)}")
    if args.branch != "dev" and args.branch not in REPORTS:
        parser.error(f"unsupported role branch: {args.branch}")

    changed = changed_paths(args.base, args.head, args.mode)
    if args.branch == "dev":
        lines = [
            "## Role Gate scope",
            "- Branch: `dev`",
            f"- Changed paths: {len(changed)}",
            "- Result: `PASS` - integration branch, role scope enforcement skipped",
        ]
        write_summary(lines)
        write_outputs(scope="PASS", handoff="N/A")
        print("\n".join(lines))
        return 0

    bundle = current_bundle(text, args.branch)
    if bundle is None:
        raise SystemExit(f"No executable bundle found for branch: {args.branch}")

    if args.write_handoff:
        path = manifest_path(bundle)
        if path.exists():
            raise SystemExit(f"Refusing to overwrite existing manifest: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                handoff_template(bundle, args.branch, git_sha(args.head), changed),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Created draft handoff: {path}")
        return 0

    patterns = allowed_paths(bundle, args.branch)
    violations = [path for path in changed if not path_allowed(path, patterns)]
    handoff, handoff_notes = handoff_status(
        bundle,
        args.branch,
        changed,
        git_sha(args.head),
    )
    result = "FAIL" if violations or handoff == "FAIL" else "PASS"
    lines = [
        "## Role Gate scope",
        f"- Branch: `{args.branch}`",
        f"- Bundle: `{bundle['EXECUTION_BUNDLE_ID']}`",
        f"- Status: `{bundle['STATUS']}`",
        f"- Changed paths: {len(changed)}",
        f"- Result: `{result}`",
        f"- Handoff: `{handoff}`",
    ]
    if violations:
        lines.extend(["", "### Paths outside ALLOWED_PATHS"])
        lines.extend(f"- `{path}`" for path in violations)
    if handoff_notes:
        lines.extend(["", "### Handoff notes"])
        lines.extend(f"- {note}" for note in handoff_notes)
    write_summary(lines)
    write_outputs(scope=result, handoff=handoff)
    print("\n".join(lines))
    return int(result == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
