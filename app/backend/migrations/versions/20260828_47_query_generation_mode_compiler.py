"""typed SQL compiler 실행을 LLM과 구분해 query 영수증에 기록한다."""

from alembic import op


revision = "20260828_47"
down_revision = "20260826_46"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 값을 보존하면서 COMPILER provenance만 허용 값에 추가한다."""

    op.execute(
        "ALTER TABLE query.query_executions "
        "DROP CONSTRAINT query_executions_generation_mode_check"
    )
    op.execute(
        "ALTER TABLE query.query_executions "
        "ADD CONSTRAINT query_executions_generation_mode_check "
        "CHECK (generation_mode IN ('LLM', 'TEMPLATE', 'COMPILER'))"
    )


def downgrade() -> None:
    """COMPILER 영수증이 있으면 provenance를 훼손하지 않고 downgrade를 거부한다."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM query.query_executions
                WHERE generation_mode = 'COMPILER'
            ) THEN
                RAISE EXCEPTION
                    'COMPILER query history must be preserved before downgrade';
            END IF;
        END $$
        """
    )
    op.execute(
        "ALTER TABLE query.query_executions "
        "DROP CONSTRAINT query_executions_generation_mode_check"
    )
    op.execute(
        "ALTER TABLE query.query_executions "
        "ADD CONSTRAINT query_executions_generation_mode_check "
        "CHECK (generation_mode IN ('LLM', 'TEMPLATE'))"
    )
