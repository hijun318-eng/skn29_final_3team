from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "infrastructure" / "database" / "scripts"
RETENTION_SQL = ROOT / "infrastructure" / "database" / "sql" / "app" / "20-retention.sql"


def test_retention_is_dry_run_by_default_and_requires_explicit_approval():
    wrapper = (SCRIPTS / "retention-app-postgres.ps1").read_text(encoding="utf-8")
    policy = RETENTION_SQL.read_text(encoding="utf-8")

    assert "-Apply -Approval APPLY_RETENTION" in wrapper
    assert "retention-evidence.json" in wrapper
    assert "if ($Apply) { 'true' } else { 'false' }" in wrapper
    assert "\\if :apply" in policy
    assert "interval '30 days'" in policy
    assert "interval '180 days'" in policy
    assert "report_v1.report_block_runs" in policy


def test_daily_backup_is_custom_format_encrypted_and_does_not_keep_plain_dump():
    source = (SCRIPTS / "backup-app-postgres.ps1").read_text(encoding="utf-8")

    assert "pg_dump" in source and "--format custom" in source
    assert "gpg" in source and "AES256" in source
    assert "External encryption key file is required" in source
    assert "Remove-Item -Force -LiteralPath $plainPath" in source
    assert "rpo_target_hours = 24" in source


def test_restore_defaults_to_non_mutating_archive_validation_and_emits_rpo_rto_evidence():
    source = (SCRIPTS / "verify-app-postgres-restore.ps1").read_text(encoding="utf-8")

    assert "pg_restore --list" in source
    assert "RESTORE_TO_ISOLATED_DB" in source
    assert "$TargetDatabase -eq 'app_db'" in source
    assert "mode = 'archive-list-only'" in source
    assert "rpo_target_hours = 24" in source
    assert "rto_target_hours = 4" in source
    assert "restore-evidence.json" in source
    assert "docker cp" in source
    assert "label=com.docker.compose.service=app-postgres" in source
    assert "[string]$EvidenceDirectory" in source
