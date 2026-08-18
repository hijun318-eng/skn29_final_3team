"""Report replay lineage와 typed block failure evidence를 영속화한다."""

from alembic import op


revision = "20260814_20"
down_revision = "20260814_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Analysis definition·request·policy lineage와 typed failure column을 추가한다."""

    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "ADD COLUMN analysis_definition_id uuid, "
        "ADD COLUMN analysis_definition_version integer"
    )
    op.execute(
        "ALTER TABLE report_v1.report_block_runs "
        "ADD COLUMN request_id uuid REFERENCES chat.analysis_requests(request_id), "
        "ADD COLUMN policy_version text, "
        "ADD COLUMN failure_code varchar(64), "
        "ADD COLUMN failure_message varchar(300)"
    )
    op.execute(
        "ALTER TABLE report_v1.report_manual_run_commands "
        "DROP CONSTRAINT report_manual_run_commands_status_check, "
        "ADD CONSTRAINT report_manual_run_commands_status_check "
        "CHECK (status IN ('queued','running','success','partial','failed','cancelled'))"
    )
    op.execute(
        """
        UPDATE report_v1.report_block_runs br
        SET request_id = a.request_id,
            policy_version = r.sql_policy_version
        FROM artifact.analysis_artifacts a
        JOIN chat.analysis_requests r ON r.request_id = a.request_id
        WHERE br.artifact_id = a.artifact_id
        """
    )
    op.execute(
        """
        UPDATE report_v1.report_block_runs
        SET failure_code = 'REPLAY_UNAVAILABLE',
            failure_message = 'This legacy block did not contain replay evidence.'
        WHERE status IN ('failed', 'cancelled')
          AND (failure_code IS NULL OR failure_message IS NULL)
        """
    )

    # Approved Report versions are immutable at runtime. The migration is the only
    # place that may attach their already-persisted source Analysis lineage.
    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "DISABLE TRIGGER report_approved_blocks_immutable"
    )
    op.execute(
        """
        UPDATE report_v1.report_blocks b
        SET analysis_definition_id = l.definition_id,
            analysis_definition_version = l.definition_version
        FROM artifact.analysis_artifacts a
        JOIN analysis_v1.analysis_run_links l ON l.request_id = a.request_id
        WHERE b.artifact_id = a.artifact_id
          AND b.block_type IN ('table', 'chart')
        """
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "ENABLE TRIGGER report_approved_blocks_immutable"
    )
    op.execute(
        """
        ALTER TABLE report_v1.report_blocks
        ADD CONSTRAINT report_block_analysis_definition_fk
            FOREIGN KEY (analysis_definition_id, analysis_definition_version)
            REFERENCES analysis_v1.analysis_definitions(definition_id, version),
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
        """
        ALTER TABLE report_v1.report_block_runs
        ADD CONSTRAINT report_block_run_failure_check CHECK (
            (status = 'success'
             AND request_id IS NOT NULL
             AND artifact_id IS NOT NULL
             AND query_id IS NOT NULL
             AND snapshot_checksum IS NOT NULL
             AND failure_code IS NULL
             AND failure_message IS NULL)
            OR
            (status = 'partial'
             AND request_id IS NOT NULL
             AND artifact_id IS NOT NULL
             AND query_id IS NOT NULL
             AND snapshot_checksum IS NOT NULL)
            OR
            (status IN ('failed', 'cancelled')
             AND failure_code IS NOT NULL
             AND failure_message IS NOT NULL)
        )
        """
    )


def downgrade() -> None:
    """확장된 상태와 lineage constraint·column을 의존성 역순으로 제거한다."""

    # Dropping replay lineage restores the old schema without re-enabling the old
    # checksum-reuse implementation.
    op.execute(
        "ALTER TABLE report_v1.report_block_runs "
        "DROP CONSTRAINT report_block_run_failure_check"
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "DROP CONSTRAINT report_block_replay_lineage_check, "
        "DROP CONSTRAINT report_block_analysis_definition_fk"
    )
    op.execute(
        "UPDATE report_v1.report_manual_run_commands "
        "SET status = 'failed' WHERE status IN ('running', 'cancelled')"
    )
    op.execute(
        "ALTER TABLE report_v1.report_manual_run_commands "
        "DROP CONSTRAINT report_manual_run_commands_status_check, "
        "ADD CONSTRAINT report_manual_run_commands_status_check "
        "CHECK (status IN ('queued','success','partial','failed'))"
    )
    op.execute(
        "ALTER TABLE report_v1.report_block_runs "
        "DROP COLUMN failure_message, DROP COLUMN failure_code, "
        "DROP COLUMN policy_version, DROP COLUMN request_id"
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "DROP COLUMN analysis_definition_version, DROP COLUMN analysis_definition_id"
    )
