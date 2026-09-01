import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.yml"
OVERRIDE = ROOT / "compose.app-postgres.override.yml"
STAGE5_COMPOSE = ROOT / "compose.report-assistant-stage5.yml"
ENV_EXAMPLE = ROOT / "infrastructure/database/.env.example"
BACKEND_VERIFIER = ROOT / "app/backend/scripts/verify-container.ps1"
BACKEND_DOCKERFILE = ROOT / "app/backend/Dockerfile"
BACKEND_COMPOSE = ROOT / "app/backend/compose.fragment.yml"
SOURCE_PROVENANCE = ROOT / "app/backend/scripts/source-provenance.ps1"


def _config() -> dict:
    env = os.environ | {"COMPOSE_PROJECT_NAME": "answervice"}
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "infrastructure/database/.env.example",
            "--profile",
            "dev",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _stage5_config() -> dict:
    env = os.environ | {
        "REPORT_ASSISTANT_MODEL_ENV_FILE": "infrastructure/database/.env.example"
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "infrastructure/database/.env.example",
            "-f",
            "compose.report-assistant-stage5.yml",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_canonical_env_example_covers_datahub_runtime_secrets():
    env_keys = {
        line.split("=", 1)[0]
        for line in (ROOT / "infrastructure/database/.env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }

    assert {
        "APP_CATALOG_PUBLISHER_USER",
        "APP_CATALOG_PUBLISHER_PASSWORD",
        "DATAHUB_MYSQL_PASSWORD",
        "DATAHUB_MYSQL_ROOT_PASSWORD",
        "DATAHUB_SECRET",
        "DATAHUB_TOKEN_SERVICE_SALT",
        "DATAHUB_TOKEN_SERVICE_SIGNING_KEY",
    } <= env_keys
    assert not (ROOT / ".env.example").exists()


def test_mcp_rate_limit_is_explicit_in_both_backend_deployments():
    example = {
        key: value
        for key, value in (
            line.split("=", 1)
            for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        )
    }
    assert example["MCP_TOOL_RATE_LIMIT_QUOTA"] == "30"
    assert example["MCP_TOOL_RATE_LIMIT_WINDOW_SECONDS"] == "60"

    expected = {
        "MCP_TOOL_RATE_LIMIT_QUOTA": "30",
        "MCP_TOOL_RATE_LIMIT_WINDOW_SECONDS": "60",
    }
    for backend in (
        _config()["services"]["backend"],
        _stage5_config()["services"]["backend"],
    ):
        assert {
            key: backend["environment"][key] for key in expected
        } == expected

    for source in (BACKEND_COMPOSE, STAGE5_COMPOSE):
        compose = source.read_text(encoding="utf-8")
        for key in expected:
            assert f"{key}: ${{{key}:?{key} is required}}" in compose
            assert f"{key}: ${{{key}:-" not in compose


def test_root_include_applies_only_the_runtime_identity_override():
    root = COMPOSE.read_text(encoding="utf-8")
    override = OVERRIDE.read_text(encoding="utf-8")

    assert "- infrastructure/database/compose.yml" in root
    assert "- app/backend/compose.fragment.yml" in root
    assert "- app/frontend/compose.fragment.yml" in root
    assert "- infrastructure/database/datahub/compose.consumer.yml" in root
    assert "- compose.app-postgres.override.yml" in root
    # 한국어 책임 header 같은 비실행 문서는 허용하되 override가 identity/port 외의
    # 운영 설정을 바꾸지 않는지는 실제 key 표면으로 검증한다.
    assert "container_name: answervice-app-postgres" in override
    assert 'ports: !override ["127.0.0.1:25432:5432"]' in override
    assert 'ports: !override ["127.0.0.1:28000:8000"]' in override
    assert override.count("ports: !override") == 2
    for forbidden in ("environment:", "volumes:", "image:", "command:", "build:"):
        assert forbidden not in override


def test_resolved_app_postgres_keeps_service_contract_except_identity():
    service = _config()["services"]["app-postgres"]

    assert service["container_name"] == "answervice-app-postgres"
    assert service["ports"] == [
        {"mode": "ingress", "target": 5432, "published": "25432", "protocol": "tcp", "host_ip": "127.0.0.1"}
    ]
    assert service["volumes"][0]["target"] == "/var/lib/postgresql/data"
    assert service["healthcheck"]["test"] == [
        "CMD-SHELL",
        "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB",
    ]


def test_resolved_backend_uses_an_isolated_host_port_only():
    service = _config()["services"]["backend"]

    assert service["ports"] == [
        {"mode": "ingress", "target": 8000, "published": "28000", "protocol": "tcp", "host_ip": "127.0.0.1"}
    ]


def test_catalog_publisher_credentials_are_confined_to_the_out_of_band_boundary():
    services = _config()["services"]
    postgres = services["app-postgres"]["environment"]
    migrations = services["app-migrations"]["environment"]
    backend = services["backend"]["environment"]

    assert postgres["APP_CATALOG_PUBLISHER_USER"] == "app_catalog_publisher"
    assert postgres["APP_CATALOG_PUBLISHER_PASSWORD"] == (
        "CHANGE_ME_AppCatalogPublisher"
    )
    assert migrations["APP_CATALOG_PUBLISHER_USER"] == "app_catalog_publisher"
    assert "APP_CATALOG_PUBLISHER_PASSWORD" not in migrations
    assert "APP_CATALOG_PUBLISHER_USER" not in backend
    assert "APP_CATALOG_PUBLISHER_PASSWORD" not in backend


def test_backend_verifier_uses_the_resolved_port_and_all_readiness_dependencies():
    source = BACKEND_VERIFIER.read_text(encoding="utf-8")

    assert "http://127.0.0.1:28000" in source
    assert "http://127.0.0.1:18000" not in source
    assert "[switch]$AllowRepositoryLocalDevelopment" in source
    assert "Resolve-ExplicitDeploymentEnvFile" in source
    assert "-AllowRepositoryLocalDevelopment:$AllowRepositoryLocalDevelopment" in source
    assert "dependencies.PSObject.Properties" in source
    assert "$readinessDependencies.Count -eq 0" in source
    assert "$notReadyDependencies.Count -gt 0" in source
    assert "dependencies.datahub" not in source


def test_backend_image_and_verifier_include_the_sealed_phase2a_gate():
    dockerfile = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    verifier = BACKEND_VERIFIER.read_text(encoding="utf-8")

    for artifact in (
        "evals/metric_retrieval.py",
        "evals/metric_retrieval_runner.py",
        "evals/metric_retrieval_gold/answervice_ko_retrieval.v2.json",
    ):
        assert artifact in dockerfile
    assert "/workspace/evals/metric_retrieval_runner.py" in verifier
    assert "--phase2a-gold-manifest" in verifier
    assert "answervice.metric_retrieval_phase2a.v2" in verifier
    assert "$retrievalGate.decision -ne 'PROMOTE'" in verifier
    assert "BACKEND_METRIC_RETRIEVAL_READY" in verifier


def test_backend_image_includes_node2_runtime_evidence():
    dockerfile = BACKEND_DOCKERFILE.read_text(encoding="utf-8")

    for artifact in (
        "evals/node2_qwen35_2b_full3000_huggingface.receipt.json",
        "evals/node2_qwen35_2b_full3000_canary.v1.json",
        "evals/node2_qwen35_2b_cp135_huggingface.receipt.json",
    ):
        assert artifact in dockerfile


def test_backend_verifier_rehearses_search_rollback_as_one_scoped_receipt():
    verifier = BACKEND_VERIFIER.read_text(encoding="utf-8")

    stages = (
        "candidate_baseline",
        "lexical_rollback",
        "candidate_restore",
    )
    assert [verifier.index(stage) for stage in stages] == sorted(
        verifier.index(stage) for stage in stages
    )
    assert "answervice.search-rollback-receipt.v1" in verifier
    assert "P0-DATAHUB-SEARCH_PROCESS_MODE_ONLY" in verifier
    assert "Search rollback receipt path must be covered by .gitignore." in verifier
    assert "Search rollback rehearsal crossed a release or Gold identity." in verifier
    assert "BACKEND_SEARCH_ROLLBACK_VERIFIED=" in verifier


def test_backend_build_fails_closed_and_verifier_matches_source_provenance():
    dockerfile = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    compose = BACKEND_COMPOSE.read_text(encoding="utf-8")
    verifier = BACKEND_VERIFIER.read_text(encoding="utf-8")
    resolver = SOURCE_PROVENANCE.read_text(encoding="utf-8")

    for key in (
        "ANSWERVICE_SOURCE_REVISION",
        "ANSWERVICE_SOURCE_DIRTY",
        "ANSWERVICE_SOURCE_FINGERPRINT",
    ):
        assert f"ARG {key}" in dockerfile
        assert compose.count(f"{key}: ${{{key}:-}}") == 2
        assert f"$env:{key}" in resolver
    assert "org.opencontainers.image.revision" in dockerfile
    assert "io.answervice.source.dirty" in dockerfile
    assert "io.answervice.source.fingerprint" in dockerfile
    assert dockerfile.index("pip install --disable-pip-version-check") < dockerfile.index(
        "ARG ANSWERVICE_SOURCE_REVISION"
    )
    assert "diff --binary --no-ext-diff HEAD" in resolver
    assert "ls-files --others --exclude-standard" in resolver
    assert "'core.quotePath=false'" in resolver
    assert "source-provenance.ps1" in verifier
    assert "docker inspect --format '{{json .Config.Labels}}'" in verifier
    assert "BACKEND_IMAGE_PROVENANCE_READY" in verifier
