"""Apply approved application schema and deterministic I2 template."""

import json
import os
from pathlib import Path

from alembic import op
from sqlalchemy import text

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
        sql_text text NOT NULL,
        source_fqns_json jsonb NOT NULL,
        requires_g1 boolean NOT NULL DEFAULT true CHECK (requires_g1),
        requires_g2 boolean NOT NULL DEFAULT true CHECK (requires_g2),
        approved_by uuid,
        approved_at timestamptz,
        UNIQUE (template_id, version)
    )
    """,
    """
    ALTER TABLE context.analysis_templates
        ADD COLUMN IF NOT EXISTS sql_text text,
        ADD COLUMN IF NOT EXISTS source_fqns_json jsonb
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


def _read_sql(filename: str) -> str:
    configured = os.getenv("APPLICATION_DDL_PATH" if filename.startswith("00_") else "I2_TEMPLATE_SQL_PATH")
    candidates = [
        Path(configured) if configured else None,
        Path(__file__).resolve().parents[1] / "sql" / filename,
        Path(__file__).resolve().parents[4] / "infrastructure" / "database" / "sql" / (
            "ddl" if filename.startswith("00_") else "queries"
        ) / filename
        if len(Path(__file__).resolve().parents) > 4
        else None,
    ]
    path = next((item for item in candidates if item and item.is_file()), None)
    if path is None:
        raise RuntimeError(f"required migration SQL is missing: {filename}")
    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith("\\")
    )


def _seed_i2_template(connection) -> None:
    template_sql = (
        _read_sql("i2_gold_recognized_room_revenue.sql")
        .replace("2026-05-01", ":period_start")
        .replace("2026-07-01", ":period_end_exclusive")
        .rstrip()
        .rstrip(";")
        + "\nLIMIT 1000"
    )
    source_fqns = [
        "pms.public.pms_stays",
        "pms.public.pms_reservations",
        "pms.public.pms_guests",
        "crm.dbo.crm_customer_map",
        "crm.dbo.crm_member_grade_history",
    ]
    connection.execute(
        text(
            """
            INSERT INTO context.analysis_templates (
                template_id, version, status, parameter_names_json,
                sql_text, source_fqns_json, requires_g1, requires_g2,
                approved_at
            )
            VALUES (
                'weekly-room-operations', 'I2-v1.0.0', 'APPROVED',
                CAST(:parameter_names AS jsonb), :sql_text,
                CAST(:source_fqns AS jsonb), true, true,
                TIMESTAMPTZ '2026-07-31 00:00:00+09'
            )
            ON CONFLICT (template_id) DO UPDATE SET
                version = EXCLUDED.version,
                status = EXCLUDED.status,
                parameter_names_json = EXCLUDED.parameter_names_json,
                sql_text = EXCLUDED.sql_text,
                source_fqns_json = EXCLUDED.source_fqns_json,
                requires_g1 = EXCLUDED.requires_g1,
                requires_g2 = EXCLUDED.requires_g2,
                approved_at = EXCLUDED.approved_at
            """
        ),
        {
            "parameter_names": json.dumps(
                ["period_start", "period_end_exclusive"]
            ),
            "sql_text": template_sql,
            "source_fqns": json.dumps(source_fqns),
        },
    )


def upgrade() -> None:
    connection = op.get_bind()
    existing_application_schema = connection.exec_driver_sql(
        "SELECT to_regclass('governance.schema_version') IS NOT NULL"
    ).scalar_one()
    if not existing_application_schema:
        connection.exec_driver_sql(_read_sql("00_answervice_app_postgresql.sql"))
    for statement in APPLICATION_DELTA:
        connection.exec_driver_sql(statement)
    _seed_i2_template(connection)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat.analysis_state_transitions")
    op.execute("DROP TABLE IF EXISTS context.analysis_templates")
