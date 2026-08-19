"""serving SQL에서 승인 전 runtime governance Markdown을 생성하거나 drift를 검사한다."""

from __future__ import annotations

import argparse
from pathlib import Path

from runtime_governance_draft import build_draft, render_markdown


def main() -> int:
    """명시된 SQL directory와 schema만 읽어 DRAFT 파일을 생성하거나 비교한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sql-directory", type=Path, required=True)
    parser.add_argument("--serving-schema", required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    rendered = render_markdown(
        build_draft(
            arguments.sql_directory,
            arguments.serving_schema,
            arguments.release_version,
        )
    )
    if arguments.check:
        if not arguments.output.is_file() or arguments.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit("RUNTIME_GOVERNANCE_DRAFT_DRIFT")
        print("RUNTIME_GOVERNANCE_DRAFT_VERIFIED")
        return 0
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"RUNTIME_GOVERNANCE_DRAFT_WRITTEN={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
