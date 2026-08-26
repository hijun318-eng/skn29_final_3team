"""Report Assistant session에 최대 다섯 승인 Artifact의 고정 checksum 결속을 추가한다."""

import os
import re

from alembic import op


revision = "20260826_38"
down_revision = "20260826_37"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    """환경의 제한된 runtime role만 SQL identifier로 허용한다."""

    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """기존 대표 Artifact를 보존하며 session별 순서·별칭·checksum 결속을 만든다."""

    op.execute(
        """
        CREATE TABLE report_v1.report_assistant_artifact_bindings (
            assistant_request_id uuid NOT NULL REFERENCES report_v1.report_assistant_requests(assistant_request_id) ON DELETE CASCADE,
            artifact_id uuid NOT NULL REFERENCES artifact.analysis_artifacts(artifact_id),
            artifact_alias varchar(32) NOT NULL,
            ordinal smallint NOT NULL CHECK (ordinal BETWEEN 1 AND 5),
            artifact_checksum char(64) NOT NULL CHECK (artifact_checksum ~ '^[0-9a-f]{64}$'),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (assistant_request_id, artifact_id),
            UNIQUE (assistant_request_id, artifact_alias),
            UNIQUE (assistant_request_id, ordinal)
        )
        """
    )
    op.execute(
        """
        INSERT INTO report_v1.report_assistant_artifact_bindings
            (assistant_request_id, artifact_id, artifact_alias, ordinal, artifact_checksum)
        SELECT r.assistant_request_id, r.artifact_id, 'source_artifact', 1, a.artifact_checksum
        FROM report_v1.report_assistant_requests r
        JOIN artifact.analysis_artifacts a ON a.artifact_id = r.artifact_id
        WHERE r.phase IS NOT NULL AND a.artifact_checksum ~ '^[0-9a-f]{64}$'
        """
    )
    op.execute(
        f"GRANT SELECT, INSERT ON report_v1.report_assistant_artifact_bindings TO {_runtime_role()}"
    )


def downgrade() -> None:
    """기존 대표 artifact_id는 유지하고 다중 결속 table만 제거한다."""

    op.execute("DROP TABLE report_v1.report_assistant_artifact_bindings")
