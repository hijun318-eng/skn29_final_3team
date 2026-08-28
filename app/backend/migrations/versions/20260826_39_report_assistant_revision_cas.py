"""Report Assistant가 draft 변경과 동시 수정을 구분할 revision token을 추가한다."""

from alembic import op


revision = "20260826_39"
down_revision = "20260826_38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 draft를 revision 1로 시작하고 이후 block 저장에서 증가시킬 token을 추가한다."""

    op.execute(
        "ALTER TABLE report_v1.report_definition_versions "
        "ADD COLUMN revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0)"
    )


def downgrade() -> None:
    """Assistant CAS token만 제거하고 definition version과 block은 보존한다."""

    op.execute(
        "ALTER TABLE report_v1.report_definition_versions DROP COLUMN revision"
    )
