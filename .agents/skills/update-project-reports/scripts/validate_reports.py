#!/usr/bin/env python3
"""Validate personal, date-summary, and weekly Markdown reports."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


MEMBERS = {
    "박준희": "junhee",
    "송민지": "minji",
    "김재홍": "jaehong",
    "정승": "seung",
    "윤대성": "daesung",
}
GIT_HISTORY = re.compile(
    r"\b(?:git\s+)?(?:fetch|pull|push|checkout|switch)\b"
    r"|\bgit\s+merge\b"
    r"|\bmerge(?:d)?\s+(?:origin(?:/[\w.-]+)?|dev|main|junhee|minji|seung|daesung|jaehong|branch)\b"
    r"|\b(?:origin(?:/[\w.-]+)?|dev|main|junhee|minji|seung|daesung|jaehong|branch)\s+merge(?:d)?\b"
    r"|\bcommit(?:\s+hash|\s+[0-9a-f]{7,40})\b"
    r"|(?:브랜치|branch)\s*(?:최신화|동기화)"
    r"|(?:브랜치|branch|dev|main|origin(?:/[\w.-]+)?)\s*(?:병합|머지|푸시)"
    r"|(?:병합|머지|푸시|커밋)\s*(?:완료|진행|반영|이력|해시)"
    r"|(?:커밋|commit)\s*(?:해시|hash)?\s*[0-9a-f]{7,40}",
    re.IGNORECASE,
)


def newest_daily_block(lines: list[str]) -> tuple[str | None, int, str]:
    starts = [i for i, line in enumerate(lines) if re.fullmatch(r"## \d{8}", line)]
    if not starts:
        return None, 0, ""
    start = starts[0]
    end = next((i for i in starts[1:] if i > start), len(lines))
    return lines[start][3:], end - start, "\n".join(lines[start:end])


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    display = path.as_posix()
    history_scope = text
    if re.search(r"^(<<<<<<<|=======|>>>>>>>)", text, re.MULTILINE):
        errors.append(f"{display}: merge conflict 표식이 있습니다.")

    if path.name == "일일보고.md":
        date, count, history_scope = newest_daily_block(lines)
        if not date:
            errors.append(f"{display}: YYYYMMDD 날짜 블록이 없습니다.")
        elif count > 5:
            errors.append(f"{display}: 최신 {date} 블록이 {count}줄로 5줄을 초과합니다.")
    elif re.fullmatch(r"\d{8}\.md", path.name):
        for name, branch in MEMBERS.items():
            pattern = rf"^\| {re.escape(name)} \| `{branch}` \| .+ \|$"
            if not re.search(pattern, text, re.MULTILINE):
                errors.append(f"{display}: {name}({branch}) 행이 없거나 형식이 다릅니다.")
    elif path.name == "주간보고.md":
        if len(lines) > 40:
            errors.append(f"{display}: {len(lines)}줄로 40줄을 초과합니다.")
        if not re.search(r"^## \d{8} ~ \d{8} \(\d+주차\)$", text, re.MULTILINE):
            errors.append(f"{display}: 주간보고 기간 제목 형식이 올바르지 않습니다.")
        if "작성자: 3팀" not in text:
            errors.append(f"{display}: 기본 작성자 `3팀` 표기가 없습니다.")
    else:
        errors.append(f"{display}: 지원하는 보고 파일이 아닙니다.")
    if GIT_HISTORY.search(history_scope):
        errors.append(f"{display}: Git 운영 이력이 포함되어 있습니다.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    errors: list[str] = []
    for path in args.paths:
        if not path.exists():
            errors.append(f"{path}: 파일이 없습니다.")
        else:
            errors.extend(validate(path))
    if errors:
        for error in errors:
            print(f"[report-validation] {error}", file=sys.stderr)
        return 1
    print(f"[report-validation] OK: {len(args.paths)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
