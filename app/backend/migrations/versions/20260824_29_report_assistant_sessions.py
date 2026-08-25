"""기존 Report Assistant 요청에 서버 소유 세션 phase와 승인 계획을 추가한다."""

from alembic import op


revision = "20260824_29"
down_revision = "20260820_28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 성공·실패 상태 규약을 보존하면서 대화형 세션 필드를 확장한다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            ADD COLUMN phase varchar(24),
            ADD COLUMN session_definition_id uuid,
            ADD COLUMN session_definition_version integer,
            ADD COLUMN base_revision integer,
            ADD COLUMN analysis_plan_json jsonb,
            ADD COLUMN data_request_id uuid,
            ADD COLUMN decision_hash varchar(64),
            ADD COLUMN approved_at timestamptz,
            ADD COLUMN rejected_at timestamptz,
            ADD COLUMN result_artifact_id uuid REFERENCES artifact.analysis_artifacts(artifact_id),
            ADD COLUMN result_revision integer,
            ADD CONSTRAINT report_assistant_session_definition_fk
                FOREIGN KEY (session_definition_id, session_definition_version)
                REFERENCES report_v1.report_definition_versions(definition_id, version),
            ADD CONSTRAINT report_assistant_phase_check CHECK (
                phase IS NULL OR phase IN (
                    'ready', 'waiting_approval', 'running_data_agent',
                    'waiting_artifact', 'saving_revision', 'completed',
                    'failed', 'cancelled'
                )
            ),
            ADD CONSTRAINT report_assistant_session_fields_check CHECK (
                phase IS NULL OR (
                    session_definition_id IS NOT NULL
                    AND session_definition_version IS NOT NULL
                    AND base_revision IS NOT NULL
                    AND base_revision > 0
                )
            ),
            ADD CONSTRAINT report_assistant_plan_check CHECK (
                phase IS NULL OR phase = 'ready' OR phase IN ('failed', 'cancelled')
                OR (analysis_plan_json IS NOT NULL AND data_request_id IS NOT NULL)
            )
        """
    )
    op.execute(
        "CREATE INDEX report_assistant_owner_phase_idx "
        "ON report_v1.report_assistant_requests (owner_id, phase, created_at DESC) "
        "WHERE phase IS NOT NULL"
    )


def downgrade() -> None:
    """대화형 세션 확장만 제거하고 기존 Assistant 요청 이력은 보존한다."""

    op.execute("DROP INDEX report_v1.report_assistant_owner_phase_idx")
    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            DROP CONSTRAINT report_assistant_plan_check,
            DROP CONSTRAINT report_assistant_session_fields_check,
            DROP CONSTRAINT report_assistant_phase_check,
            DROP CONSTRAINT report_assistant_session_definition_fk,
            DROP COLUMN result_revision,
            DROP COLUMN result_artifact_id,
            DROP COLUMN rejected_at,
            DROP COLUMN approved_at,
            DROP COLUMN decision_hash,
            DROP COLUMN data_request_id,
            DROP COLUMN analysis_plan_json,
            DROP COLUMN base_revision,
            DROP COLUMN session_definition_version,
            DROP COLUMN session_definition_id,
            DROP COLUMN phase
        """
    )
