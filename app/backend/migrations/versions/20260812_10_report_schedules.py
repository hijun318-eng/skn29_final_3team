"""Add owner-scoped Report schedules."""

import os
import re

from alembic import op


revision = "20260812_10"
down_revision = "20260812_09"
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
        CREATE TABLE report_v1.report_schedules (
            schedule_id uuid PRIMARY KEY,
            definition_id uuid NOT NULL,
            definition_version integer NOT NULL,
            cadence varchar(16) NOT NULL CHECK (cadence IN ('daily', 'weekly', 'monthly')),
            timezone_name varchar(64) NOT NULL CHECK (timezone_name = 'Asia/Seoul'),
            next_run_at timestamptz NOT NULL,
            enabled boolean NOT NULL DEFAULT true,
            last_run_id uuid REFERENCES report_v1.report_runs(run_id),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (definition_id, definition_version)
                REFERENCES report_v1.report_definition_versions(definition_id, version)
        )
        """
    )
    role = _runtime_role()
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON report_v1.report_schedules TO {role}")


def downgrade() -> None:
    op.execute("DROP TABLE report_v1.report_schedules")
