"""Add persistent daily, weekly and monthly Report schedules."""

import os
import re

from alembic import op


revision = "20260812_08"
down_revision = "20260811_07"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE report_v1.report_schedules (
            schedule_id uuid PRIMARY KEY,
            definition_id uuid NOT NULL,
            definition_version integer NOT NULL,
            frequency varchar(16) NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly')),
            hour smallint NOT NULL CHECK (hour BETWEEN 0 AND 23),
            minute smallint NOT NULL CHECK (minute BETWEEN 0 AND 59),
            weekday smallint CHECK (weekday BETWEEN 0 AND 6),
            day_of_month smallint CHECK (day_of_month BETWEEN 1 AND 31),
            timezone_name varchar(64) NOT NULL DEFAULT 'Asia/Seoul' CHECK (timezone_name = 'Asia/Seoul'),
            enabled boolean NOT NULL DEFAULT false,
            next_run_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (definition_id, definition_version),
            FOREIGN KEY (definition_id, definition_version)
                REFERENCES report_v1.report_definition_versions(definition_id, version),
            CHECK ((frequency = 'weekly') = (weekday IS NOT NULL)),
            CHECK ((frequency = 'monthly') = (day_of_month IS NOT NULL)),
            CHECK ((enabled AND next_run_at IS NOT NULL) OR (NOT enabled AND next_run_at IS NULL))
        )
        """
    )
    op.execute("ALTER TABLE report_v1.report_manual_run_commands ADD COLUMN trigger_type varchar(16) NOT NULL DEFAULT 'MANUAL' CHECK (trigger_type IN ('MANUAL', 'SCHEDULE'))")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands ADD COLUMN schedule_id uuid REFERENCES report_v1.report_schedules(schedule_id)")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands ADD CONSTRAINT report_command_trigger_check CHECK ((trigger_type = 'MANUAL' AND schedule_id IS NULL) OR (trigger_type = 'SCHEDULE' AND schedule_id IS NOT NULL))")
    role = _runtime_role()
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON report_v1.report_schedules TO {role}")


def downgrade() -> None:
    role = _runtime_role()
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON report_v1.report_schedules FROM {role}")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands DROP CONSTRAINT report_command_trigger_check")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands DROP COLUMN schedule_id")
    op.execute("ALTER TABLE report_v1.report_manual_run_commands DROP COLUMN trigger_type")
    op.execute("DROP TABLE report_v1.report_schedules")
