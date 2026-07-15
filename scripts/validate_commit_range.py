#!/usr/bin/env python3
"""Validate every commit subject in a Git revision range."""

from __future__ import annotations

import argparse
import subprocess

from validate_commit_message import validate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()

    result = subprocess.run(
        ["git", "log", "--format=%H%x09%s", f"{args.base}..{args.head}"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        print(result.stderr.strip() or "Failed to read the commit range.")
        return 1

    rows = [line for line in result.stdout.splitlines() if line.strip()]
    if not rows:
        print("No commits found in the pull-request range.")
        return 1

    invalid = False
    for row in rows:
        commit_hash, subject = row.split("\t", 1)
        errors = validate(subject)
        if errors:
            invalid = True
            print(f"{commit_hash[:12]} {subject}")
            for error in errors:
                print(f"  - {error}")

    if invalid:
        print("See docs/engineering/COMMIT_CONVENTION.md")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
