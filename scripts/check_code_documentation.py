#!/usr/bin/env python3
"""프로덕션 모듈과 공개 API의 한국어 책임 문서화를 검사한다.

주석 수를 늘리는 것이 목적이 아니다. 다른 모듈이 호출하는 경계에 책임·입출력·실패
의미를 남기고, 구현을 그대로 번역한 소음성 주석은 code review에서 별도로 거절한다.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOTS = (
    REPOSITORY_ROOT / "app" / "backend" / "app",
    REPOSITORY_ROOT / "app" / "backend" / "migrations",
    REPOSITORY_ROOT / "app" / "backend" / "scripts",
    REPOSITORY_ROOT / "evals",
    REPOSITORY_ROOT / "infrastructure" / "database" / "datahub",
    REPOSITORY_ROOT / "scripts",
    REPOSITORY_ROOT / "src" / "ai",
    REPOSITORY_ROOT / "src" / "data",
    REPOSITORY_ROOT / "src" / "ml",
    REPOSITORY_ROOT / "src" / "modelops",
    REPOSITORY_ROOT / "src" / "rag",
    REPOSITORY_ROOT / "src" / "report",
)
FRONTEND_ROOTS = (
    REPOSITORY_ROOT / "app" / "frontend" / "src",
    REPOSITORY_ROOT / "app" / "frontend" / "vite.config.js",
)
EXCLUDED_PARTS = {"__pycache__", "node_modules", "dist", "releases"}
INFRASTRUCTURE_CODE_ROOTS = (
    REPOSITORY_ROOT / "app" / "backend" / "scripts",
    REPOSITORY_ROOT / "infrastructure" / "database",
    REPOSITORY_ROOT / ".githooks",
)
INFRASTRUCTURE_CODE_FILES = (
    REPOSITORY_ROOT / "compose.yml",
    REPOSITORY_ROOT / "compose.app-postgres.override.yml",
    REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml",
    REPOSITORY_ROOT / "app" / "backend" / "Dockerfile",
    REPOSITORY_ROOT / "app" / "backend" / "entrypoint.sh",
    REPOSITORY_ROOT / "app" / "backend" / "compose.fragment.yml",
    REPOSITORY_ROOT / "infrastructure" / "database" / ".env.example",
)
INFRASTRUCTURE_SUFFIXES = {".ps1", ".sh", ".sql", ".properties", ".yml", ".yaml"}
INFRASTRUCTURE_EXCLUDED_PATHS = (
    "/infrastructure/database/releases/",
    "/infrastructure/database/sql/data/",
)
# 이 revision은 외부에 배포된 byte checksum이 control-plane 계약이다. 주석을 추가하는
# 것조차 upgrade 재현성을 깨므로 원문 hash가 정확할 때만 문서화 검사에서 제외한다.
IMMUTABLE_PYTHON_SOURCES = {
    "app/backend/migrations/versions/20260730_02_application_schema.py": (
        "a468edca9b560c78afffc46876acb4d6b2ef1d6b42641d00fcc2db1c63c285ee"
    ),
}
HANGUL = re.compile(r"[가-힣]")
GENERIC_DOCUMENTATION = (
    "데이터와 불변식을 표현하는 공개 계약이다",
    "경계의 책임과 공개 연산을 제공한다",
    "입력으로 검증된 계약 객체 또는 산출물을 생성한다",
    "공개 연산을 수행하고 선언된 계약 결과를 반환한다",
    "상황을 상위 계층이 구분해 중단하거나 재시도하도록 전달하는 예외다",
    "작업을 timeout·취소·실패 계약 안에서 실행하고 typed 결과를 반환한다",
    "동작과 관련 상태를 캡슐화한다",
    "backend 기능의 입력 계약, 권한 확인, 실행 경계를 정의한다",
    "원본을 읽어 스키마와 무결성을 검증한 결과를 반환한다",
    "명령행 입력을 검증하고 작업 결과에 맞는 종료 상태를 반환한다",
    "입력 필드와 불변식을 검증해",
    "애플리케이션 흐름에서 도메인 불변식과 상태 전이의 실행 순서를 조정한다",
    "어댑터에서 외부 I/O, typed 계약 변환, 의존성 실패 매핑을 담당한다",
    "HTTP 엔드포인트의 입력 검증, 주체 권한 확인, 응답 변환을 구성한다",
    "AI 파이프라인에 필요한 typed 입력·출력 계약과 결정론적 검증 규칙을 구현한다",
    "필터 조건에 맞는",
    "정보를 소유권과 존재 여부를 확인한 뒤 조회한다",
    "상태 전이를 선행 조건과 주체 권한 확인 후 영속화한다",
    "처리를 종료하고 남은 자원과 상태를 일관되게 정리한다",
    "동작을 조합 가능한 저장소 구현으로 제공한다",
    "값을 비교·집계해 검증 가능한 요약 결과를 만든다",
    "처리에 필요한",
    "규칙을 한 경계에 모은다",
)
GENERATED_SYMBOL_DOCUMENTATION = re.compile(
    r"^(?:모듈|[A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_][A-Za-z0-9_]*은 "
    r"(?:현재 상태|.+ 입력)에서 .+ 값을 계산한다[.]?",
    re.MULTILINE,
)
EXPORT_DECLARATION = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?"
    r"(?:function|class|const|let|var|interface|type|enum)\b"
)
PUBLIC_FRONTEND_DECLARATION = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+"
    r"(?:use[A-Z][A-Za-z0-9_]*|[A-Z][A-Za-z0-9_]*)\b"
)


@dataclass(frozen=True)
class DocumentationFinding:
    """문서화가 누락된 파일·줄·공개 경계를 표현한다."""

    path: Path
    line: int
    symbol: str
    reason: str

    def render(self) -> str:
        """CI에서 클릭 가능한 repository-relative 진단을 만든다."""

        relative = self.path.relative_to(REPOSITORY_ROOT)
        return f"{relative}:{self.line}: {self.symbol}: {self.reason}"


def _is_meaningful_korean(documentation: str | None) -> bool:
    return bool(
        documentation
        and len(documentation.strip()) >= 10
        and HANGUL.search(documentation)
        # 이름만 바꾼 일괄 생성 문구는 코드의 실제 책임이나 실패 경계를 설명하지 않는다.
        and not any(phrase in documentation for phrase in GENERIC_DOCUMENTATION)
        and not GENERATED_SYMBOL_DOCUMENTATION.search(documentation.strip())
    )


def _python_findings(path: Path) -> tuple[DocumentationFinding, ...]:
    # Unit tests pass temporary files outside the repository. Only repository-relative
    # paths can match the small immutable migration allowlist; every other file still
    # receives the same AST and documentation checks.
    try:
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        relative = ""
    immutable_hash = IMMUTABLE_PYTHON_SOURCES.get(relative)
    if immutable_hash and hashlib.sha256(path.read_bytes()).hexdigest() == immutable_hash:
        return ()
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as error:
        return (
            DocumentationFinding(
                path, error.lineno or 1, "<module>", f"parse failure: {error.msg}"
            ),
        )
    findings: list[DocumentationFinding] = []
    if not _is_meaningful_korean(ast.get_docstring(tree, clean=False)):
        findings.append(
            DocumentationFinding(path, 1, "<module>", "한국어 책임 docstring이 없습니다.")
        )
    for node in tree.body:
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        if not _is_meaningful_korean(ast.get_docstring(node, clean=False)):
            findings.append(
                DocumentationFinding(
                    path, node.lineno, node.name, "공개 경계의 한국어 docstring이 없습니다."
                )
            )
        if not isinstance(node, ast.ClassDef):
            continue
        for member in node.body:
            if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if member.name.startswith("_"):
                continue
            if not _is_meaningful_korean(ast.get_docstring(member, clean=False)):
                findings.append(
                    DocumentationFinding(
                        path,
                        member.lineno,
                        f"{node.name}.{member.name}",
                        "공개 method의 한국어 docstring이 없습니다.",
                    )
                )
    return tuple(findings)


def _leading_jsdoc(lines: list[str], index: int) -> str | None:
    cursor = index - 1
    while cursor >= 0 and not lines[cursor].strip():
        cursor -= 1
    if cursor < 0 or not lines[cursor].strip().endswith("*/"):
        return None
    end = cursor
    while cursor >= 0 and "/**" not in lines[cursor]:
        cursor -= 1
    if cursor < 0:
        return None
    return "\n".join(lines[cursor : end + 1])


def _module_comment(lines: list[str]) -> str | None:
    first_code = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_code is None:
        return "빈 모듈"
    line = lines[first_code].strip()
    if line.startswith("//"):
        return line
    if line.startswith("/*"):
        end = first_code
        while end < len(lines) and "*/" not in lines[end]:
            end += 1
        return "\n".join(lines[first_code : min(end + 1, len(lines))])
    return None


def _frontend_findings(path: Path) -> tuple[DocumentationFinding, ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    findings: list[DocumentationFinding] = []
    if not _is_meaningful_korean(_module_comment(lines)):
        findings.append(
            DocumentationFinding(path, 1, "<module>", "한국어 책임 header comment가 없습니다.")
        )
    if path.suffix.lower() == ".css":
        return tuple(findings)
    seen_lines: set[int] = set()
    for index, line in enumerate(lines):
        if not (EXPORT_DECLARATION.match(line) or PUBLIC_FRONTEND_DECLARATION.match(line)):
            continue
        line_number = index + 1
        if line_number in seen_lines:
            continue
        seen_lines.add(line_number)
        if _is_meaningful_korean(_leading_jsdoc(lines, index)):
            continue
        symbol = line.strip()[:80]
        findings.append(
            DocumentationFinding(
                path, line_number, symbol, "공개 export/component의 한국어 JSDoc이 없습니다."
            )
        )
    return tuple(findings)


def _infrastructure_header(path: Path) -> str | None:
    """실행 설정의 첫 20줄에서 한국어 책임 주석을 찾아 반환한다."""

    lines = path.read_text(encoding="utf-8").splitlines()[:20]
    comments: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#!"):
            continue
        if stripped.startswith(("#", "--")):
            comments.append(stripped.lstrip("#- "))
    return " ".join(comments) or None


def _infrastructure_findings(path: Path) -> tuple[DocumentationFinding, ...]:
    """Shell·SQL·Compose·엔진 설정에 파일 책임을 설명하는 한국어 header를 요구한다."""

    if _is_meaningful_korean(_infrastructure_header(path)):
        return ()
    return (
        DocumentationFinding(
            path,
            1,
            "<module>",
            "실행 설정의 책임과 fail-closed 경계를 설명하는 한국어 header가 없습니다.",
        ),
    )


def _infrastructure_paths() -> tuple[Path, ...]:
    """과거 release/data archive를 제외한 실행 스크립트와 설정 파일을 열거한다."""

    paths = {path for path in INFRASTRUCTURE_CODE_FILES if path.is_file()}
    for root in INFRASTRUCTURE_CODE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            normalized = "/" + path.as_posix().lower()
            if (
                path.is_file()
                and (
                    path.suffix.lower() in INFRASTRUCTURE_SUFFIXES
                    or path.name.lower().startswith("dockerfile")
                )
                and not any(token in normalized for token in INFRASTRUCTURE_EXCLUDED_PATHS)
            ):
                paths.add(path)
    return tuple(sorted(paths))


def _source_paths() -> tuple[Path, ...]:
    paths: set[Path] = set()
    for root in PYTHON_ROOTS:
        if not root.exists():
            continue
        candidates = (root,) if root.is_file() else root.rglob("*.py")
        paths.update(
            path
            for path in candidates
            if path.is_file() and not EXCLUDED_PARTS.intersection(path.parts)
        )
    for root in FRONTEND_ROOTS:
        if not root.exists():
            continue
        candidates = (root,) if root.is_file() else root.rglob("*")
        paths.update(
            path
            for path in candidates
            if path.is_file()
            and path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".css"}
            and not EXCLUDED_PARTS.intersection(path.parts)
        )
    return tuple(sorted(paths))


def main() -> int:
    """모든 프로덕션 공개 경계를 검사하고 누락 시 실패 코드를 반환한다."""

    paths = _source_paths()
    infrastructure_paths = _infrastructure_paths()
    findings = tuple(
        finding
        for path in paths
        for finding in (
            _python_findings(path) if path.suffix == ".py" else _frontend_findings(path)
        )
    ) + tuple(
        finding
        for path in infrastructure_paths
        for finding in _infrastructure_findings(path)
    )
    if findings:
        print("[ERROR] CODE DOCUMENTATION VIOLATIONS")
        for finding in findings:
            print(f"  - {finding.render()}")
        return 1
    print(
        "Code documentation passed "
        f"({len(paths)} source files, {len(infrastructure_paths)} executable configs)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
