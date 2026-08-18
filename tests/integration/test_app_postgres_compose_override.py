import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.yml"
OVERRIDE = ROOT / "compose.app-postgres.override.yml"


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


def test_canonical_env_example_covers_datahub_runtime_secrets():
    env_keys = {
        line.split("=", 1)[0]
        for line in (ROOT / "infrastructure/database/.env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }

    assert {
        "DATAHUB_MYSQL_PASSWORD",
        "DATAHUB_MYSQL_ROOT_PASSWORD",
        "DATAHUB_SECRET",
        "DATAHUB_TOKEN_SERVICE_SALT",
        "DATAHUB_TOKEN_SERVICE_SIGNING_KEY",
    } <= env_keys
    assert not (ROOT / ".env.example").exists()


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
