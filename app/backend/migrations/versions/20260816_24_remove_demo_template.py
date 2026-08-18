"""과거 demonstration Analysis Template row를 upgrade된 DB에서 제거한다."""

from alembic import op
from sqlalchemy import text


revision = "20260816_24"
down_revision = "20260814_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """역사적 identifier 한 건을 parameter binding으로 삭제해 runtime 의존을 끝낸다."""

    op.get_bind().execute(
        text(
            "DELETE FROM context.analysis_templates "
            "WHERE template_id = :legacy_template_id"
        ),
        {"legacy_template_id": "weekly-room-operations"},
    )


def downgrade() -> None:
    """삭제된 scenario SQL을 되살리는 것이므로 downgrade에서도 의도적으로 재생성하지 않는다."""
