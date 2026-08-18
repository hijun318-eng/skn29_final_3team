"""고정 scenario row 없이 Template schema와 최소권한 runtime grant를 적용한다."""

import os
import re

from alembic import op


revision = "20260731_03"
down_revision = "20260730_02"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """동적 Template 저장 구조를 완성하고 runtime role에 필요한 권한만 부여한다."""

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
        DELETE FROM context.analysis_templates
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
    role = _runtime_role()
    op.execute(f"GRANT USAGE ON SCHEMA governance, context, chat TO {role}")
    op.execute(f"GRANT SELECT ON governance.alembic_version TO {role}")
    op.execute(f"GRANT SELECT ON context.analysis_templates TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON chat.analysis_state_transitions TO {role}")


def downgrade() -> None:
    """runtime grant와 이 revision의 Template SQL column만 제거한다."""

    role = _runtime_role()
    op.execute(f"REVOKE SELECT, INSERT ON chat.analysis_state_transitions FROM {role}")
    op.execute(f"REVOKE SELECT ON context.analysis_templates FROM {role}")
    op.execute(f"REVOKE SELECT ON governance.alembic_version FROM {role}")
    op.execute(f"REVOKE USAGE ON SCHEMA governance, context, chat FROM {role}")
    op.execute("ALTER TABLE context.analysis_templates DROP COLUMN IF EXISTS source_fqns_json")
    op.execute("ALTER TABLE context.analysis_templates DROP COLUMN IF EXISTS sql_text")
