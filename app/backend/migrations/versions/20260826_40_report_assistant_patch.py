"""Report Assistant의 검증된 제한 patch를 감사 이력에 추가한다."""

from alembic import op


revision = "20260826_40"
down_revision = "20260826_39"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 요청을 변경하지 않고 대화형 patch JSON만 선택적으로 보존한다."""

    op.execute(
        "ALTER TABLE report_v1.report_assistant_requests "
        "ADD COLUMN report_patch_json jsonb"
    )


def downgrade() -> None:
    """Assistant patch 감사 column만 제거한다."""

    op.execute(
        "ALTER TABLE report_v1.report_assistant_requests DROP COLUMN report_patch_json"
    )
