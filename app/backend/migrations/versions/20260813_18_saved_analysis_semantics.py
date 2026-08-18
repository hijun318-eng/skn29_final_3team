"""저장된 Analysis에 semantic request와 parameter schema snapshot을 추가한다."""

from alembic import op


revision = "20260813_18"
down_revision = "20260813_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 row를 빈 객체로 안전하게 backfill하며 두 semantic JSON column을 추가한다."""

    op.execute(
        "ALTER TABLE analysis_v1.analysis_definitions "
        "ADD COLUMN semantic_request_json jsonb NOT NULL DEFAULT '{}'::jsonb, "
        "ADD COLUMN parameter_schema_json jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
def downgrade() -> None:
    """parameter schema와 semantic request snapshot column을 함께 제거한다."""

    op.execute(
        "ALTER TABLE analysis_v1.analysis_definitions "
        "DROP COLUMN parameter_schema_json, DROP COLUMN semantic_request_json"
    )
