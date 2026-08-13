from alembic import op


revision = "20260813_16"
down_revision = "20260813_15"
branch_labels = None
depends_on = None


_STATUS_CONSTRAINT = "ck_chat_analysis_requests_status"
_BASE_STATUSES = (
    "'RECEIVED','CLARIFYING','CONTEXT_BUILDING','GENERATING','VALIDATING',"
    "'RUNNING','SUCCEEDED','PARTIAL','FAILED','DENIED'"
)


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE chat.analysis_requests "
        f"DROP CONSTRAINT IF EXISTS {_STATUS_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE chat.analysis_requests ADD CONSTRAINT {_STATUS_CONSTRAINT} "
        f"CHECK (status IN ({_BASE_STATUSES},'CANCELLED'))"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE chat.analysis_requests SET status = 'FAILED' "
        "WHERE status = 'CANCELLED'"
    )
    op.execute(
        f"ALTER TABLE chat.analysis_requests "
        f"DROP CONSTRAINT IF EXISTS {_STATUS_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE chat.analysis_requests ADD CONSTRAINT {_STATUS_CONSTRAINT} "
        f"CHECK (status IN ({_BASE_STATUSES}))"
    )
