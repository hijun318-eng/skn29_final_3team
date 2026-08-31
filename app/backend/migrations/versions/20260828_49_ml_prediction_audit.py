"""ML 객실 수요 예측 결과와 provenance를 append-only로 보존한다."""

import os
import re

from alembic import op


revision = "20260828_49"
down_revision = "20260828_48"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """ML 예측 결과와 RAG 미호출 provenance를 기록할 append-only 표를 만든다."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance.ml_prediction_audit_events (
            execution_id text PRIMARY KEY,
            request_payload jsonb NOT NULL,
            result_payload jsonb NOT NULL,
            provenance jsonb NOT NULL,
            status text NOT NULL,
            rag_called boolean NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_ml_prediction_audit_rag_not_called
                CHECK (rag_called = false)
        )
        """
    )
    op.execute(
        "GRANT SELECT, INSERT ON TABLE "
        f"governance.ml_prediction_audit_events TO {_runtime_role()}"
    )


def downgrade() -> None:
    """runtime 권한을 회수하고 ML 예측 감사 표를 제거한다."""
    op.execute(
        "REVOKE SELECT, INSERT ON TABLE "
        f"governance.ml_prediction_audit_events FROM {_runtime_role()}"
    )
    op.drop_table("ml_prediction_audit_events", schema="governance")
