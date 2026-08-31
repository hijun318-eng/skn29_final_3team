"""ML 예측 결과를 대화 턴의 독립 route로 보존한다."""

from alembic import op


revision = "20260831_62"
down_revision = "20260831_61"
branch_labels = None
depends_on = None


_PREVIOUS_ROUTES = (
    "ANALYSIS",
    "PRESENTATION",
    "REPORT_ACTION",
    "INTERNAL_GUIDELINE",
    "OUT_OF_SCOPE",
)


def _replace_route_check(values: tuple[str, ...]) -> None:
    allowed = ",".join(f"'{value}'" for value in values)
    op.execute("ALTER TABLE chat.turns DROP CONSTRAINT IF EXISTS turns_route_check")
    op.execute(
        "ALTER TABLE chat.turns "
        f"ADD CONSTRAINT turns_route_check CHECK (route IN ({allowed}))"
    )


def upgrade() -> None:
    """Capability 검증을 통과한 ML 예측 턴 저장을 허용한다."""

    _replace_route_check((*_PREVIOUS_ROUTES, "ML_PREDICTION"))


def downgrade() -> None:
    """ML 예측 턴이 남아 있으면 데이터 손실 방지를 위해 거부한다."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM chat.turns WHERE route = 'ML_PREDICTION'
            ) THEN
                RAISE EXCEPTION
                    'ML_PREDICTION turns must be preserved before downgrade';
            END IF;
        END $$
        """
    )
    _replace_route_check(_PREVIOUS_ROUTES)
