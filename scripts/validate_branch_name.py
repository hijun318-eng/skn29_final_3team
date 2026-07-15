#!/usr/bin/env python3
"""Validate the fixed seven-branch team workflow."""

from __future__ import annotations

import argparse


ALLOWED_BRANCHES = {
    "main",
    "dev",
    "junhee",
    "minji",
    "seung",
    "daesung",
    "jaehong",
}


def is_valid(branch: str) -> bool:
    return branch in ALLOWED_BRANCHES


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", required=True)
    args = parser.parse_args()

    if is_valid(args.branch):
        return 0

    print(f"Invalid branch name: {args.branch}")
    print("Allowed branches: main, dev, junhee, minji, seung, daesung, jaehong")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
