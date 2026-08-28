"""RuntimeContextPackage를 Run 단위의 불변 실행 영수증으로 연결한다."""

from alembic import op


revision = "20260826_45"
down_revision = "20260826_44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """과거 Context Registry FK를 선택값으로 두고 runtime release 결속을 강제한다."""

    op.execute(
        "ALTER TABLE context.context_packages "
        "ALTER COLUMN context_release_id DROP NOT NULL"
    )
    op.execute(
        """
        ALTER TABLE context.context_packages
        ADD CONSTRAINT context_package_semantic_receipt_required CHECK (
            context_release_id IS NOT NULL
            OR (
                product_release_id IS NOT NULL
                AND permission_snapshot_id IS NOT NULL
                AND semantic_release_id IS NOT NULL
            )
        ) NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE chat.analysis_requests
        ADD CONSTRAINT analysis_request_context_receipt_complete CHECK (
            context_package_id IS NULL
            OR (
                product_release_id IS NOT NULL
                AND permission_snapshot_id IS NOT NULL
                AND semantic_release_id IS NOT NULL
            )
        ) NOT VALID
        """
    )


def downgrade() -> None:
    """runtime 영수증 제약을 제거하며 null 영수증이 없을 때만 과거 NOT NULL을 복원한다."""

    op.execute(
        "ALTER TABLE chat.analysis_requests "
        "DROP CONSTRAINT IF EXISTS analysis_request_context_receipt_complete"
    )
    op.execute(
        "ALTER TABLE context.context_packages "
        "DROP CONSTRAINT IF EXISTS context_package_semantic_receipt_required"
    )
    op.execute(
        "ALTER TABLE context.context_packages "
        "ALTER COLUMN context_release_id SET NOT NULL"
    )
