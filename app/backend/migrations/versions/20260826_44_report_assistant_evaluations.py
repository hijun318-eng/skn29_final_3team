"""Report Assistant 요청별 안전한 품질·비용 평가를 멱등 저장한다."""

import os
import re

from alembic import op


revision = "20260826_44"
down_revision = "20260826_43"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    """제한된 runtime role 이름만 SQL identifier로 허용한다."""

    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """원문 prompt·SQL 없이 request ID 단위 평가 레코드와 조회 index를 추가한다."""

    op.execute(
        """
        CREATE TABLE report_v1.report_assistant_evaluations (
            evaluation_id uuid PRIMARY KEY,
            assistant_request_id uuid NOT NULL UNIQUE
                REFERENCES report_v1.report_assistant_requests(assistant_request_id)
                ON DELETE CASCADE,
            owner_id uuid NOT NULL,
            data_request_id uuid,
            patch_request_id uuid,
            definition_id uuid,
            definition_version integer CHECK (definition_version IS NULL OR definition_version > 0),
            artifact_id uuid,
            prompt_id varchar(128),
            prompt_version varchar(64),
            model_version varchar(128),
            route varchar(24) CHECK (route IS NULL OR route IN ('existing_artifact', 'new_data')),
            operation_types jsonb NOT NULL DEFAULT '[]'::jsonb,
            contract_valid boolean NOT NULL DEFAULT false,
            approval_decision varchar(16) NOT NULL DEFAULT 'pending'
                CHECK (approval_decision IN ('approved', 'rejected', 'pending')),
            final_phase varchar(32) NOT NULL DEFAULT 'ready',
            revision_created boolean NOT NULL DEFAULT false,
            duplicate_revision_prevented boolean NOT NULL DEFAULT false,
            model_attempts integer CHECK (model_attempts IS NULL OR model_attempts > 0),
            latency_ms numeric(14,3) CHECK (latency_ms IS NULL OR latency_ms >= 0),
            input_tokens integer CHECK (input_tokens IS NULL OR input_tokens >= 0),
            output_tokens integer CHECK (output_tokens IS NULL OR output_tokens >= 0),
            estimated_cost numeric(18,8) CHECK (estimated_cost IS NULL OR estimated_cost >= 0),
            cost_is_estimate boolean NOT NULL DEFAULT false,
            error_code varchar(128),
            evaluated_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX report_assistant_evaluations_period_idx
            ON report_v1.report_assistant_evaluations(evaluated_at DESC);
        CREATE INDEX report_assistant_evaluations_owner_period_idx
            ON report_v1.report_assistant_evaluations(owner_id, evaluated_at DESC);
        CREATE INDEX report_assistant_evaluations_failure_idx
            ON report_v1.report_assistant_evaluations(error_code, evaluated_at DESC)
            WHERE error_code IS NOT NULL;
        """
    )
    role = _runtime_role()
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON report_v1.report_assistant_evaluations TO {role}"
    )


def downgrade() -> None:
    """평가 데이터만 제거하고 Assistant 세션과 Revision은 보존한다."""

    op.execute("DROP TABLE report_v1.report_assistant_evaluations")
