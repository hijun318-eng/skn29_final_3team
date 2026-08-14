from pathlib import Path

from alembic import op
from sqlalchemy import text


revision = "20260814_19"
down_revision = "20260813_18"
branch_labels = None
depends_on = None


def _template_sql() -> str:
    root = Path(__file__).resolve().parents[4]
    path = root / "infrastructure/database/sql/queries/i2_gold_recognized_room_revenue.sql"
    if not path.is_file():
        raise RuntimeError("required template SQL is missing")
    return path.read_text(encoding="utf-8").strip()


def upgrade() -> None:
    op.get_bind().execute(
        text(
            "UPDATE context.analysis_templates "
            "SET version = 'I2-v1.1.0', status = 'APPROVED', sql_text = :sql_text "
            "WHERE template_id = 'weekly-room-operations'"
        ),
        {"sql_text": _template_sql()},
    )


def downgrade() -> None:
    op.execute(
        "UPDATE context.analysis_templates "
        "SET version = 'I2-v1.0.0', status = 'DRAFT' "
        "WHERE template_id = 'weekly-room-operations'"
    )
