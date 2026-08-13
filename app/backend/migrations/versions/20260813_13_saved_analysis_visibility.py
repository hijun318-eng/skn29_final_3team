"""Separate explicitly saved analyses from transient request definitions."""

from alembic import op


revision = "20260813_13"
down_revision = "20260812_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE analysis_v1.analysis_definitions "
        "ADD COLUMN is_saved boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE analysis_v1.analysis_definitions "
        "DISABLE TRIGGER analysis_definitions_immutable"
    )
    op.execute(
        "UPDATE analysis_v1.analysis_definitions "
        "SET is_saved = true WHERE title <> 'Analysis request'"
    )
    op.execute(
        "ALTER TABLE analysis_v1.analysis_definitions "
        "ENABLE TRIGGER analysis_definitions_immutable"
    )
    op.execute(
        "CREATE INDEX idx_analysis_definitions_saved_owner_created "
        "ON analysis_v1.analysis_definitions(owner_id, created_at DESC) "
        "WHERE is_saved"
    )


def downgrade() -> None:
    op.execute("DROP INDEX analysis_v1.idx_analysis_definitions_saved_owner_created")
    op.execute("ALTER TABLE analysis_v1.analysis_definitions DROP COLUMN is_saved")
