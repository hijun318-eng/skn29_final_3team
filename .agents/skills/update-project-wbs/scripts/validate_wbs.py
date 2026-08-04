#!/usr/bin/env python3
"""Validate the execution WBS and its synchronized summary views."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


REQUIRED_HEADINGS = [
    "## 🗓️ 8주 핵심 개발 일정",
    "## 📈 Mermaid 일정 가시화",
    "## 📊 단계별 요약",
    "## 실행 WBS",
    "## 📦 산출물 제출 일정",
]
STATUSES = {"대기", "진행", "검토", "차단", "완료", "취소"}


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def section(lines: list[str], prefix: str) -> list[str]:
    start = next((i for i, line in enumerate(lines) if line.startswith(prefix)), None)
    if start is None:
        return []
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].startswith("## ") and not lines[i].startswith("### ")
        ),
        len(lines),
    )
    return lines[start:end]


def valid_mmdd(value: str) -> bool:
    try:
        datetime.strptime(f"2026/{value}", "%Y/%m/%d")
    except ValueError:
        return False
    return True


def summary_counts(lines: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in section(lines, "## 📊 단계별 요약"):
        row = cells(line) if line.startswith("|") else []
        if len(row) == 3 and row[1].isdigit():
            result[row[0]] = int(row[1])
    return result


def execution_tasks(
    lines: list[str],
) -> tuple[list[tuple[str, str, str, str]], dict[str, int]]:
    tasks: list[tuple[str, str, str, str]] = []
    phases: dict[str, int] = {}
    phase = ""
    for line in section(lines, "## 🗂️ 전체 태스크"):
        if line.startswith("### "):
            phase = line[4:].strip()
            phases.setdefault(phase, 0)
            continue
        row = cells(line) if line.startswith("|") else []
        if len(row) != 8 or not re.fullmatch(r"\d+\.\d+★?", row[0]):
            continue
        task_id = row[0].removesuffix("★")
        tasks.append((task_id, row[4], row[5], row[6]))
        phases[phase] = phases.get(phase, 0) + 1
    return tasks, phases


def deliverable_ids(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in section(lines, "## 📦 산출물 제출 일정"):
        row = cells(line) if line.startswith("|") else []
        if len(row) == 7 and re.fullmatch(r"\d+\.\d+", row[4]):
            result.append(row[4])
    return result


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    display = path.as_posix()

    for heading in REQUIRED_HEADINGS:
        if not any(line.startswith(heading) for line in lines):
            errors.append(f"{display}: 필수 절이 없습니다: {heading}")

    tasks, phase_counts = execution_tasks(lines)
    task_ids = [task[0] for task in tasks]
    if not tasks:
        errors.append(f"{display}: 실행 WBS 태스크를 찾을 수 없습니다.")
        return errors
    duplicates = sorted({task_id for task_id in task_ids if task_ids.count(task_id) > 1})
    if duplicates:
        errors.append(f"{display}: 중복 실행 WBS ID: {', '.join(duplicates)}")

    for task_id, status, start, end in tasks:
        if status not in STATUSES:
            errors.append(f"{display}: {task_id}의 현황이 허용값이 아닙니다: {status}")
        if not valid_mmdd(start) or not valid_mmdd(end) or start > end:
            errors.append(f"{display}: {task_id}의 시작·마감일이 유효하지 않습니다.")

    declared = re.search(r"전체 태스크 \((\d+)개", text)
    if not declared or int(declared.group(1)) != len(tasks):
        errors.append(f"{display}: 전체 태스크 제목의 개수와 실제 {len(tasks)}개가 다릅니다.")
    banner = re.search(r"실행 일정 (\d+)개 태스크", text)
    if not banner or int(banner.group(1)) != len(tasks):
        errors.append(f"{display}: 상단 실행 일정 개수와 실제 {len(tasks)}개가 다릅니다.")

    summaries = summary_counts(lines)
    if summaries != phase_counts:
        errors.append(f"{display}: 단계별 요약과 실행 WBS 단계별 개수가 다릅니다.")
    if sum(summaries.values()) != len(tasks):
        errors.append(f"{display}: 단계별 요약 합계와 전체 태스크 수가 다릅니다.")

    missing = sorted(set(deliverable_ids(lines)) - set(task_ids))
    if missing:
        errors.append(f"{display}: 산출물 일정이 없는 WBS ID를 참조합니다: {', '.join(missing)}")
    if "dateFormat  YYYY-MM-DD" not in text:
        errors.append(f"{display}: Mermaid Gantt의 dateFormat이 올바르지 않습니다.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if not args.path.exists():
        parser.error(f"파일이 없습니다: {args.path}")
    errors = validate(args.path)
    if errors:
        for error in errors:
            print(f"[wbs-validation] {error}", file=sys.stderr)
        return 1
    print("[wbs-validation] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
