"""Allow one aggregate Analysis Artifact to remain one Report block."""

from alembic import op


revision = "20260814_22"
down_revision = "20260814_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
