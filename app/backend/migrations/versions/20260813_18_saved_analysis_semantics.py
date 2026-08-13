from alembic import op


revision = "20260813_18"
down_revision = "20260813_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE analysis_v1.analysis_definitions "
        "ADD COLUMN semantic_request_json jsonb NOT NULL DEFAULT '{}'::jsonb, "
        "ADD COLUMN parameter_schema_json jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
def downgrade() -> None:
    op.execute(
        "ALTER TABLE analysis_v1.analysis_definitions "
        "DROP COLUMN parameter_schema_json, DROP COLUMN semantic_request_json"
    )
