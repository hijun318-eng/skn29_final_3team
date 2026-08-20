#!/usr/bin/env python3
"""저장소의 모든 비무시 파일을 분류하고 운영 우회 구현을 탐지한다.

이 감사기는 파일 이름만 세는 도구가 아니다. 운영 소스와 실행 설정이 테스트 double,
과거 demo, 고정 release archive, 요청 전용 JSON을 다시 실행 경로로 끌어오는지를 검사한다.
테스트 fixture와 불변 release archive는 삭제 대상이 아니라 운영 비참조 증거로 분리한다.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPOSITORY_ROOT / "docs" / "architecture" / "repository-file-inventory.md"
TEXT_SUFFIXES = {
    "", ".conf", ".config", ".css", ".example", ".html", ".ini", ".js",
    ".json", ".jsonl", ".jsx", ".md", ".mjs", ".properties", ".ps1", ".py",
    ".sh", ".sql", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
}
PRODUCTION_PREFIXES = (
    "app/backend/app/",
    "app/frontend/src/",
    "src/ai/",
    "src/data/",
    "src/modelops/",
    "src/report/",
    "scripts/",
    "infrastructure/database/datahub/",
)
RUNTIME_CONFIG_PREFIXES = (
    ".github/",
    "app/backend/scripts/",
    "app/backend/migrations/",
    "infrastructure/database/scripts/",
    "infrastructure/database/trino/",
)
ARCHIVE_PREFIXES = (
    "evals/",
    "infrastructure/database/releases/",
    "infrastructure/database/sql/data/",
)
LOCAL_CACHE_PREFIXES = (
    ".codex-",
    ".pytest-",
    ".pytest_cache/",
    ".playwright-cli/",
    "app/frontend/.pytest_cache/",
)
RUNTIME_CONFIG_FILES = {
    "compose.yml",
    "compose.app-postgres.override.yml",
    "app/backend/compose.fragment.yml",
    "app/backend/Dockerfile",
    "app/frontend/vite.config.js",
    "infrastructure/database/compose.yml",
}

# 이 목록은 운영 데이터가 아니라 정적 감사 정책이다. 새 항목은 소유자·생성 절차·
# validator가 있는 versioned schema/config/manifest일 때만 추가한다.
ALLOWED_RUNTIME_JSON = {
    "app/frontend/package.json": "frontend dependency manifest",
    "app/frontend/package-lock.json": "frontend dependency lock",
    "app/backend/contracts/openapi.v0.1.json": "generated API contract snapshot",
    "app/backend/contracts/state_mapping.v0.1.json": "versioned state contract",
    "src/ai/contracts/model_release.v1.json": "provider response schema manifest",
    "src/ai/contracts/node_io.v0.1.json": "versioned node I/O schema",
    "src/modelops/model_runtime_manifest.v1.json": "validated model capacity manifest",
    "src/modelops/model_candidate.instruct2507.v0.1.json": "historical model evidence",
    "src/modelops/model_decision.v0.1.json": "non-ready model decision record",
    "src/modelops/release_candidate.v1.json": "non-ready release evidence",
    "src/modelops/serving_manifest.v0.1.json": "historical serving evidence",
    "infrastructure/database/trino/etc/access-control-rules.json": "Trino policy config",
    "infrastructure/database/datahub/decisions/metric_retirement_20260820.v1.json": (
        "validated product-scope retirement decision"
    ),
}
PROHIBITED_RUNTIME_REFERENCES = {
    "docs/e2e_mvp/derived/service_demo_v3": "과거 demo seed",
    "infrastructure/database/releases/": "불변 과거 release archive",
    "r1-service-fragment.v1.json": "삭제된 service fixture manifest",
    "candidate_context": "요청 전용 context snapshot",
    "pms_crm_pos_context": "요청 전용 context snapshot",
    "source_registry.v1.json": "고정 source registry",
    "data_platform_mode=fake": "운영 fake data platform mode",
    "synthetic-local": "고정 synthetic principal",
}
STATIC_QUESTION_CATALOG = re.compile(
    r"\b(?:APPROVED|EXAMPLE|SAMPLE|DEMO)_QUESTIONS?\b", re.IGNORECASE
)
# 특정 고객·release·승인 metric은 외부 policy 입력과 불변 archive에는 존재할 수
# 있지만, 운영 Python/TypeScript에 들어가면 다음 요청을 위해 코드를 다시 고치는
# 구조가 된다. 아래 이름은 현재 승인 workflow가 runtime과 분리됐는지 확인하는
# 회귀 표식이며 실제 metric registry 역할을 하지 않는다.
REQUEST_SPECIFIC_RUNTIME_LITERAL = re.compile(
    r"walkerhill|analytics_v4_3|\bV4\.3\b|"
    r"total_operating_revenue_krw|banquet_cancelled_events|"
    r"voc_(?:review_count|low_rating_reviews|negative_reviews|positive_reviews|followup_reviews)",
    re.IGNORECASE,
)
# 질문 문구를 직접 훑어 route·기간·차트를 정하는 분기는 동의어·오타·새로운 표현이
# 나올 때마다 사전을 고쳐야 하고, 승인된 의미 계약을 우회해 사용자의 요청을 조용히
# 다른 동작으로 바꾼다. 아래는 한국어 의도 어휘가 정규식·문자열 비교 안에 들어간
# 형태를 잡는다. 판정은 Node1의 typed 신호와 서버 전제조건 검증이 소유해야 한다.
_ROUTE_INTENT_WORDS = "보고서|리포트|그래프|차트|테이블|막대|꺾은선|시각화|보여줘|나타내줘|담아|바꿔"
_PERIOD_INTENT_WORDS = (
    "지난달|저번달|그전달|다음달|올해|금년|작년|전년|지난해|재작년|내년|익년|"
    "분기|상반기|하반기|최근|지난"
)
_INTENT_WORDS = f"{_ROUTE_INTENT_WORDS}|{_PERIOD_INTENT_WORDS}"
QUESTION_PHRASE_ROUTING = re.compile(
    # 정규식 리터럴 안에 의도 어휘가 들어간 경우
    rf"(?:re\.(?:search|match|fullmatch|compile)|new RegExp)\s*\([^)]*(?:{_INTENT_WORDS})"
    # 발화 문자열 포함 검사로 분기하는 경우. 조사가 붙어도 잡도록 따옴표 안 어디든 허용한다.
    rf"|[\"'][^\"']*(?:{_INTENT_WORDS})[^\"']*[\"']\s*\)?\s*in\s+"
    rf"|\.includes\(\s*[\"'][^\"']*(?:{_INTENT_WORDS})[^\"']*[\"']\s*\)",
)
PRODUCTION_DOUBLE = re.compile(
    r"\b(?:class|function)\s+(?:Fake|Mock|Stub|InMemory)[A-Za-z0-9_]*\b"
)
PRODUCTION_TEST_AUTH = re.compile(
    r"\bAUTH_MODE\s*[:=]\s*[\"']?test\b|\b_TEST_TOKENS\b|\bruntime-test-token\b",
    re.IGNORECASE,
)
DATAHUB_AUTH_BYPASS = re.compile(
    r"\bMETADATA_SERVICE_AUTH_ENABLED\s*[:=]\s*[\"']?false\b"
    r"|\bGUEST_AUTHENTICATION_ENABLED\s*[:=]\s*[\"']?true\b",
    re.IGNORECASE,
)
# Docker/Compose 명령 인자에 secret 값을 보간하면 process listing과 진단 로그에
# 평문이 남는다. 변수 이름만 전달하는 ``--env NAME``은 허용하고 ``NAME=value``
# 또는 Python CLI의 password 값 옵션은 운영 script에서 차단한다.
SECRET_COMMAND_ARGUMENT = re.compile(
    r"(?:--env|[\"']--env[\"'])[\s,`]*(?:[\"'])?"
    r"[A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN)[A-Z0-9_]*=\$\("
    r"|add_argument\(\s*[\"']--[a-z0-9-]*(?:password|secret|token)[\"']",
    re.IGNORECASE,
)
HISTORICAL_JSON = {
    "src/modelops/model_candidate.instruct2507.v0.1.json",
    "src/modelops/model_decision.v0.1.json",
    "src/modelops/release_candidate.v1.json",
    "src/modelops/serving_manifest.v0.1.json",
}
AUDIT_TOOL_FILES = {
    "scripts/audit_repository_integrity.py",
    "scripts/check_code_documentation.py",
    "scripts/lint_architectural_invariants.py",
}


@dataclass(frozen=True)
class Finding:
    """전수 감사에서 발견한 파일별 운영 무결성 위반을 표현한다."""

    path: str
    reason: str


def _repository_files() -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    names = result.stdout.decode("utf-8").split("\0")
    return tuple(
        sorted(
            (
                path
                for name in names
                if name and (path := REPOSITORY_ROOT / name).is_file()
            ),
            key=lambda path: path.as_posix().lower(),
        )
    )


def _relative(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def _classify(relative: str) -> str:
    if relative.startswith(LOCAL_CACHE_PREFIXES):
        return "local-cache"
    if relative.startswith("tests/"):
        return "test"
    if relative in HISTORICAL_JSON:
        return "archive"
    if relative in ALLOWED_RUNTIME_JSON:
        return "runtime-contract"
    if relative.startswith(ARCHIVE_PREFIXES):
        return "archive"
    if (
        relative.endswith(".md")
        or relative.startswith(("docs/", ".agents/"))
        or relative in {"AGENTS.md", "CLAUDE.md"}
    ):
        return "documentation"
    if relative.startswith(PRODUCTION_PREFIXES):
        return "production"
    if relative.startswith(RUNTIME_CONFIG_PREFIXES) or relative in RUNTIME_CONFIG_FILES:
        return "runtime-config"
    if relative.endswith((".png", ".docx", ".xlsx", ".pptx")):
        return "asset"
    return "project-config"


def _read_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _review_text(relative: str, text: str, suffix: str) -> tuple[Finding, ...]:
    """분류된 텍스트 한 건에서 운영 우회 참조를 찾는다."""

    category = _classify(relative)
    if category not in {"production", "runtime-config", "project-config"}:
        return ()
    if relative == "scripts/audit_repository_integrity.py":
        return ()
    normalized = text.replace("\\", "/").lower()
    findings: list[Finding] = []
    if relative not in AUDIT_TOOL_FILES:
        for token, description in PROHIBITED_RUNTIME_REFERENCES.items():
            if token.lower() in normalized:
                findings.append(Finding(relative, f"운영 경로가 {description}를 참조합니다: {token}"))
    if STATIC_QUESTION_CATALOG.search(text):
        findings.append(Finding(relative, "정적 예시 질문 catalog가 운영 소스에 있습니다."))
    if category == "production" and REQUEST_SPECIFIC_RUNTIME_LITERAL.search(text):
        findings.append(
            Finding(
                relative,
                "특정 고객·release·metric literal은 외부 승인 policy에서만 관리해야 합니다.",
            )
        )
    if category == "production" and QUESTION_PHRASE_ROUTING.search(text):
        findings.append(
            Finding(
                relative,
                "질문 문구로 route·기간·차트를 분기했습니다. Node1의 typed 신호와 "
                "서버 전제조건 검증으로 판정하세요.",
            )
        )
    if PRODUCTION_DOUBLE.search(text):
        findings.append(Finding(relative, "test double 구현이 운영 소스에 선언되어 있습니다."))
    if PRODUCTION_TEST_AUTH.search(text):
        findings.append(Finding(relative, "test 인증 token 또는 mode가 운영 경계에 남아 있습니다."))
    if DATAHUB_AUTH_BYPASS.search(text):
        findings.append(
            Finding(
                relative,
                "DataHub metadata 인증을 끄거나 guest 우회 주체를 활성화한 운영 설정입니다.",
            )
        )
    if SECRET_COMMAND_ARGUMENT.search(text):
        findings.append(
            Finding(
                relative,
                "secret 값을 command argv에 넣지 말고 child process 환경에는 변수 이름만 전달하세요.",
            )
        )
    if "analysis_templates" in text and "allowed_roles" in text and suffix.lower() in {".json", ".yaml", ".yml"}:
        findings.append(
            Finding(relative, "Template별 역할을 고정 파일에 저장하지 말고 승인 DB metadata를 사용하세요.")
        )
    if suffix.lower() == ".json" and relative not in ALLOWED_RUNTIME_JSON:
        findings.append(Finding(relative, "소유·생성·검증 계약이 분류되지 않은 운영 JSON입니다."))
    return tuple(findings)


def _local_secret_findings(root: Path = REPOSITORY_ROOT) -> tuple[Finding, ...]:
    """Git ignore 여부와 무관하게 저장소 내부의 실제 ``.env`` secret 파일을 차단한다."""

    findings: list[Finding] = []
    excluded = {".git", "node_modules", "__pycache__"}
    for path in root.rglob(".env"):
        try:
            relative_path = path.relative_to(root)
        except ValueError:
            relative_path = path
        if (
            not path.is_file()
            or excluded.intersection(relative_path.parts)
            or any(
                part.startswith((".pytest", ".codex"))
                for part in relative_path.parts
            )
        ):
            continue
        try:
            relative = relative_path.as_posix()
        except ValueError:
            relative = str(path)
        findings.append(
            Finding(
                relative,
                "평문 자격증명 위험이 있는 repository-local .env 대신 명시적 외부 secret 파일을 사용하세요.",
            )
        )
    return tuple(findings)


def _review_file(path: Path) -> tuple[Finding, ...]:
    relative = _relative(path)
    text = _read_text(path)
    if path.suffix.lower() in TEXT_SUFFIXES and text is None:
        return (
            Finding(
                relative,
                "텍스트 파일을 UTF-8로 읽을 수 없어 파일별 내용 감사를 수행할 수 없습니다.",
            ),
        )
    if text is None:
        return ()
    # UTF-8 decoding 자체가 성공해도 이미 U+FFFD로 손상된 문서는 원문을 복원할 수
    # 없다. 이런 파일을 REVIEWED로 기록하면 주석·운영 절차 전수 감사가 허위가 된다.
    if "\ufffd" in text:
        return (
            Finding(
                relative,
                "Unicode 대체문자가 남아 있어 사람이 읽을 수 있는 원문을 복원해야 합니다.",
            ),
        )
    return _review_text(relative, text, path.suffix)


def _inventory_status(path: Path) -> str:
    category = _classify(_relative(path))
    if category == "test":
        return "TEST_ONLY"
    if category == "archive":
        return "ARCHIVE_NON_RUNTIME"
    if category == "local-cache":
        return "LOCAL_CACHE_NOT_PRODUCT"
    if category in {"documentation", "asset"}:
        return "REFERENCE_NON_RUNTIME"
    return "REVIEWED" if not _review_file(path) else "VIOLATION"


def _render_report(paths: tuple[Path, ...], findings: tuple[Finding, ...]) -> str:
    counts = Counter(_classify(_relative(path)) for path in paths)
    lines = [
        "# Repository file integrity inventory",
        "",
        "> 이 파일은 `python scripts/audit_repository_integrity.py --write-report`로 생성한다. ",
        "> Git이 관리하거나 명시적으로 추가된 모든 비무시 파일을 분류하며, test/archive 결과를 live 증거로 승격하지 않는다.",
        "",
        "## 분류 요약",
        "",
        "| 분류 | 파일 수 |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {counts[name]} |" for name in sorted(counts))
    lines.extend(
        [
            "",
            f"운영 무결성 위반: **{len(findings)}건**",
            "",
            "## 파일별 검토 결과",
            "",
            "| 파일 | 분류 | 결과 |",
            "|---|---|---|",
        ]
    )
    for path in paths:
        relative = _relative(path)
        escaped = relative.replace("|", "\\|")
        lines.append(f"| `{escaped}` | {_classify(relative)} | {_inventory_status(path)} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """전수 감사 결과를 출력하고 선택적으로 파일별 inventory를 갱신한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args(argv)
    paths = _repository_files()
    findings = tuple(item for path in paths for item in _review_file(path)) + _local_secret_findings()
    if args.write_report:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(_render_report(paths, findings), encoding="utf-8")
    if findings:
        print("[ERROR] REPOSITORY INTEGRITY VIOLATIONS")
        for finding in findings:
            print(f"  - {finding.path}: {finding.reason}")
        return 1
    print(f"Repository integrity audit passed ({len(paths)} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
