#!/usr/bin/env python3
"""Validate personal, date-summary, and weekly Markdown reports."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
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


def valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def daily_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    starts = [i for i, line in enumerate(lines) if re.fullmatch(r"## \d{8}", line)]
    blocks: list[tuple[str, list[str]]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        block = lines[start:end]
        while block and not block[-1].strip():
            block.pop()
        blocks.append((lines[start][3:], block))
    return blocks


def validate(path: Path, target_date: str | None = None) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    display = path.as_posix()
    history_scope = text
    if re.search(r"^(<<<<<<<|=======|>>>>>>>)", text, re.MULTILINE):
        errors.append(f"{display}: merge conflict 표식이 있습니다.")

    if path.name == "일일보고.md":
        blocks = daily_blocks(lines)
        dates = [date for date, _ in blocks]
        if not blocks:
            errors.append(f"{display}: YYYYMMDD 날짜 블록이 없습니다.")
        else:
            invalid = [date for date in dates if not valid_date(date)]
            if invalid:
                errors.append(f"{display}: 유효하지 않은 날짜 블록: {', '.join(invalid)}")
            duplicates = sorted({date for date in dates if dates.count(date) > 1})
            if duplicates:
                errors.append(f"{display}: 중복 날짜 블록: {', '.join(duplicates)}")
            if dates != sorted(dates, reverse=True):
                errors.append(f"{display}: 날짜 블록이 최신순이 아닙니다.")
            selected_date = target_date or dates[0]
            selected = next((block for date, block in blocks if date == selected_date), None)
            if selected is None:
                errors.append(f"{display}: 검사할 날짜 블록이 없습니다: {selected_date}")
                history_scope = ""
            else:
                history_scope = "\n".join(selected)
                if len(selected) > 5:
                    errors.append(
                        f"{display}: {selected_date} 블록이 {len(selected)}줄로 5줄을 초과합니다."
                    )
    elif re.fullmatch(r"\d{8}\.md", path.name):
        if not valid_date(path.stem):
            errors.append(f"{display}: 파일명의 날짜가 유효하지 않습니다.")
        for name, branch in MEMBERS.items():
            pattern = rf"^\| {re.escape(name)} \| `{branch}` \| .+ \|$"
            count = len(re.findall(pattern, text, re.MULTILINE))
            if count != 1:
                errors.append(f"{display}: {name}({branch}) 행이 정확히 하나여야 합니다.")
    elif path.name == "주간보고.md":
        if len(lines) > 40:
            errors.append(f"{display}: {len(lines)}줄로 40줄을 초과합니다.")
        periods = re.findall(
            r"^## (\d{8}) ~ (\d{8}) \((\d+)주차\)$", text, re.MULTILINE
        )
        if len(periods) != 1:
            errors.append(f"{display}: 주간보고 기간 제목 형식이 올바르지 않습니다.")
        else:
            start, end, week = periods[0]
            if not valid_date(start) or not valid_date(end) or start > end:
                errors.append(f"{display}: 주간보고 기간이 유효하지 않습니다.")
            if path.parent.name != f"{week}주차":
                errors.append(f"{display}: 상위 폴더와 주차 제목이 다릅니다.")
        if "작성자: 3팀" not in text:
            errors.append(f"{display}: 기본 작성자 `3팀` 표기가 없습니다.")
    else:
        errors.append(f"{display}: 지원하는 보고 파일이 아닙니다.")
    if GIT_HISTORY.search(history_scope):
        errors.append(f"{display}: Git 운영 이력이 포함되어 있습니다.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="일일보고에서 검사할 YYYYMMDD 날짜 블록")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    if args.date and not valid_date(args.date):
        parser.error("--date는 유효한 YYYYMMDD 형식이어야 합니다.")
    errors: list[str] = []
    for path in args.paths:
        if not path.exists():
            errors.append(f"{path}: 파일이 없습니다.")
        else:
            errors.extend(validate(path, args.date))
    if errors:
        for error in errors:
            print(f"[report-validation] {error}", file=sys.stderr)
        return 1
    print(f"[report-validation] OK: {len(args.paths)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
