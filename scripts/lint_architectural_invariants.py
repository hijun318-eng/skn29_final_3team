#!/usr/bin/env python3
"""Answervice 프로덕션 소스의 금지 아키텍처 패턴을 정적으로 검사한다."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "app" / "backend" / "app",
    REPOSITORY_ROOT / "app" / "frontend" / "src",
    REPOSITORY_ROOT / "infrastructure" / "database",
    REPOSITORY_ROOT / "scripts",
    REPOSITORY_ROOT / "src" / "ai",
    REPOSITORY_ROOT / "src" / "data",
    REPOSITORY_ROOT / "src" / "modelops",
    REPOSITORY_ROOT / "src" / "report",
)
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".css"}
EXCLUDED_PARTS = {"migrations", "node_modules", "dist", "__pycache__"}
SUSPICIOUS_CONTAINER_NAME = re.compile(
    r"(?:^|_)(?:HINTS?|KEYWORDS?|TRANSLATIONS?)(?:_|$)", re.IGNORECASE
)
QUESTION_NAMES = {"query", "question", "normalized_question", "utterance"}
SQL_NAMES = {"sql", "statement", "bound_sql", "normalized_sql"}
REGEX_SQL_METHODS = {"search", "match", "fullmatch", "findall", "finditer"}


@dataclass(frozen=True)
class Violation:
    """검사 실패 위치와 헌법 조항을 보존한다."""

    path: Path
    line: int
    ban: str
    message: str

    def render(self) -> str:
        """위반 위치를 repository-relative CI 진단 문자열로 직렬화한다."""

        try:
            display = self.path.relative_to(REPOSITORY_ROOT)
        except ValueError:
            display = self.path
        return f"{display}:{self.line}: [{self.ban}] {self.message}"


def _expression_names(node: ast.AST) -> set[str]:
    return {
        child.id.lower()
        for child in ast.walk(node)
        if isinstance(child, ast.Name)
    } | {
        child.attr.lower()
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute)
    }


def _assigned_names(node: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.append(child.id)
        elif isinstance(child, ast.Attribute):
            names.append(child.attr)
    return tuple(names)


def _call_name(node: ast.Call) -> tuple[str | None, str | None]:
    if isinstance(node.func, ast.Name):
        return None, node.func.id
    if isinstance(node.func, ast.Attribute):
        owner = node.func.value.id if isinstance(node.func.value, ast.Name) else None
        return owner, node.func.attr
    return None, None


class ArchitecturalInvariantVisitor(ast.NodeVisitor):
    """Python AST에서 질문·SQL·I/O 관련 금지 패턴을 찾는다."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.violations: list[Violation] = []
        self._fixed_sql_lines: set[int] = set()

    def _add(self, node: ast.AST, ban: str, message: str) -> None:
        self.violations.append(
            Violation(self.path, getattr(node, "lineno", 1), ban, message)
        )

    def visit_Import(self, node: ast.Import) -> None:
        """동기 urllib 모듈을 직접 import하는 BAN-05 위반을 수집한다."""

        if any(alias.name == "urllib.request" for alias in node.names):
            self._add(node, "BAN-05", "urllib.request 대신 비동기 HTTP client를 사용하세요.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """urllib.request symbol import를 놓치지 않고 BAN-05로 차단한다."""

        if node.module == "urllib.request":
            self._add(node, "BAN-05", "urllib.request 대신 비동기 HTTP client를 사용하세요.")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """일반 대입의 질문 연결용 정적 컨테이너 이름을 검사한다."""

        self._check_container_assignment(node, node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """타입 표기 대입도 일반 대입과 같은 정적 컨테이너 정책으로 검사한다."""

        if node.value is not None:
            self._check_container_assignment(node, (node.target,), node.value)
        self.generic_visit(node)

    def _check_container_assignment(
        self,
        node: ast.AST,
        targets: Iterable[ast.AST],
        value: ast.AST,
    ) -> None:
        if not isinstance(value, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
            return
        for target in targets:
            for name in _assigned_names(target):
                if SUSPICIOUS_CONTAINER_NAME.search(name):
                    self._add(
                        node,
                        "BAN-02",
                        f"질문 연결용 정적 컨테이너 {name!r} 대신 DataHub metadata를 조회하세요.",
                    )

    def visit_Compare(self, node: ast.Compare) -> None:
        """질문 원문과 문자열 literal을 포함 비교하는 분기를 탐지한다."""

        operands = (node.left, *node.comparators)
        names = set().union(*(_expression_names(item) for item in operands))
        has_literal = any(
            isinstance(item, ast.Constant) and isinstance(item.value, str)
            for item in operands
        )
        if (
            has_literal
            and names & QUESTION_NAMES
            and any(isinstance(operator, (ast.In, ast.NotIn)) for operator in node.ops)
        ):
            self._add(
                node,
                "BAN-02",
                "질문 문자열 포함 여부로 분기하지 말고 typed intent와 metadata resolver를 사용하세요.",
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """urlopen과 SQL 대상 정규식 호출을 각각 BAN-05·BAN-04로 분류한다."""

        owner, method = _call_name(node)
        if method == "urlopen":
            self._add(node, "BAN-05", "urlopen 호출은 허용되지 않습니다.")
        if (
            owner == "re"
            and method in REGEX_SQL_METHODS
            and any(_expression_names(argument) & SQL_NAMES for argument in node.args)
        ):
            self._add(
                node,
                "BAN-04",
                "SQL 검증에 정규식을 사용하지 말고 sqlglot AST를 순회하세요.",
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """동기 함수 안에 조각으로 숨긴 고정 다중 JOIN SQL을 검사한다."""

        self._check_fixed_sql_fragments(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """비동기 함수도 동일한 고정 SQL 생성 금지 정책으로 검사한다."""

        self._check_fixed_sql_fragments(node)
        self.generic_visit(node)

    def _check_fixed_sql_fragments(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        text = " ".join(
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        )
        self._flag_fixed_sql(node, text)

    def visit_Constant(self, node: ast.Constant) -> None:
        """모듈 상수로 선언된 장문 SQL template을 생성 경로에서 탐지한다."""

        if not isinstance(node.value, str) or len(node.value) < 400:
            return
        self._flag_fixed_sql(node, node.value)

    def _is_generation_path(self) -> bool:
        return (
            "src/ai" in self.path.as_posix()
            or self.path.name in {"contract_model.py", "governed_data_platform.py"}
        )

    def _flag_fixed_sql(self, node: ast.AST, text: str) -> None:
        normalized = " ".join(text.upper().split())
        line = getattr(node, "lineno", 1)
        if (
            self._is_generation_path()
            and "SELECT " in normalized
            and normalized.count(" JOIN ") >= 2
            and line not in self._fixed_sql_lines
        ):
            self._fixed_sql_lines.add(line)
            self._add(
                node,
                "BAN-03",
                "다중 테이블 고정 SQL 문자열 대신 승인 Schema Context에서 SQL을 합성하세요.",
            )


def _is_source_file(path: Path) -> bool:
    try:
        resolved = path.resolve()
        resolved.relative_to(REPOSITORY_ROOT)
    except (OSError, ValueError):
        return False
    return (
        resolved.suffix.lower() in SOURCE_SUFFIXES
        and not EXCLUDED_PARTS.intersection(resolved.parts)
        and any(resolved.is_relative_to(root) for root in SOURCE_ROOTS)
    )


def _all_source_files() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for root in SOURCE_ROOTS
            if root.exists()
            for path in root.rglob("*")
            if path.is_file() and _is_source_file(path)
        )
    )


def _staged_source_files() -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return tuple(
        path
        for name in result.stdout.splitlines()
        if (path := REPOSITORY_ROOT / name).is_file() and _is_source_file(path)
    )


def inspect_file(path: Path) -> tuple[Violation, ...]:
    """한 소스 파일의 Python AST 위반을 반환한다."""

    text = path.read_text(encoding="utf-8")
    violations: list[Violation] = []
    if path.suffix == ".py":
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as error:
            violations.append(
                Violation(path, error.lineno or 1, "SYNTAX", error.msg)
            )
        else:
            visitor = ArchitecturalInvariantVisitor(path)
            visitor.visit(tree)
            violations.extend(visitor.violations)
    return tuple(violations)


def main(argv: list[str] | None = None) -> int:
    """전체 소스 또는 staged 소스를 검사하고 commit 친화적 종료 코드를 반환한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Git index의 추가·수정된 프로덕션 소스만 검사합니다.",
    )
    args = parser.parse_args(argv)
    paths = _staged_source_files() if args.staged else _all_source_files()
    violations = [item for path in paths for item in inspect_file(path)]
    if violations:
        print("[ERROR] ARCHITECTURAL INVARIANT VIOLATIONS")
        for violation in sorted(
            violations, key=lambda item: (str(item.path), item.line, item.ban)
        ):
            print(f"  - {violation.render()}")
        return 1
    print(f"Architectural invariants passed ({len(paths)} source files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
