from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_retention_redacts_payloads_and_preserves_immutable_definitions():
    policy = (ROOT / "infrastructure/database/sql/app/20-retention.sql").read_text(encoding="utf-8")

    assert "approved_report_snapshot_90d" in policy
    assert "interval '90 days'" in policy
    assert "artifact_snapshot_30d" in policy
    assert "audit_metadata_archive_180d" in policy
    assert "INSERT INTO governance.audit_events_archive" in policy
    assert "SET data_snapshot_json = '{}'::jsonb" in policy
    for forbidden in (
        "DELETE FROM analysis_v1.analysis_run_links",
        "DELETE FROM context.context_packages",
        "DELETE FROM chat.analysis_requests",
    ):
        assert forbidden not in policy


def test_audit_archive_is_append_only_and_follows_current_head():
    migration = (ROOT / "app/backend/migrations/versions/20260812_12_retention_archive.py").read_text(encoding="utf-8")

    assert 'down_revision = "20260812_11"' in migration
    assert "audit_events_archive_append_only" in migration
    assert "BEFORE UPDATE OR DELETE" in migration


def test_daily_maintenance_is_encrypted_backup_then_dry_run_retention():
    scripts = ROOT / "infrastructure/database/scripts"
    runner = (scripts / "run-app-postgres-maintenance.ps1").read_text(encoding="utf-8")
    installer = (scripts / "install-app-postgres-maintenance-task.ps1").read_text(encoding="utf-8")
    backup = (scripts / "backup-app-postgres.ps1").read_text(encoding="utf-8")

    assert runner.index("backup-app-postgres.ps1") < runner.index("retention-app-postgres.ps1")
    assert "-Apply" not in runner and "APPLY_RETENTION" not in runner
    assert "-EvidenceDirectory $EvidenceDirectory" in runner
    assert "New-ScheduledTaskTrigger -Daily" in installer
    assert "-StartWhenAvailable -MultipleInstances IgnoreNew" in installer
    assert "External encryption key file is required." in installer
    assert "cipher-algo AES256" in backup
    assert "[System.IO.Path]::GetFileName(\"$encryptedPath.json\")" in backup
