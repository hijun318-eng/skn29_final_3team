"""Repository-wide integrity inventory의 분류와 차단 규칙을 검증한다."""

import scripts.audit_repository_integrity as integrity_audit

from scripts.audit_repository_integrity import (
    _classify,
    _local_secret_findings,
    _review_text,
)


def test_classifies_tests_archives_and_runtime_contracts_separately() -> None:
    """test/archive/schema snapshot을 production 결과와 섞지 않는다."""

    assert _classify("tests/support/fakes.py") == "test"
    assert _classify("infrastructure/database/releases/r1/manifest.json") == "archive"
    assert _classify("src/ai/contracts/node_io.v0.1.json") == "runtime-contract"
    assert _classify("app/backend/app/main.py") == "production"


def test_rejects_demo_archive_and_request_context_from_runtime_config() -> None:
    """운영 설정이 과거 demo나 요청 전용 context를 다시 참조하면 실패한다."""

    text = """
    volumes:
      - ./docs/e2e_mvp/derived/service_demo_v3:/seed
    environment:
      CONTEXT_PATH: pms_crm_pos_context.v1.json
    """

    findings = _review_text("compose.yml", text, ".yml")

    assert len(findings) == 2


def test_rejects_question_catalog_and_test_double_in_production() -> None:
    """정적 질문 목록과 메모리 성공 adapter는 test 경계 밖에 둘 수 없다."""

    text = """
    APPROVED_QUESTIONS = ("one scenario",)
    class InMemorySuccessRepository:
        pass
    """

    findings = _review_text("app/backend/app/example.py", text, ".py")

    assert len(findings) == 2


def test_allows_versioned_schema_and_explicit_test_fixture() -> None:
    """소유된 schema manifest와 test double은 각자의 경계에서 허용한다."""

    assert _review_text(
        "src/ai/contracts/node_io.v0.1.json", "{}", ".json"
    ) == ()
    assert _review_text(
        "tests/support/fakes.py", "class ContractFakeModelAdapter: pass", ".py"
    ) == ()


def test_rejects_static_template_role_policy() -> None:
    """승인 template 역할은 단일 로컬 설정이 아니라 DB control plane이 소유한다."""

    findings = _review_text(
        "config/access-policy.yaml",
        '{"analysis_templates":{"one":{"allowed_roles":["analyst"]}}}',
        ".yaml",
    )

    assert len(findings) == 1


def test_rejects_production_test_authentication_bypass() -> None:
    """운영 모듈의 test token·mode 분기는 test support 주입으로 이동해야 한다."""

    findings = _review_text(
        "app/backend/app/auth.py",
        'AUTH_MODE = "test"\n_TEST_TOKENS = {"runtime-test-token": "principal"}',
        ".py",
    )

    assert len(findings) == 1


def test_rejects_datahub_authentication_or_guest_bypass() -> None:
    """운영 GMS는 metadata 인증을 끄거나 guest 주체를 열어 둘 수 없다."""

    findings = _review_text(
        "infrastructure/database/datahub/compose.consumer.yml",
        'METADATA_SERVICE_AUTH_ENABLED: "false"\nGUEST_AUTHENTICATION_ENABLED: "true"',
        ".yml",
    )

    assert len(findings) == 1


def test_rejects_already_corrupted_unicode_text(monkeypatch, tmp_path) -> None:
    """디코딩에 성공해도 대체문자가 남은 문서는 검토 완료로 기록하지 않는다."""

    document = tmp_path / "AGENTS.md"
    document.write_text("손상된 규칙 \ufffd", encoding="utf-8")
    monkeypatch.setattr(integrity_audit, "REPOSITORY_ROOT", tmp_path)

    findings = integrity_audit._review_file(document)

    assert len(findings) == 1
    assert "Unicode 대체문자" in findings[0].reason


def test_rejects_ignored_repository_local_env(tmp_path) -> None:
    """Git ignore가 실제 평문 secret 파일을 운영 입력으로 정당화하지 않는다."""

    (tmp_path / ".env").write_text("SECRET=not-a-real-secret\n", encoding="utf-8")

    findings = _local_secret_findings(tmp_path)

    assert len(findings) == 1
    assert findings[0].path == ".env"


def test_rejects_secret_values_in_process_arguments() -> None:
    """Docker argv와 Python CLI option으로 평문 secret을 전달할 수 없다."""

    powershell = """
    & docker compose exec --env "PGPASSWORD=$($values.DB_PASSWORD)" database true
    """
    python = 'parser.add_argument("--trino-password")'

    assert len(_review_text("infrastructure/database/scripts/verify.ps1", powershell, ".ps1")) == 1
    assert len(_review_text("infrastructure/database/datahub/build.py", python, ".py")) == 1


def test_allows_secret_variable_name_without_value() -> None:
    """child 환경이 상속할 변수 이름만 argv에 기록하는 전달 방식은 허용한다."""

    text = "& docker exec --env TRINO_PASSWORD trino trino --password"

    assert _review_text("infrastructure/database/scripts/verify.ps1", text, ".ps1") == ()
