"""Catalog candidate publisher가 runtime·activation 권한과 분리됐는지 검증한다."""

import sys
from pathlib import Path


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
START = ROOT / "infrastructure/database/scripts/start.ps1"


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
