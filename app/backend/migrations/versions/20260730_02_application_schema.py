"""Apply approved application schema through the single Alembic head."""

from pathlib import Path

from alembic import op

revision = "20260730_02"
down_revision = "20260729_01"
branch_labels = None
depends_on = None


APPLICATION_DELTA = (
    """
    CREATE TABLE IF NOT EXISTS context.analysis_templates (
        template_id varchar(128) PRIMARY KEY,
        version varchar(64) NOT NULL,
        status varchar(16) NOT NULL CHECK (status IN ('DRAFT','APPROVED','RETIRED')),
        parameter_names_json jsonb NOT NULL,
        requires_g1 boolean NOT NULL DEFAULT true CHECK (requires_g1),
        requires_g2 boolean NOT NULL DEFAULT true CHECK (requires_g2),
        approved_by uuid,
        approved_at timestamptz,
        UNIQUE (template_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat.analysis_state_transitions (
        transition_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        request_id uuid NOT NULL REFERENCES chat.analysis_requests(request_id),
        sequence_no smallint NOT NULL CHECK (sequence_no > 0),
        from_status varchar(20),
        to_status varchar(20) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (request_id, sequence_no)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_analysis_state_transitions_request_created
        ON chat.analysis_state_transitions(request_id, created_at)
    """,
)


def upgrade() -> None:
    connection = op.get_bind()
    existing_application_schema = connection.exec_driver_sql(
        "SELECT to_regclass('governance.schema_version') IS NOT NULL"
    ).scalar_one()
    if existing_application_schema:
        for statement in APPLICATION_DELTA:
            connection.exec_driver_sql(statement)
        return

    root = Path(__file__).resolve().parents[4]
    ddl = root / "infrastructure" / "database" / "sql" / "ddl" / "00_answervice_app_postgresql.sql"
    sql = "\n".join(line for line in ddl.read_text(encoding="utf-8").splitlines() if not line.startswith("\\"))
    connection.exec_driver_sql(sql)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat.analysis_state_transitions")
    op.execute("DROP TABLE IF EXISTS context.analysis_templates")
