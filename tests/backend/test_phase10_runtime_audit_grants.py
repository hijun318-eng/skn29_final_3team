from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "app"
    / "backend"
    / "migrations"
    / "versions"
    / "20260823_35_phase10_runtime_audit_grants.py"
)


def test_phase10_runtime_audit_grant_is_append_only() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "down_revision = \"20260823_34\"" in source
    assert "GRANT SELECT, INSERT ON governance.audit_events" in source
    assert "GRANT UPDATE" not in source
    assert "GRANT DELETE" not in source
    assert "REVOKE SELECT, INSERT ON governance.audit_events" in source
