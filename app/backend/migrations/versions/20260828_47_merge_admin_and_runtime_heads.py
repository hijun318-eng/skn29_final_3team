"""관리자 제어 계보와 runtime catalog migration 계보를 하나로 연결한다."""

revision = "20260828_47"
down_revision = ("20260827_31", "20260826_46")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """이미 적용된 두 schema 이력을 data 변경 없이 하나의 head로 연결한다."""


def downgrade() -> None:
    """migration graph를 다시 두 부모 head로 나눈다."""
