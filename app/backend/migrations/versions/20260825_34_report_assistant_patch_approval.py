"""Report Assistant의 기존 근거 patch를 사용자 승인 뒤 저장하도록 확장한다."""

from alembic import op


revision = "20260825_34"
down_revision = "20260824_33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """patch 요청 ID와 승인 대기 phase를 추가하고 완료 phase의 계획 제약 오류를 바로잡는다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            ADD COLUMN patch_request_id uuid,
            DROP CONSTRAINT report_assistant_phase_check,
            DROP CONSTRAINT report_assistant_plan_check,
            ADD CONSTRAINT report_assistant_phase_check CHECK (
                phase IS NULL OR phase IN (
                    'ready', 'waiting_patch_approval', 'waiting_approval',
                    'running_data_agent', 'waiting_artifact', 'saving_revision',
                    'completed', 'failed', 'cancelled'
                )
            ),
            ADD CONSTRAINT report_assistant_plan_check CHECK (
                phase IS NULL
                OR phase IN ('ready', 'completed', 'failed', 'cancelled')
                OR (
                    phase = 'waiting_patch_approval'
                    AND report_patch_json IS NOT NULL
                    AND patch_request_id IS NOT NULL
                )
                OR (
                    phase = 'saving_revision'
                    AND (
                        (report_patch_json IS NOT NULL AND patch_request_id IS NOT NULL)
                        OR (analysis_plan_json IS NOT NULL AND data_request_id IS NOT NULL)
                    )
                )
                OR (
                    phase IN ('waiting_approval', 'running_data_agent', 'waiting_artifact')
                    AND analysis_plan_json IS NOT NULL
                    AND data_request_id IS NOT NULL
                )
            )
        """
    )


def downgrade() -> None:
    """승인 대기 patch가 없는 상태에서 이전 phase·계획 제약으로 되돌린다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            DROP CONSTRAINT report_assistant_plan_check,
            DROP CONSTRAINT report_assistant_phase_check,
            DROP COLUMN patch_request_id,
            ADD CONSTRAINT report_assistant_phase_check CHECK (
                phase IS NULL OR phase IN (
                    'ready', 'waiting_approval', 'running_data_agent',
                    'waiting_artifact', 'saving_revision', 'completed',
                    'failed', 'cancelled'
                )
            ),
            ADD CONSTRAINT report_assistant_plan_check CHECK (
                phase IS NULL OR phase = 'ready' OR phase IN ('failed', 'cancelled')
                OR (analysis_plan_json IS NOT NULL AND data_request_id IS NOT NULL)
            )
        """
    )
