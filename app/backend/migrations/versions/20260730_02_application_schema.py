"""Apply approved application schema through the single Alembic head."""

from pathlib import Path

from alembic import op

revision = "20260730_02"
down_revision = "20260729_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    root = Path(__file__).resolve().parents[4]
    ddl = root / "infrastructure" / "database" / "sql" / "ddl" / "00_answervice_app_postgresql.sql"
    sql = "\n".join(line for line in ddl.read_text(encoding="utf-8").splitlines() if not line.startswith("\\"))
    op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat.analysis_state_transitions")
    op.execute("DROP TABLE IF EXISTS context.analysis_templates")
