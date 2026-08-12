from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "backend"))
from app.recovery_status import recovery_status


def test_recovery_status_reads_sanitized_latest_manifests(tmp_path, monkeypatch):
    monkeypatch.setenv("RECOVERY_EVIDENCE_DIRECTORY", str(tmp_path))
    (tmp_path / "retention-evidence.json").write_text(
        json.dumps({"executed_at_utc": "2026-08-12T00:00:00Z", "status": "dry_run", "secret": "hidden"}), encoding="utf-8"
    )
    (tmp_path / "app-postgres.dump.gpg.json").write_text(
        json.dumps({"created_at_utc": "2026-08-12T00:00:00Z", "backup_file": "/secret/backup.gpg", "sha256": "a" * 64}), encoding="utf-8"
    )
    (tmp_path / "app-postgres.dump.gpg.restore-evidence.json").write_text(
        json.dumps({"verified_at_utc": "2026-08-12T01:00:00Z", "mode": "archive-list-only", "backup_sha256": "a" * 64, "backup_age_hours": 1, "restore_duration_hours": 0.1, "rpo_target_hours": 24, "rpo_passed": True, "rto_target_hours": 4, "rto_passed": True, "key_path": "/secret/key"}), encoding="utf-8"
    )

    status = recovery_status(datetime(2026, 8, 12, 2, tzinfo=timezone.utc))
    serialized = json.dumps(status, default=str)

    assert status["retention"]["status"] == "dry_run"
    assert status["backup"]["age_hours"] == 2
    assert status["backup"]["rpo_passed"] is True
    assert status["restore"]["mode"] == "archive-list-only"
    assert status["restore"]["status"] == "archive_validated"
    assert status["restore"]["rto_passed"] is True
    assert "/secret" not in serialized
    assert "backup_file" not in serialized
    assert "key_path" not in serialized


def test_recovery_status_is_honest_when_unconfigured_or_not_run(tmp_path, monkeypatch):
    monkeypatch.delenv("RECOVERY_EVIDENCE_DIRECTORY", raising=False)
    assert recovery_status()["backup"]["status"] == "unknown"

    monkeypatch.setenv("RECOVERY_EVIDENCE_DIRECTORY", str(tmp_path))
    status = recovery_status()
    assert status["retention"]["status"] == "not_run"
    assert status["backup"]["status"] == "not_run"
    assert status["restore"]["mode"] == "not_run"
