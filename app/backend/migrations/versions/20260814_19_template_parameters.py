"""scenario SQL을 설치하지 않고 이미 발행된 revision chain 호환성을 보존한다."""

revision = "20260814_19"
down_revision = "20260813_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """scenario SQL을 설치하지 않은 채 발행된 revision identity만 보존한다."""


def downgrade() -> None:
    """호환성 revision이 변경한 DB state가 없으므로 되돌릴 작업도 없다."""
