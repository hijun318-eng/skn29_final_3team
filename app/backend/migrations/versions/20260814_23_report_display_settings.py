"""Report page orientation과 currency display 설정을 version별로 영속화한다."""

from alembic import op


revision = "20260814_23"
down_revision = "20260814_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """definition version과 frozen document에 검증된 display setting column을 추가한다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_definition_versions
        ADD COLUMN orientation varchar(16) NOT NULL DEFAULT 'portrait'
            CHECK (orientation IN ('portrait', 'landscape')),
        ADD COLUMN currency_display_unit varchar(24) NOT NULL DEFAULT 'auto'
            CHECK (currency_display_unit IN
                ('auto', 'one', 'thousand', 'million', 'hundredMillion', 'billion'))
        """
    )
    op.execute(
        """
        ALTER TABLE report_v1.report_documents
        ADD COLUMN currency_display_unit varchar(24) NOT NULL DEFAULT 'auto'
            CHECK (currency_display_unit IN
                ('auto', 'one', 'thousand', 'million', 'hundredMillion', 'billion'))
        """
    )


def downgrade() -> None:
    """frozen document와 definition version의 display setting column을 제거한다."""

    op.execute(
        "ALTER TABLE report_v1.report_documents DROP COLUMN currency_display_unit"
    )
    op.execute(
        "ALTER TABLE report_v1.report_definition_versions "
        "DROP COLUMN currency_display_unit, DROP COLUMN orientation"
    )
