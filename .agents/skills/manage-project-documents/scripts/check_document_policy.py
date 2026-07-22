#!/usr/bin/env python3
"""Validate changed project documents without modifying them."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


COMMON_ROWS = ["문서 설명", "문서 분류", "버전", "문서 기준일", "작성·수정"]
NUMBERED_ROWS = ["산출물 번호", "제출 일자", "대응 템플릿"]
CLASSIFICATIONS = {"산출물 작업본", "일반 문서"}


def git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return Path(result.stdout.strip()).resolve()


def normalize(root: Path, value: str) -> tuple[Path, str]:
    path = Path(value)
    absolute = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        relative = absolute.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"저장소 밖 경로입니다: {value}") from exc
    return absolute, relative


def table_rows(lines: list[str], start: int) -> tuple[list[str], dict[str, str]]:
    order: list[str] = []
    values: dict[str, str] = {}
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            break
        order.append(cells[0])
        values[cells[0]] = cells[1]
    return order, values


def validate_markdown(root: Path, path: Path, relative: str) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("# "):
        return [f"{relative}: 첫 줄에 최상위 제목(`# `)이 필요합니다."]

    index = 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index + 1 >= len(lines) or lines[index].strip() != "| 항목 | 내용 |":
        return [f"{relative}: 제목 바로 아래에 메타데이터 표가 필요합니다."]
    if not re.fullmatch(r"\|\s*:?-{3,}:?\s*\|\s*:?-{3,}:?\s*\|", lines[index + 1].strip()):
        errors.append(f"{relative}: 메타데이터 표 구분 행이 올바르지 않습니다.")

    order, values = table_rows(lines, index)
    if order[: len(COMMON_ROWS)] != COMMON_ROWS:
        errors.append(f"{relative}: 공통 헤더 행과 순서가 올바르지 않습니다.")
    if values.get("문서 분류") not in CLASSIFICATIONS:
        errors.append(f"{relative}: 문서 분류가 허용값이 아닙니다.")
    if not re.fullmatch(r"v\d+\.\d+|—", values.get("버전", "")):
        errors.append(f"{relative}: 버전은 vX.Y 또는 — 형식이어야 합니다.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", values.get("문서 기준일", "")):
        errors.append(f"{relative}: 문서 기준일은 YYYY-MM-DD HH:MM 형식이어야 합니다.")
    if values.get("작성·수정", "").strip() in {"", "—"}:
        errors.append(f"{relative}: 작성·수정에 실제 편집자 이름이 필요합니다.")

    match = re.match(r"^(\d{2})_", path.name)
    if match:
        missing = [row for row in NUMBERED_ROWS if row not in values]
        if missing:
            errors.append(f"{relative}: 번호 문서 헤더 누락: {', '.join(missing)}")
        if values.get("산출물 번호") != match.group(1):
            errors.append(f"{relative}: 산출물 번호가 파일명과 다릅니다.")
    if "## 변경 내역" not in text:
        errors.append(f"{relative}: 하단 `## 변경 내역`이 필요합니다.")

    for target in re.findall(r"\[[^\]]+\]\((?!https?://|#)([^)]+)\)", text):
        cleaned = target.strip().strip("<>").split("#", 1)[0]
        if cleaned and not (path.parent / cleaned).resolve().exists():
            errors.append(f"{relative}: 깨진 로컬 링크: {target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", help="검사할 저장소 상대 또는 절대 경로")
    args = parser.parse_args()
    root = git_root()
    errors: list[str] = []

    for value in args.paths:
        try:
            path, relative = normalize(root, value)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if relative in {"docs/markdown/final_project", "docs/templates"} or relative.startswith(
            ("docs/markdown/final_project/", "docs/templates/")
        ):
            errors.append(f"{relative}: 읽기 전용 보호 경로입니다.")
            continue
        if not path.exists():
            errors.append(f"{relative}: 파일이 없습니다.")
            continue
        if path.is_dir():
            errors.append(f"{relative}: 파일 경로를 지정해야 합니다.")
            continue
        if path.suffix.lower() != ".md" or not relative.startswith("docs/"):
            continue
        if relative == "docs/문서관리규칙.md" or relative.startswith("docs/markdown/daily_reports/"):
            continue
        errors.extend(validate_markdown(root, path, relative))

    if errors:
        for error in errors:
            print(f"[document-policy] {error}", file=sys.stderr)
        return 1
    print(f"[document-policy] OK: {len(args.paths)} path(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
