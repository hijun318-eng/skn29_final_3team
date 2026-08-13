"""Add persisted Report Assistant request outcomes."""

import os
import re

from alembic import op


revision = "20260812_11"
down_revision = "20260812_10"
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
        CREATE TABLE report_v1.report_assistant_requests (
            assistant_request_id uuid PRIMARY KEY,
            owner_id uuid NOT NULL,
            artifact_id uuid NOT NULL REFERENCES artifact.analysis_artifacts(artifact_id),
            instruction_hash varchar(64) NOT NULL CHECK (length(instruction_hash) = 64),
            status varchar(16) NOT NULL CHECK (status IN ('running', 'success', 'failed')),
            definition_id uuid,
            definition_version integer,
            prompt_id varchar(64) NOT NULL,
            prompt_version varchar(64) NOT NULL,
            prompt_hash varchar(64) NOT NULL CHECK (length(prompt_hash) = 64),
            model_version varchar(255),
            output_hash varchar(64),
            error_code varchar(64),
            created_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz,
            FOREIGN KEY (definition_id, definition_version)
                REFERENCES report_v1.report_definition_versions(definition_id, version),
            CHECK (
                (status = 'running' AND completed_at IS NULL)
                OR (status = 'success' AND definition_id IS NOT NULL
                    AND definition_version IS NOT NULL AND output_hash IS NOT NULL
                    AND error_code IS NULL AND completed_at IS NOT NULL)
                OR (status = 'failed' AND definition_id IS NULL
                    AND definition_version IS NULL AND output_hash IS NULL
                    AND error_code IS NOT NULL AND completed_at IS NOT NULL)
            )
        )
        """
    )
    role = _runtime_role()
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON report_v1.report_assistant_requests TO {role}")


def downgrade() -> None:
    op.execute("DROP TABLE report_v1.report_assistant_requests")
