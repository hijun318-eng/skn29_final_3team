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
            ".env.example",
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


def test_root_include_applies_only_the_runtime_identity_override():
    root = COMPOSE.read_text(encoding="utf-8")
    override = OVERRIDE.read_text(encoding="utf-8")

    assert "- infrastructure/database/compose.yml" in root
    assert "- app/backend/compose.fragment.yml" in root
    assert "- app/enterprise-react/compose.fragment.yml" in root
    assert "- infrastructure/database/datahub/compose.consumer.yml" in root
    assert "- compose.app-postgres.override.yml" in root
    assert override == (
        "services:\n"
        "  app-postgres:\n"
        "    container_name: ${APP_POSTGRES_CONTAINER_NAME:-answervice-app-postgres}\n"
        '    ports: !override ["${APP_POSTGRES_BIND_ADDRESS:-127.0.0.1}:${APP_POSTGRES_PORT:-25432}:5432"]\n'
        "  backend:\n"
        "    container_name: ${BACKEND_CONTAINER_NAME:-answervice-backend}\n"
        '    ports: !override ["${BACKEND_BIND_ADDRESS:-127.0.0.1}:${BACKEND_PORT:-28000}:8000"]\n'
    )


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
    assert service["depends_on"]["app-postgres-provision"]["condition"] == "service_completed_successfully"


def test_app_postgres_provision_repairs_existing_volume_before_backend():
    config = _config()
    database = config["services"]["app-postgres"]
    provision = config["services"]["app-postgres-provision"]

    assert any(volume["target"] == "/docker-entrypoint-initdb.d/05-provision-roles.sh" for volume in database["volumes"])
    assert provision["environment"]["PGHOST"] == "app-postgres"
    assert provision["depends_on"]["app-postgres"]["condition"] == "service_healthy"
    assert provision["entrypoint"] == ["sh", "/security/provision-app-postgres.sh"]


def test_provision_transfers_schema_table_and_sequence_ownership():
    script = (ROOT / "infrastructure/database/security/provision-app-postgres.sh").read_text(encoding="utf-8")

    assert "ALTER TABLE %I.%I OWNER TO %I" in script
    assert "ALTER SEQUENCE %I.%I OWNER TO %I" in script
    assert "ALTER SCHEMA %I OWNER TO %I" in script
