from alembic import op


revision = "20260813_14"
down_revision = "20260813_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM query.query_executions
                WHERE generation_mode = 'FALLBACK'
            ) THEN
                RAISE EXCEPTION 'FALLBACK query history must be reviewed before migration';
            END IF;
        END
        $$
        """
    )
    op.execute(
        "ALTER TABLE query.query_executions "
        "DROP CONSTRAINT query_executions_generation_mode_check"
    )
    op.execute(
        "UPDATE query.query_executions SET generation_mode = 'LLM' "
        "WHERE generation_mode = 'SLLM'"
    )
    op.execute(
        "ALTER TABLE query.query_executions "
        "ADD CONSTRAINT query_executions_generation_mode_check "
        "CHECK (generation_mode IN ('LLM', 'TEMPLATE'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE query.query_executions "
        "DROP CONSTRAINT query_executions_generation_mode_check"
    )
    op.execute(
        "UPDATE query.query_executions SET generation_mode = 'SLLM' "
        "WHERE generation_mode = 'LLM'"
    )
    op.execute(
        "ALTER TABLE query.query_executions "
        "ADD CONSTRAINT query_executions_generation_mode_check "
        "CHECK (generation_mode IN ('SLLM', 'TEMPLATE', 'FALLBACK'))"
    )
