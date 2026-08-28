"""실패한 Report Assistant 요청에서 새 세션으로 이어지는 재시도 lineage를 기록한다."""

from alembic import op


revision = "20260826_44"
down_revision = "20260826_43"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 실패 이력을 보존하며 재시도 원본과 생성 시각을 선택 필드로 추가한다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            ADD COLUMN retry_of_assistant_request_id uuid
                REFERENCES report_v1.report_assistant_requests(assistant_request_id),
            ADD COLUMN retry_created_at timestamptz,
            ADD CONSTRAINT report_assistant_retry_fields_check CHECK (
                (retry_of_assistant_request_id IS NULL AND retry_created_at IS NULL)
                OR (retry_of_assistant_request_id IS NOT NULL AND retry_created_at IS NOT NULL)
            );
        CREATE UNIQUE INDEX report_assistant_retry_source_idx
            ON report_v1.report_assistant_requests(retry_of_assistant_request_id)
            WHERE retry_of_assistant_request_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    """재시도 lineage만 제거하고 원본·자식 Assistant 세션은 보존한다."""

    op.execute(
        """
        DROP INDEX report_v1.report_assistant_retry_source_idx;
        ALTER TABLE report_v1.report_assistant_requests
            DROP CONSTRAINT report_assistant_retry_fields_check,
            DROP COLUMN retry_created_at,
            DROP COLUMN retry_of_assistant_request_id;
        """
    )
