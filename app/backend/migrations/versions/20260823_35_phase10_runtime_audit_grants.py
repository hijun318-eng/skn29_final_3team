"""Phase 10 분석 runtime에 append-only audit ledger의 최소 접근 권한을 부여한다."""

import os
import re

from alembic import op


revision = "20260823_35"
down_revision = "20260823_34"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """audit event 멱등성 확인과 append-only 기록에 필요한 SELECT·INSERT만 허용한다."""

    op.execute(
        f"GRANT SELECT, INSERT ON governance.audit_events TO {_runtime_role()}"
    )


def downgrade() -> None:
    """다른 runtime 권한은 유지하고 Phase 10 audit ledger 권한만 회수한다."""

    op.execute(
        f"REVOKE SELECT, INSERT ON governance.audit_events FROM {_runtime_role()}"
    )
