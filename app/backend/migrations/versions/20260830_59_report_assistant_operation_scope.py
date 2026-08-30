"""Report Assistant 세션에 서버 권위 변경 범위를 영속한다."""

from alembic import op


revision = "20260830_59"
down_revision = "20260829_58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 세션은 전체 보고서 범위로 보존하고 이후 명확한 enum만 저장한다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            ADD COLUMN operation_scope varchar(24) NOT NULL DEFAULT 'full_report';
        ALTER TABLE report_v1.report_assistant_requests
            ADD COLUMN message_revision bigint NOT NULL DEFAULT 0;
        ALTER TABLE report_v1.report_assistant_requests
            ADD CONSTRAINT report_assistant_operation_scope_check
            CHECK (operation_scope IN ('full_report', 'report_title'));
        ALTER TABLE report_v1.report_assistant_requests
            ADD CONSTRAINT report_assistant_message_revision_check
            CHECK (message_revision >= 0);
        """
    )


def downgrade() -> None:
    """범위·메시지 revision 컬럼만 제거하고 기존 세션·대화·보고서 버전은 보존한다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            DROP CONSTRAINT report_assistant_message_revision_check;
        ALTER TABLE report_v1.report_assistant_requests
            DROP CONSTRAINT report_assistant_operation_scope_check;
        ALTER TABLE report_v1.report_assistant_requests
            DROP COLUMN message_revision;
        ALTER TABLE report_v1.report_assistant_requests
            DROP COLUMN operation_scope;
        """
    )
