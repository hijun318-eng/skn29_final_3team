"""일반 대화 응답을 분석 턴과 분리된 불변 route로 보존한다."""

from alembic import op


revision = "20260829_57"
down_revision = "20260828_56"
branch_labels = None
depends_on = None


def _replace_route_check(values: tuple[str, ...]) -> None:
    allowed = ",".join(f"'{value}'" for value in values)
    op.execute("ALTER TABLE chat.turns DROP CONSTRAINT IF EXISTS turns_route_check")
    op.execute(
        "ALTER TABLE chat.turns "
        f"ADD CONSTRAINT turns_route_check CHECK (route IN ({allowed}))"
    )


def upgrade() -> None:
    """GENERAL_CHAT 턴을 기존 분석 focus와 독립된 route로 허용한다."""

    _replace_route_check(
        (
            "ANALYSIS",
            "PRESENTATION",
            "REPORT_ACTION",
            "INTERNAL_GUIDELINE",
            "GENERAL_CHAT",
        )
    )


def downgrade() -> None:
    """일반 대화 턴이 남아 있으면 데이터 손실을 막기 위해 downgrade를 거부한다."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM chat.turns WHERE route = 'GENERAL_CHAT'
            ) THEN
                RAISE EXCEPTION
                    'GENERAL_CHAT turns must be preserved before downgrade';
            END IF;
        END $$
        """
    )
    _replace_route_check(
        ("ANALYSIS", "PRESENTATION", "REPORT_ACTION", "INTERNAL_GUIDELINE")
    )
