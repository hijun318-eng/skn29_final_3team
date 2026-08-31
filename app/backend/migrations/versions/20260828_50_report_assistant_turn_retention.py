"""Report Assistant가 모델에 사용하는 범위만 원문 대화로 보관하게 한다."""

import os
import re

from alembic import op


revision = "20260828_50"
down_revision = "20260828_49"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    """환경의 제한된 runtime role만 SQL identifier로 허용한다."""

    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """owner 검증 뒤 최근 여섯 turn만 남기는 repository에 최소 DELETE 권한을 부여한다."""

    op.execute(
        f"GRANT DELETE ON report_v1.report_assistant_turns TO {_runtime_role()}"
    )


def downgrade() -> None:
    """대화 데이터는 보존하고 runtime role의 bounded 정리 권한만 회수한다."""

    op.execute(
        f"REVOKE DELETE ON report_v1.report_assistant_turns FROM {_runtime_role()}"
    )
