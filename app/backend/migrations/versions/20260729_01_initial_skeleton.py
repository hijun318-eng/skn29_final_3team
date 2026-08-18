"""Compose 소유 application DDL을 중복하지 않고 단일 Alembic chain을 시작한다."""

from alembic import op


revision = "20260729_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """도메인 table 변경 없이 Alembic revision 존재만 기록한다."""

    # Alembic creates alembic_version. Domain tables remain Compose-owned until their ownership transfer is approved.
    op.execute("SELECT 1")


def downgrade() -> None:
    """도메인 state가 없는 초기 revision이므로 되돌릴 변경이 없다."""

    pass
