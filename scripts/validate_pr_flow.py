#!/usr/bin/env python3
"""Validate pull-request flow for fixed personal, dev, and main branches."""

from __future__ import annotations

import argparse


PERSONAL_BRANCHES = {"junhee", "minji", "seung", "daesung", "jaehong"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    args = parser.parse_args()

    if args.head in PERSONAL_BRANCHES and args.base == "dev":
        return 0
    if args.head == "dev" and args.base == "main":
        return 0

    print(f"Disallowed PR flow: {args.head} -> {args.base}")
    print("Allowed flows: personal branch -> dev, dev -> main")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
