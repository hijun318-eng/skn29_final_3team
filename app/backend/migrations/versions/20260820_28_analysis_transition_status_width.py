"""분석 상태 전이가 전체 typed 상태 이름을 손실 없이 저장하도록 폭을 확장한다."""

from alembic import op


revision = "20260820_28"
down_revision = "20260820_27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """``CLARIFICATION_REQUIRED``를 포함하도록 전이 상태 column을 확장한다."""

    op.execute(
        "ALTER TABLE chat.analysis_state_transitions "
        "ALTER COLUMN from_status TYPE varchar(32), "
        "ALTER COLUMN to_status TYPE varchar(32)"
    )


def downgrade() -> None:
    """긴 보완 요청 상태를 이전 저장 표현으로 바꾼 뒤 폭을 복원한다."""

    op.execute(
        "UPDATE chat.analysis_state_transitions "
        "SET from_status = 'CLARIFYING' "
        "WHERE from_status = 'CLARIFICATION_REQUIRED'"
    )
    op.execute(
        "UPDATE chat.analysis_state_transitions "
        "SET to_status = 'CLARIFYING' "
        "WHERE to_status = 'CLARIFICATION_REQUIRED'"
    )
    op.execute(
        "ALTER TABLE chat.analysis_state_transitions "
        "ALTER COLUMN from_status TYPE varchar(20), "
        "ALTER COLUMN to_status TYPE varchar(20)"
    )
