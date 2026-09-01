"""공개 코드 경계의 책임 주석 검사기를 검증한다."""

import hashlib
from pathlib import Path

from scripts.check_code_documentation import (
    PYTHON_ROOTS,
    REPOSITORY_ROOT,
    _frontend_findings,
    _infrastructure_findings,
    _python_findings,
)


def test_rag_and_ml_production_roots_require_public_boundary_documentation() -> None:
    """RAG·ML 공개 경계도 Backend와 같은 문서화 정책으로 검사한다."""

    assert REPOSITORY_ROOT / "src" / "rag" in PYTHON_ROOTS
    assert REPOSITORY_ROOT / "src" / "ml" in PYTHON_ROOTS


def test_python_checker_requires_module_class_and_public_method_docs(tmp_path: Path) -> None:
    """Python 공개 경계마다 의미 있는 한국어 docstring이 필요하다."""

    path = tmp_path / "sample.py"
    path.write_text(
        '"""테스트 모듈의 외부 책임을 설명한다."""\n'
        "class PublicService:\n"
        '    """공개 작업 흐름을 조정하는 서비스다."""\n'
        "    def execute(self):\n"
        "        return None\n",
        encoding="utf-8",
    )

    findings = _python_findings(path)

    assert len(findings) == 1
    assert findings[0].symbol == "PublicService.execute"


def test_frontend_checker_requires_module_and_export_jsdoc(tmp_path: Path) -> None:
    """Frontend module header와 공개 export의 한국어 JSDoc을 각각 확인한다."""

    path = tmp_path / "sample.ts"
    path.write_text(
        "/** 화면 계약을 정규화하는 모듈이다. */\n"
        "const internal = true;\n"
        "export function normalize(value) { return value; }\n",
        encoding="utf-8",
    )

    findings = _frontend_findings(path)

    assert len(findings) == 1
    assert "export function normalize" in findings[0].symbol


def test_frontend_checker_accepts_meaningful_korean_jsdoc(tmp_path: Path) -> None:
    """책임을 설명하는 module/JSDoc 조합은 통과시킨다."""

    path = tmp_path / "sample.jsx"
    path.write_text(
        "/** 보고서 화면의 표현 경계를 제공한다. */\n"
        "/** 서버에서 검증된 제목만 화면에 렌더링한다. */\n"
        "export function ReportTitle({ title }) { return title; }\n",
        encoding="utf-8",
    )

    assert _frontend_findings(path) == ()


def test_checker_rejects_name_only_generated_documentation(tmp_path: Path) -> None:
    """심볼 이름만 반복하는 자동 생성 문구를 상세 주석으로 오인하지 않는다."""

    path = tmp_path / "generated.py"
    path.write_text(
        '"""테스트 모듈의 외부 책임을 설명한다."""\n'
        "class PublicContract:\n"
        '    """PublicContract 데이터와 불변식을 표현하는 공개 계약이다."""\n'
        "    pass\n",
        encoding="utf-8",
    )

    findings = _python_findings(path)

    assert len(findings) == 1
    assert findings[0].symbol == "PublicContract"


def test_checker_rejects_generated_input_output_sentence(tmp_path: Path) -> None:
    """심볼·인자 이름만 끼워 넣은 계산 문장도 책임 문서로 인정하지 않는다."""

    path = tmp_path / "generated_service.py"
    path.write_text(
        '"""테스트 모듈의 외부 책임을 설명한다."""\n'
        "def authenticate_credentials(username, password):\n"
        '    """모듈.authenticate_credentials은 username, password 입력에서 '
        'authenticate credentials 값을 계산한다."""\n'
        "    return None\n",
        encoding="utf-8",
    )

    findings = _python_findings(path)

    assert len(findings) == 1
    assert findings[0].symbol == "authenticate_credentials"


def test_infrastructure_checker_requires_korean_responsibility_header(
    tmp_path: Path,
) -> None:
    """실행 스크립트는 shebang만으로 문서화된 것으로 판정하지 않는다."""

    path = tmp_path / "entrypoint.sh"
    path.write_text("#!/bin/sh\nset -eu\n", encoding="utf-8")

    findings = _infrastructure_findings(path)

    assert len(findings) == 1
    assert findings[0].symbol == "<module>"


def test_infrastructure_checker_accepts_fail_closed_header(tmp_path: Path) -> None:
    """책임과 실패 경계를 설명하는 한국어 설정 header는 통과시킨다."""

    path = tmp_path / "compose.yml"
    path.write_text(
        "# 외부 secret이 없으면 서비스를 시작하지 않는 배포 경계다.\nservices: {}\n",
        encoding="utf-8",
    )

    assert _infrastructure_findings(path) == ()


def test_checker_does_not_rewrite_checksum_pinned_migration() -> None:
    """배포된 migration은 한국어 주석보다 byte checksum 재현성을 우선한다."""

    path = Path("app/backend/migrations/versions/20260730_02_application_schema.py")

    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "a468edca9b560c78afffc46876acb4d6b2ef1d6b42641d00fcc2db1c63c285ee"
    )
    assert _python_findings(path.resolve()) == ()
