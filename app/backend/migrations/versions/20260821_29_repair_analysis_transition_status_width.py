"""최신 revision 표기와 실제 분석 상태 column 폭 사이의 drift를 복구한다."""

from alembic import op


revision = "20260821_29"
down_revision = "20260820_28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """전체 typed 상태를 저장하도록 두 전이 column의 실제 폭을 다시 보장한다."""

    # 운영 DB가 이전 head로 stamp된 뒤 bootstrap schema와 섞인 경우에도
    # revision 번호만 신뢰하지 않고 실제 persistence 계약을 원상 복구한다.
    op.execute(
        "ALTER TABLE chat.analysis_state_transitions "
        "ALTER COLUMN from_status TYPE varchar(32), "
        "ALTER COLUMN to_status TYPE varchar(32)"
    )


def downgrade() -> None:
    """긴 상태값을 호환 표현으로 축약한 뒤 직전 폭으로 되돌린다."""

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
