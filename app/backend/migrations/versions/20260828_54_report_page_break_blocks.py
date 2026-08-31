"""명시적 A4 페이지 경계를 Report revision block으로 보존한다."""

from alembic import op


revision = "20260828_54"
down_revision = "20260828_53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 block을 유지하면서 내용·lineage 없는 page_break 유형만 추가한다."""

    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "DROP CONSTRAINT report_block_type_check, "
        "ADD CONSTRAINT report_block_type_check "
        "CHECK (block_type IN ('table', 'chart', 'artifact', 'text', 'page_break'))"
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "DROP CONSTRAINT report_block_artifact_check, "
        "ADD CONSTRAINT report_block_artifact_check CHECK ("
        "(block_type IN ('table', 'chart', 'artifact') AND artifact_id IS NOT NULL) "
        "OR (block_type = 'text' AND btrim(content) <> '') "
        "OR (block_type = 'page_break' AND artifact_id IS NULL AND query_id IS NULL "
        "AND content = '' AND x = 0 AND w = 12 AND h = 1))"
    )
    op.execute(
        """
        ALTER TABLE report_v1.report_blocks
        DROP CONSTRAINT report_block_replay_lineage_check,
        ADD CONSTRAINT report_block_replay_lineage_check CHECK (
            (block_type IN ('table', 'chart', 'artifact')
             AND analysis_definition_id IS NOT NULL
             AND analysis_definition_version IS NOT NULL)
            OR
            (block_type IN ('text', 'page_break')
             AND analysis_definition_id IS NULL
             AND analysis_definition_version IS NULL)
        ) NOT VALID
        """
    )


def downgrade() -> None:
    """page_break가 없을 때만 이전 block 계약으로 안전하게 복원한다."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM report_v1.report_blocks WHERE block_type = 'page_break'
            ) THEN
                RAISE EXCEPTION 'page break Report blocks must be removed before downgrade';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        ALTER TABLE report_v1.report_blocks
        DROP CONSTRAINT report_block_replay_lineage_check,
        ADD CONSTRAINT report_block_replay_lineage_check CHECK (
            (block_type IN ('table', 'chart', 'artifact')
             AND analysis_definition_id IS NOT NULL
             AND analysis_definition_version IS NOT NULL)
            OR
            (block_type = 'text'
             AND analysis_definition_id IS NULL
             AND analysis_definition_version IS NULL)
        ) NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "DROP CONSTRAINT report_block_artifact_check, "
        "ADD CONSTRAINT report_block_artifact_check "
        "CHECK ((block_type IN ('table', 'chart', 'artifact') AND artifact_id IS NOT NULL) "
        "OR (block_type = 'text' AND btrim(content) <> ''))"
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "DROP CONSTRAINT report_block_type_check, "
        "ADD CONSTRAINT report_block_type_check "
        "CHECK (block_type IN ('table', 'chart', 'artifact', 'text'))"
    )
