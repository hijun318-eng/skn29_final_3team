"""Persist owner-scoped real analysis stage events."""

import os
import re

from alembic import op


revision = "20260812_11"
down_revision = "20260812_10"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE chat.analysis_stage_events (
            request_id uuid NOT NULL REFERENCES chat.analysis_requests(request_id),
            sequence_no integer NOT NULL CHECK (sequence_no > 0),
            stage varchar(16) NOT NULL CHECK (
                stage IN ('DATAHUB','NODE1','G1','NODE2','G2','TRINO','G3','NODE3','ARTIFACT')
            ),
            outcome varchar(16) NOT NULL CHECK (
                outcome IN ('STARTED','PASSED','SKIPPED','BLOCKED','FAILED')
            ),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (request_id, sequence_no)
        )
        """
    )
    role = _runtime_role()
    op.execute(f"GRANT SELECT, INSERT ON chat.analysis_stage_events TO {role}")


def downgrade() -> None:
    role = _runtime_role()
    op.execute(f"REVOKE SELECT, INSERT ON chat.analysis_stage_events FROM {role}")
    op.execute("DROP TABLE chat.analysis_stage_events")
