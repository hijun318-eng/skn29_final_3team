from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "infrastructure" / "database" / "compose.yml"
MARKER = "/var/opt/mssql/.answervice_schema_initialized"
SQLCMD = "/opt/mssql-tools18/bin/sqlcmd"


def _crm_service() -> str:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    return compose.split("  crm-mssql:\n", 1)[1].split(
        "  facility-clickhouse:\n", 1
    )[0]


def _is_seed_ready(command: str) -> bool:
    marker_index = command.find(f"test -f {MARKER}")
    sqlcmd_index = command.find(SQLCMD)
    return marker_index >= 0 and sqlcmd_index > marker_index and "&&" in command[
        marker_index:sqlcmd_index
    ]


def test_crm_health_requires_seed_marker_and_database_probe():
    service = _crm_service()
    health_command = next(
        line.strip() for line in service.splitlines() if line.strip().startswith("test:")
    )

    assert _is_seed_ready(health_command)
    assert not _is_seed_ready(f"test -f {MARKER}")
    assert not _is_seed_ready(f'{SQLCMD} -Q "SELECT 1"')


def test_crm_compose_identity_is_unchanged():
    service = _crm_service()

    assert "container_name: crm-mssql" in service
    assert (
        'image: "mcr.microsoft.com/mssql/server:2022-CU17-ubuntu-22.04@'
        'sha256:d252932ef839c24c61c1139cc98f69c85ca774fa7c6bfaaa0015b7eb02b9dc87"'
        in service
    )
    assert 'entrypoint: ["/bin/bash", "/bootstrap/entrypoint.sh"]' in service
    assert 'ports: ["127.0.0.1:11433:1433"]' in service
    assert "- crm-mssql-data:/var/opt/mssql" in service
