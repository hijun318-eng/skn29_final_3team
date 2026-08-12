"""Add durable Report command claim and completion state."""

import os
import re

from alembic import op


revision = "20260812_09"
down_revision = "20260812_08"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    op.execute("ALTER TABLE report_v1.report_manual_run_commands DROP CONSTRAINT report_manual_run_commands_status_check")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands ADD CONSTRAINT report_manual_run_commands_status_check CHECK (status IN ('queued', 'running', 'success', 'partial', 'failed'))")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands ADD COLUMN run_id uuid REFERENCES report_v1.report_runs(run_id)")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands ADD COLUMN claimed_at timestamptz")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands ADD COLUMN completed_at timestamptz")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands ADD COLUMN error_message_redacted text")
    op.execute(
        """
        ALTER TABLE report_v1.report_manual_run_commands
        ADD CONSTRAINT report_command_state_check CHECK (
            (status = 'queued' AND claimed_at IS NULL AND completed_at IS NULL AND run_id IS NULL)
            OR (status = 'running' AND claimed_at IS NOT NULL AND completed_at IS NULL AND run_id IS NULL)
            OR (status IN ('success', 'partial') AND claimed_at IS NOT NULL AND completed_at IS NOT NULL AND run_id IS NOT NULL)
            OR (status = 'failed' AND claimed_at IS NOT NULL AND completed_at IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX report_command_queue_idx ON report_v1.report_manual_run_commands(status, created_at)")
    role = _runtime_role()
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON report_v1.report_runs, report_v1.report_block_runs TO {role}")


def downgrade() -> None:
    op.execute("DROP INDEX report_v1.report_command_queue_idx")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands DROP CONSTRAINT report_command_state_check")
    for column in ("error_message_redacted", "completed_at", "claimed_at", "run_id"):
        op.execute(f"ALTER TABLE report_v1.report_manual_run_commands DROP COLUMN {column}")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands DROP CONSTRAINT report_manual_run_commands_status_check")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands ADD CONSTRAINT report_manual_run_commands_status_check CHECK (status = 'queued')")
