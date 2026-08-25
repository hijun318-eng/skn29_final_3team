"""Catalog candidate publisher가 runtime·activation 권한과 분리됐는지 검증한다."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app/backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.adapters.runtime_catalog_candidate_publisher import (  # noqa: E402
    PostgresRuntimeCatalogCandidatePublisher,
)


MIGRATION = (
    ROOT
    / "app/backend/migrations/versions/20260825_36_catalog_publisher_role.py"
)
PROVISION = ROOT / "infrastructure/database/security/provision-app-postgres.sh"
PROVISION_CREDENTIAL = (
    ROOT
    / "infrastructure/database/security/provision-app-catalog-publisher.py"
)
START = ROOT / "infrastructure/database/scripts/start.ps1"


def _credential_provisioner():
    spec = importlib.util.spec_from_file_location(
        "catalog_publisher_credential_provisioner", PROVISION_CREDENTIAL
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_publish_only_adapter_has_no_activation_capability() -> None:
    source = (
        BACKEND / "app/adapters/runtime_catalog_candidate_publisher.py"
    ).read_text(encoding="utf-8")

    assert not hasattr(PostgresRuntimeCatalogCandidatePublisher, "activate")
    assert "runtime_catalog_active_pointer" not in source
    assert "runtime_catalog_activation_receipts" not in source


def test_role_grants_exclude_pointer_and_revoke_runtime_manifest_insert() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    provision = PROVISION.read_text(encoding="utf-8")
    start = START.read_text(encoding="utf-8")

    assert "REVOKE INSERT ON governance.product_release_manifests" in migration
    assert "governance.runtime_catalog_projections" in migration
    assert "governance.product_release_manifests" in migration
    assert "runtime_catalog_active_pointer" not in migration
    assert "runtime_catalog_activation_receipts" not in migration
    assert "roles must differ" in provision
    assert "APP_CATALOG_PUBLISHER_PASSWORD" in provision
    assert "runtime_catalog_active_pointer" not in provision
    assert "Sort-Object -Unique" in start
    assert "roles must differ" in start


def test_publisher_only_upgrade_stops_before_runtime_grant_reconciliation() -> None:
    provision = PROVISION.read_text(encoding="utf-8")
    branch = provision.index("if [ \"$provision_mode\" = 'publisher-only' ]")
    branch_exit = provision.index("exit 0", branch)
    runtime_revoke = provision.index("REVOKE ALL PRIVILEGES ON ALL TABLES", branch)

    assert branch < branch_exit < runtime_revoke
    assert "APP_CATALOG_PUBLISHER_ROLE_PROVISIONED" in provision[branch:branch_exit]
    assert (
        '\\set publisher_password `printf %s "$APP_CATALOG_PUBLISHER_PASSWORD"`'
        in provision[branch:branch_exit]
    )


def test_publisher_credential_provisioning_is_idempotent_and_secret_safe(
    tmp_path: Path,
) -> None:
    module = _credential_provisioner()
    repository = tmp_path / "repository"
    repository.mkdir()
    env_path = tmp_path / "deployment.env"
    env_path.write_text(
        "APP_DB_USER=app_user\nAPP_MIGRATION_USER=app_migration\n",
        encoding="utf-8",
    )

    first = module.provision(env_path, repository=repository)
    _, values = module._read_env(env_path)
    password = values["APP_CATALOG_PUBLISHER_PASSWORD"]
    first_bytes = env_path.read_bytes()
    second = module.provision(env_path, repository=repository)

    assert first["status"] == "PROVISIONED"
    assert second["status"] == "UNCHANGED"
    assert env_path.read_bytes() == first_bytes
    assert len(password) >= 32
    assert password not in json.dumps(first)
    assert password not in json.dumps(second)


def test_publisher_credential_provisioning_rejects_role_collision_before_write(
    tmp_path: Path,
) -> None:
    module = _credential_provisioner()
    repository = tmp_path / "repository"
    repository.mkdir()
    env_path = tmp_path / "deployment.env"
    env_path.write_text(
        "APP_DB_USER=app_user\n"
        "APP_MIGRATION_USER=app_migration\n"
        "APP_CATALOG_PUBLISHER_USER=app_user\n"
        "APP_CATALOG_PUBLISHER_PASSWORD=a-secure-password\n",
        encoding="utf-8",
    )
    before = env_path.read_bytes()

    with pytest.raises(ValueError, match="roles must differ"):
        module.provision(env_path, repository=repository)

    assert env_path.read_bytes() == before
