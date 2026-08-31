"""일반 GPT route를 제거하고 범위 밖 요청을 고정 응답 route로 보존한다."""

from alembic import op


revision = "20260829_58"
down_revision = "20260829_57"
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
    """저장된 일반 GPT 턴이 없을 때만 OUT_OF_SCOPE 계약으로 교체한다."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM chat.turns WHERE route = 'GENERAL_CHAT'
            ) THEN
                RAISE EXCEPTION
                    'GENERAL_CHAT turns must be preserved before route replacement';
            END IF;
        END $$
        """
    )
    _replace_route_check(
        (
            "ANALYSIS",
            "PRESENTATION",
            "REPORT_ACTION",
            "INTERNAL_GUIDELINE",
            "OUT_OF_SCOPE",
        )
    )


def downgrade() -> None:
    """범위 거부 턴이 남아 있으면 데이터 손실을 막기 위해 downgrade를 거부한다."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM chat.turns WHERE route = 'OUT_OF_SCOPE'
            ) THEN
                RAISE EXCEPTION
                    'OUT_OF_SCOPE turns must be preserved before downgrade';
            END IF;
        END $$
        """
    )
    _replace_route_check(
        (
            "ANALYSIS",
            "PRESENTATION",
            "REPORT_ACTION",
            "INTERNAL_GUIDELINE",
            "GENERAL_CHAT",
        )
    )
