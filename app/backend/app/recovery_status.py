from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _read_latest(directory: Path, pattern: str) -> dict | None:
    files = sorted(directory.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        value = json.loads(files[0].read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _hash(value: object) -> str | None:
    text = str(value or "")
    return text.lower() if _SHA256.fullmatch(text) else None


def recovery_status(now: datetime | None = None) -> dict:
    generated_at = now or datetime.now(timezone.utc)
    configured = os.getenv("RECOVERY_EVIDENCE_DIRECTORY", "").strip()
    base = Path(configured) if configured else None
    if base is None or not base.is_dir():
        state = "unknown" if base is None else "not_run"
        return {
            "generated_at": generated_at,
            "retention": {"status": state, "last_run_at": None},
            "backup": {"status": state, "created_at": None, "age_hours": None, "sha256": None, "rpo_target_hours": 24, "rpo_passed": None},
            "restore": {"status": state, "verified_at": None, "mode": "unknown" if state == "unknown" else "not_run", "backup_age_hours": None, "restore_duration_hours": None, "rpo_target_hours": 24, "rpo_passed": None, "rto_target_hours": 4, "rto_passed": None, "backup_sha256": None},
        }

    retention = _read_latest(base, "retention-evidence*.json")
    backup = _read_latest(base, "*.dump.gpg.json")
    restore = _read_latest(base, "*.restore-evidence.json")
    retention_at = _timestamp((retention or {}).get("executed_at_utc"))
    backup_at = _timestamp((backup or {}).get("created_at_utc"))
    verified_at = _timestamp((restore or {}).get("verified_at_utc"))
    age = round((generated_at - backup_at).total_seconds() / 3600, 3) if backup_at else None
    backup_hash = _hash((backup or {}).get("sha256"))
    restore_hash = _hash((restore or {}).get("backup_sha256"))
    retention_status = (retention or {}).get("status")
    if retention_status not in {"dry_run", "applied"}:
        retention_status = "unknown" if retention == {} else "not_run"
    restore_mode = (restore or {}).get("mode")
    if restore_mode not in {"archive-list-only", "isolated-restore"}:
        restore_mode = "unknown" if restore == {} else "not_run"
    return {
        "generated_at": generated_at,
        "retention": {
            "status": retention_status,
            "last_run_at": retention_at,
        },
        "backup": {
            "status": "available" if backup_at and backup_hash else "unknown" if backup == {} else "not_run",
            "created_at": backup_at,
            "age_hours": age,
            "sha256": backup_hash,
            "rpo_target_hours": 24,
            "rpo_passed": age <= 24 if age is not None else None,
        },
        "restore": {
            "status": "verified" if verified_at and restore_hash else "unknown" if restore == {} else "not_run",
            "verified_at": verified_at,
            "mode": restore_mode,
            "backup_age_hours": (restore or {}).get("backup_age_hours"),
            "restore_duration_hours": (restore or {}).get("restore_duration_hours"),
            "rpo_target_hours": (restore or {}).get("rpo_target_hours", 24),
            "rpo_passed": (restore or {}).get("rpo_passed"),
            "rto_target_hours": (restore or {}).get("rto_target_hours", 4),
            "rto_passed": (restore or {}).get("rto_passed"),
            "backup_sha256": restore_hash,
        },
    }
