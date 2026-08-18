"""Analysis request 상태 계약에 명시적인 CANCELLED 종결 상태를 추가한다."""

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
    """기존 상태 constraint를 CANCELLED를 포함하는 계약으로 원자 교체한다."""

    op.execute(
        f"ALTER TABLE chat.analysis_requests "
        f"DROP CONSTRAINT IF EXISTS {_STATUS_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE chat.analysis_requests ADD CONSTRAINT {_STATUS_CONSTRAINT} "
        f"CHECK (status IN ({_BASE_STATUSES},'CANCELLED'))"
    )


def downgrade() -> None:
    """CANCELLED row가 없음을 확인한 뒤 이전 상태 constraint로 되돌린다."""

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
