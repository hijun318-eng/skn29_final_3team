"""Report Assistant가 검증한 새 Artifact의 query·checksum lineage를 보존한다."""

from alembic import op


revision = "20260824_30"
down_revision = "20260824_29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """검증된 결과 Artifact와 함께 query ID 및 SHA-256 checksum을 저장한다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            ADD COLUMN result_query_id varchar(255),
            ADD COLUMN result_artifact_checksum varchar(64),
            ADD CONSTRAINT report_assistant_result_lineage_check CHECK (
                (result_artifact_id IS NULL AND result_query_id IS NULL
                    AND result_artifact_checksum IS NULL)
                OR (result_artifact_id IS NOT NULL AND result_query_id IS NOT NULL
                    AND result_artifact_checksum ~ '^[0-9a-f]{64}$')
            )
        """
    )


def downgrade() -> None:
    """검증 결과 lineage 확장만 제거하고 기존 Assistant 세션을 보존한다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            DROP CONSTRAINT report_assistant_result_lineage_check,
            DROP COLUMN result_artifact_checksum,
            DROP COLUMN result_query_id
        """
    )
