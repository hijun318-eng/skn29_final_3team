"""Persist manual Report execution and failed block evidence."""

from alembic import op


revision = "20260812_09"
down_revision = "20260812_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE report_v1.report_block_runs "
        "ALTER COLUMN artifact_id DROP NOT NULL, "
        "ALTER COLUMN query_id DROP NOT NULL, "
        "ALTER COLUMN snapshot_checksum DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE report_v1.report_manual_run_commands "
        "DROP CONSTRAINT report_manual_run_commands_status_check"
    )
    op.execute(
        "ALTER TABLE report_v1.report_manual_run_commands "
        "ADD CONSTRAINT report_manual_run_commands_status_check "
        "CHECK (status IN ('queued','success','partial','failed')), "
        "ADD COLUMN run_id uuid UNIQUE REFERENCES report_v1.report_runs(run_id)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE report_v1.report_manual_run_commands "
        "DROP COLUMN run_id, DROP CONSTRAINT report_manual_run_commands_status_check, "
        "ADD CONSTRAINT report_manual_run_commands_status_check CHECK (status = 'queued')"
    )
    op.execute(
        "ALTER TABLE report_v1.report_block_runs "
        "ALTER COLUMN artifact_id SET NOT NULL, "
        "ALTER COLUMN query_id SET NOT NULL, "
        "ALTER COLUMN snapshot_checksum SET NOT NULL"
    )
