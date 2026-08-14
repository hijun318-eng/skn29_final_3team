import os
import re

from alembic import op


revision = "20260813_15"
down_revision = "20260813_14"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS security")
    op.execute("""
        CREATE TABLE security.auth_sessions (
            token_sha256 char(64) PRIMARY KEY,
            subject uuid NOT NULL,
            role varchar(32) NOT NULL CHECK (role IN ('hotel_analyst', 'report_admin', 'data_admin')),
            issued_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL CHECK (expires_at > issued_at),
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_auth_sessions_active ON security.auth_sessions (expires_at) WHERE revoked_at IS NULL")
    role = _runtime_role()
    op.execute(f"GRANT USAGE ON SCHEMA security TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON security.auth_sessions TO {role}")


def downgrade() -> None:
    role = _runtime_role()
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON security.auth_sessions FROM {role}")
    op.execute(f"REVOKE USAGE ON SCHEMA security FROM {role}")
    op.execute("DROP TABLE security.auth_sessions")
