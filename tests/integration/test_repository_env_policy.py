"""활성 deployment 진입점이 저장소의 단일 dotenv만 선택하는지 검증한다."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "infrastructure/database/scripts/deployment-environment.ps1"
EXPECTED_CALLERS = {
    "app/backend/scripts/verify-container.ps1",
    "infrastructure/database/datahub/ingest_runtime_catalog.ps1",
    "infrastructure/database/scripts/recreate-serving-views.ps1",
    "infrastructure/database/scripts/reset.ps1",
    "infrastructure/database/scripts/rollback-datahub-runtime.ps1",
    "infrastructure/database/scripts/start.ps1",
    "infrastructure/database/scripts/stop.ps1",
    "infrastructure/database/scripts/upgrade-datahub-runtime.ps1",
    "infrastructure/database/scripts/verify-release-sources.ps1",
    "infrastructure/database/scripts/verify-release-trino.ps1",
    "infrastructure/database/scripts/verify.ps1",
    "infrastructure/database/security/provision-release-principals.ps1",
    "infrastructure/database/security/provision-serving-catalog-secrets.ps1",
    "infrastructure/database/security/provision-trino-password-database.ps1",
}


def _active_powershell_sources() -> dict[str, str]:
    """release archive를 제외한 현재 PowerShell 진입점 원문을 반환한다."""

    paths = [
        *sorted((ROOT / "app/backend/scripts").rglob("*.ps1")),
        *sorted((ROOT / "infrastructure/database").rglob("*.ps1")),
    ]
    return {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8-sig")
        for path in paths
        if "releases" not in path.parts
    }


def test_repository_env_policy_has_no_external_or_process_fallback() -> None:
    """고정 `.env`, gitignore, symlink 차단을 우회하는 fallback을 금지한다."""

    source = POLICY.read_text(encoding="utf-8-sig")

    assert "infrastructure/database/.env" in source
    assert "Resolve-RepositoryDeploymentEnvFile" in source
    assert "GetEnvironmentVariables" not in source
    assert "Resolve-ExternalDeploymentEnvFile" not in source
    assert "Resolve-ExplicitDeploymentEnvFile" not in source
    assert "ReparsePoint" in source
    assert "check-ignore" in source


def test_all_active_env_consumers_use_the_repository_resolver() -> None:
    """env를 읽는 현재 PowerShell caller가 단일 resolver를 벗어나지 못하게 한다."""

    sources = _active_powershell_sources()
    callers = {
        path
        for path, source in sources.items()
        if path != POLICY.relative_to(ROOT).as_posix()
        and "Resolve-RepositoryDeploymentEnvFile" in source
    }

    assert callers == EXPECTED_CALLERS
    assert all("Resolve-ExternalDeploymentEnvFile" not in source for source in sources.values())
    assert all("Resolve-ExplicitDeploymentEnvFile" not in source for source in sources.values())


def test_human_account_bootstrap_has_two_fixed_database_roles() -> None:
    """bootstrap은 DB에 analyst/admin만 만들고 username의 subject를 보존한다."""

    provisioner = (
        ROOT / "infrastructure/database/security/provision-release-principals.ps1"
    ).read_text(encoding="utf-8-sig")
    backend_provisioner = (ROOT / "app/backend/scripts/provision_accounts.py").read_text(
        encoding="utf-8-sig"
    )
    example = (ROOT / "infrastructure/database/.env.example").read_text(
        encoding="utf-8-sig"
    )

    assert provisioner.count("username_env =") == 2
    assert "role = 'analyst'" in provisioner
    assert "role = 'admin'" in provisioner
    assert "scripts/provision_accounts.py" in provisioner
    assert "require_subject_match = -not" in provisioner
    assert "require_subject_match and persisted_subject !=" in backend_provisioner
    assert "LegacyPrincipalPath" in provisioner
    assert "$item.Length -gt 1MB" in provisioner
    assert "HashSet[string]" in provisioner
    assert "observedSubjects.Add" in provisioner
    assert "Rfc2898DeriveBytes" not in provisioner
    assert "create_password_verifier" in backend_provisioner
    assert "ON CONFLICT (username) DO UPDATE" in backend_provisioner
    assert "subject = EXCLUDED.subject" not in backend_provisioner
    assert "ANALYST_LOGIN_ROLE" not in example
    assert "REPORT_ADMIN_LOGIN_" not in example
    assert "role_env" not in provisioner
    assert "ValidateSet" not in provisioner
    assert "Group-Object username" not in provisioner
    assert "$bootstrapAccounts[0]['username']" in provisioner
    assert "Remove-EnvValue 'ANALYST_LOGIN_ROLE'" in provisioner
    assert "Remove-EnvValue 'REPORT_ADMIN_LOGIN_ID'" in provisioner
    assert "Remove-EnvValue 'REPORT_ADMIN_LOGIN_PASSWORD'" in provisioner
    legacy_guard = provisioner.index("Legacy principal migration is pending")
    database_provision = provisioner.index("& docker compose")
    provision_success = provisioner.index("$result.status -ne 'ok'")
    legacy_key_removal = provisioner.index(
        "Remove-EnvValue 'AUTH_PRINCIPALS_HOST_FILE'"
    )
    assert legacy_guard < database_provision < provision_success < legacy_key_removal
    assert "ADMIN_LOGIN_ID=admin" in example
    assert "ADMIN_LOGIN_PASSWORD=" in example
    assert "answervice_auth_principals" not in provisioner + example

    # 같은 문자열을 쓰더라도 Trino setup principal은 사람의 App Role이 아니다.
    assert "TRINO_ADMIN_USER=answervice_platform_admin" in example


def test_two_role_upgrade_documents_the_closed_authentication_window() -> None:
    """구·신 Backend 동시 실행 없이 DB·DataHub 전환을 끝내는 순서를 고정한다."""

    documents = [
        (ROOT / "README.md").read_text(encoding="utf-8-sig"),
        (ROOT / "infrastructure/database/README.md").read_text(encoding="utf-8-sig"),
        (ROOT / "docs/e2e_mvp/LOCAL_SETUP.md").read_text(encoding="utf-8-sig"),
    ]

    for document in documents:
        migration = document.index("upgrade head")
        provision = document.index("provision", migration)
        datahub = document.index("DataHub", provision)
        new_backend = document.index("새 Backend", datahub)
        assert migration < provision < datahub < new_backend
        assert "old/new Backend" in document or "구 Backend와 새 Backend" in document
        assert any(
            marker in document
            for marker in ("인증 트래픽", "인증 요청", "로그인 트래픽")
        )
