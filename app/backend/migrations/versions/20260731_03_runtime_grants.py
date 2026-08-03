"""Add the deterministic I2 template and least-privilege runtime grants."""

import json
import os
import re
from pathlib import Path

from alembic import op
from sqlalchemy import text


revision = "20260731_03"
down_revision = "20260730_02"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def _template_sql() -> str:
    configured = os.getenv("I2_TEMPLATE_SQL_PATH")
    migration = Path(__file__).resolve()
    candidates = [
        Path(configured) if configured else None,
        migration.parents[1] / "sql" / "i2_gold_recognized_room_revenue.sql",
    ]
    if len(migration.parents) > 4:
        candidates.append(
            migration.parents[4]
            / "infrastructure"
            / "database"
            / "sql"
            / "queries"
            / "i2_gold_recognized_room_revenue.sql"
        )
    path = next((candidate for candidate in candidates if candidate and candidate.is_file()), None)
    if path is None:
        raise RuntimeError("required migration SQL is missing: i2_gold_recognized_room_revenue.sql")
    return (
        path.read_text(encoding="utf-8")
        .replace("2026-05-01", ":period_start")
        .replace("2026-07-01", ":period_end_exclusive")
        .rstrip()
        .rstrip(";")
        + "\nLIMIT 1000"
    )


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
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
        """
    )
    connection.exec_driver_sql(
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
        """
    )
    connection.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS ix_analysis_state_transitions_request_created
            ON chat.analysis_state_transitions(request_id, created_at)
        """
    )
    connection.exec_driver_sql(
        """
        ALTER TABLE context.analysis_templates
            ADD COLUMN IF NOT EXISTS sql_text text,
            ADD COLUMN IF NOT EXISTS source_fqns_json jsonb
        """
    )
    connection.exec_driver_sql(
        """
        UPDATE context.analysis_templates
        SET status = 'RETIRED',
            sql_text = COALESCE(sql_text, 'SELECT 1 LIMIT 1'),
            source_fqns_json = COALESCE(source_fqns_json, '[]'::jsonb)
        WHERE sql_text IS NULL OR source_fqns_json IS NULL
        """
    )
    connection.exec_driver_sql(
        """
        ALTER TABLE context.analysis_templates
            ALTER COLUMN sql_text SET NOT NULL,
            ALTER COLUMN source_fqns_json SET NOT NULL
        """
    )
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
            "parameter_names": json.dumps(["period_start", "period_end_exclusive"]),
            "sql_text": _template_sql(),
            "source_fqns": json.dumps(
                [
                    "pms.public.pms_stays",
                    "pms.public.pms_reservations",
                    "pms.public.pms_guests",
                    "crm.dbo.crm_customer_map",
                    "crm.dbo.crm_member_grade_history",
                ]
            ),
        },
    )

    role = _runtime_role()
    op.execute(f"GRANT USAGE ON SCHEMA governance, context, chat TO {role}")
    op.execute(f"GRANT SELECT ON governance.alembic_version TO {role}")
    op.execute(f"GRANT SELECT ON context.analysis_templates TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON chat.analysis_state_transitions TO {role}")


def downgrade() -> None:
    role = _runtime_role()
    op.execute(f"REVOKE SELECT, INSERT ON chat.analysis_state_transitions FROM {role}")
    op.execute(f"REVOKE SELECT ON context.analysis_templates FROM {role}")
    op.execute(f"REVOKE SELECT ON governance.alembic_version FROM {role}")
    op.execute(f"REVOKE USAGE ON SCHEMA governance, context, chat FROM {role}")
    op.execute("DELETE FROM context.analysis_templates WHERE template_id = 'weekly-room-operations'")
    op.execute("ALTER TABLE context.analysis_templates DROP COLUMN IF EXISTS source_fqns_json")
    op.execute("ALTER TABLE context.analysis_templates DROP COLUMN IF EXISTS sql_text")
