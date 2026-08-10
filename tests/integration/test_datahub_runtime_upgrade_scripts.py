from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UPGRADE = ROOT / "infrastructure/database/scripts/upgrade-datahub-runtime.ps1"
ROLLBACK = ROOT / "infrastructure/database/scripts/rollback-datahub-runtime.ps1"


def test_upgrade_is_exact_and_resource_gated() -> None:
    source = UPGRADE.read_text(encoding="utf-8")
    assert "BLOCKED_INSUFFICIENT_MEMORY" in source
    assert "BACKUP_NOT_APPLICABLE_NEW_RUNTIME" in source
    assert "RandomNumberGenerator]::Create()" in source
    assert "down --volumes" not in source
    assert "docker system prune" not in source
    assert "data-hub-test" not in source
    assert "At least 8 GB free host memory" in source


def test_rollback_preserves_volumes_and_uses_exact_services() -> None:
    source = ROLLBACK.read_text(encoding="utf-8")
    assert "@services" in source
    assert "Volumes" not in source
    assert " down" not in source
    assert " rm -f" in source
    assert "VOLUMES_PRESERVED" in source
