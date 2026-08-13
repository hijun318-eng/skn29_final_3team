from alembic import op


revision = "20260813_17"
down_revision = "20260813_16"
branch_labels = None
depends_on = None


_CONSTRAINT = "ck_chat_analysis_requests_error_type"
_BASE_ERROR_TYPES = (
    "'AMBIGUOUS','UNSUPPORTED','PERMISSION','QUERY','PARTIAL',"
    "'INSUFFICIENT_EVIDENCE'"
)


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE chat.analysis_requests "
        f"DROP CONSTRAINT IF EXISTS {_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE chat.analysis_requests ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (error_type IS NULL OR error_type IN ({_BASE_ERROR_TYPES},'PERSISTENCE'))"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE chat.analysis_requests SET error_type = 'QUERY' "
        "WHERE error_type = 'PERSISTENCE'"
    )
    op.execute(
        f"ALTER TABLE chat.analysis_requests "
        f"DROP CONSTRAINT IF EXISTS {_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE chat.analysis_requests ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK (error_type IS NULL OR error_type IN ({_BASE_ERROR_TYPES}))"
    )
