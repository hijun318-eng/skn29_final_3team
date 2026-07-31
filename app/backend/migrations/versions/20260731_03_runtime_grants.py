"""Grant runtime access to objects created by the migration role."""

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
    role = _runtime_role()
    op.execute(f"GRANT USAGE ON SCHEMA governance, context, chat TO {role}")
    op.execute(f"GRANT SELECT ON governance.alembic_version TO {role}")
    op.execute(f"GRANT SELECT ON context.analysis_templates TO {role}")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        f"ON chat.analysis_state_transitions TO {role}"
    )


def downgrade() -> None:
    role = _runtime_role()
    op.execute(f"REVOKE SELECT ON governance.alembic_version FROM {role}")
    op.execute(f"REVOKE SELECT ON context.analysis_templates FROM {role}")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE "
        f"ON chat.analysis_state_transitions FROM {role}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA governance, context, chat FROM {role}")
