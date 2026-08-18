"""Query generation mode를 검증된 LLM 경로로 축소하고 과거 fallback을 차단한다."""

from alembic import op


revision = "20260813_14"
down_revision = "20260813_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """live FALLBACK history가 없음을 확인한 뒤 허용 mode를 LLM으로 제한한다."""

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
    """migration chain 복원용 과거 enum만 되살리며 runtime fallback을 구현하지 않는다."""

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
