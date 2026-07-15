#!/usr/bin/env python3
"""Validate this repository's commit subject convention."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ALLOWED_TYPES = (
    "feat", "fix", "docs", "refactor", "test", "chore", "build",
    "ci", "perf", "style", "data", "eval",
)
SUBJECT_PATTERN = re.compile(
    rf"^({'|'.join(ALLOWED_TYPES)})(\([a-z0-9][a-z0-9._/-]*\))?!?: .+$"
)
EXEMPT_PREFIXES = ("Merge ", "Revert ", "fixup! ", "squash! ")


def validate(subject: str) -> list[str]:
    errors: list[str] = []
    if subject.startswith(EXEMPT_PREFIXES):
        return errors
    if len(subject) > 72:
        errors.append(f"subject is {len(subject)} characters; maximum is 72")
    if not SUBJECT_PATTERN.fullmatch(subject):
        errors.append("expected <type>(<scope>): <summary> with an allowed lowercase type")
    if subject.endswith("."):
        errors.append("subject must not end with a period")
    if subject != subject.strip():
        errors.append("subject must not have leading or trailing whitespace")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("message_file", nargs="?", type=Path)
    source.add_argument("--message")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.message is not None:
        subject = args.message.splitlines()[0] if args.message else ""
    else:
        try:
            subject = args.message_file.read_text(encoding="utf-8-sig").splitlines()[0]
        except (OSError, IndexError) as exc:
            print(f"commit-msg: cannot read subject: {exc}", file=sys.stderr)
            return 1

    errors = validate(subject)
    if not errors:
        return 0

    print("Invalid commit message:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    print("See docs/engineering/COMMIT_CONVENTION.md", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
