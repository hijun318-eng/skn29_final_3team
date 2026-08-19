"""aggregate Analysis Artifact 하나를 Report block 하나로 그대로 보존할 수 있게 한다."""

from alembic import op


revision = "20260814_22"
down_revision = "20260814_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """artifact block type과 aggregate display_kind를 허용하도록 constraint를 확장한다."""

    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "DROP CONSTRAINT report_block_type_check, "
        "ADD CONSTRAINT report_block_type_check "
        "CHECK (block_type IN ('table', 'chart', 'artifact', 'text'))"
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "DROP CONSTRAINT report_block_artifact_check, "
        "ADD CONSTRAINT report_block_artifact_check "
        "CHECK ((block_type IN ('table', 'chart', 'artifact') AND artifact_id IS NOT NULL) "
        "OR (block_type = 'text' AND btrim(content) <> ''))"
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


def downgrade() -> None:
    """새 block type row가 없음을 확인한 뒤 이전 table/chart/text 계약으로 복원한다."""

    # Refuse a lossy downgrade. A saved aggregate block must be explicitly
    # converted by the application before returning to the old schema.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM report_v1.report_blocks WHERE block_type = 'artifact'
            ) THEN
                RAISE EXCEPTION 'aggregate Artifact Report blocks must be converted before downgrade';
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
            (block_type IN ('table', 'chart')
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
        "CHECK ((block_type IN ('table', 'chart') AND artifact_id IS NOT NULL) "
        "OR (block_type = 'text' AND btrim(content) <> ''))"
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "DROP CONSTRAINT report_block_type_check, "
        "ADD CONSTRAINT report_block_type_check "
        "CHECK (block_type IN ('table', 'chart', 'text'))"
    )
