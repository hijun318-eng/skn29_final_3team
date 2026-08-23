"""Phase 10 runtime role에 terminal query 증거 기록용 최소 column 권한을 부여한다."""

import os
import re

from alembic import op


revision = "20260823_34"
down_revision = "20260822_33"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


_TERMINAL_EVIDENCE_COLUMNS = (
    "generation_mode",
    "ast_validation_json",
    "join_validation_json",
    "permission_validation_json",
    "explain_json",
    "validation_status",
    "result_checksum",
    "source_urns_json",
    "source_cutoff_json",
)


def upgrade() -> None:
    """runtime이 terminal evidence를 완성하는 데 필요한 column UPDATE만 추가한다."""

    columns = ", ".join(_TERMINAL_EVIDENCE_COLUMNS)
    op.execute(
        f"GRANT UPDATE ({columns}) ON query.query_executions TO {_runtime_role()}"
    )


def downgrade() -> None:
    """Phase 1 lifecycle 권한은 유지하고 Phase 10에서 추가한 column 권한만 회수한다."""

    columns = ", ".join(_TERMINAL_EVIDENCE_COLUMNS)
    op.execute(
        f"REVOKE UPDATE ({columns}) ON query.query_executions FROM {_runtime_role()}"
    )
