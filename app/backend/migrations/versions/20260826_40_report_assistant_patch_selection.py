"""Report Assistant patch 미리보기와 승인 operation 선택을 세션에 결속한다."""

from alembic import op


revision = "20260826_40"
down_revision = "20260826_39"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 전체 승인을 유지하며 이후 patch의 안전한 미리보기와 선택 인덱스를 저장한다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            ADD COLUMN patch_preview_json jsonb,
            ADD COLUMN approved_operation_indexes smallint[],
            ADD CONSTRAINT report_assistant_operation_selection_check CHECK (
                approved_operation_indexes IS NULL
                OR (
                    cardinality(approved_operation_indexes) BETWEEN 1 AND 12
                    AND array_position(approved_operation_indexes, NULL) IS NULL
                )
            )
        """
    )


def downgrade() -> None:
    """기존 patch와 승인 결과는 유지하고 미리보기·부분 선택 감사값만 제거한다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            DROP CONSTRAINT report_assistant_operation_selection_check,
            DROP COLUMN approved_operation_indexes,
            DROP COLUMN patch_preview_json
        """
    )
