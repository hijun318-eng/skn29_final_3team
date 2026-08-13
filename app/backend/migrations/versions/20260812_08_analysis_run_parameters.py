"""Persist the immutable parameter snapshot for each Analysis run."""

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
        "ALTER TABLE analysis_v1.analysis_run_links "
        "ADD COLUMN parameters_json jsonb NOT NULL DEFAULT '{}'::jsonb, "
        "ADD COLUMN parameter_hash varchar(64) NOT NULL "
        "DEFAULT '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'"
    )
    op.execute(
        "ALTER TABLE analysis_v1.analysis_run_links "
        "ALTER COLUMN parameters_json DROP DEFAULT, "
        "ALTER COLUMN parameter_hash DROP DEFAULT"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON analysis_v1.analysis_run_links TO {_runtime_role()}"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE analysis_v1.analysis_run_links "
        "DROP COLUMN parameter_hash, DROP COLUMN parameters_json"
    )
