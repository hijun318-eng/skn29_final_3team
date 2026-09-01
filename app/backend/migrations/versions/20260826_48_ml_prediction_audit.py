"""ML 객실 수요 예측 결과와 provenance를 append-only로 보존한다."""

import os
import re

from alembic import op


revision = "20260826_48"
down_revision = "20260826_47"
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
    op.execute(
        "REVOKE SELECT, INSERT ON TABLE "
        f"governance.ml_prediction_audit_events FROM {_runtime_role()}"
    )
    op.drop_table("ml_prediction_audit_events", schema="governance")
