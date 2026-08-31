"""MCP principal·tool별 원자 fixed-window quota 저장소를 추가한다.

Row는 window 종료 뒤 같은 길이의 보존 구간까지 유지하고, runtime의 bounded cleanup이
``expires_at`` index를 사용해 제거한다. Downgrade는 row가 하나라도 남으면 중단하여 quota
상태를 묵시적으로 삭제하지 않는다.
"""

import os
import re

from alembic import op


revision = "20260831_63"
down_revision = "20260831_62"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """원자 UPSERT와 bounded TTL cleanup에 필요한 최소 table 권한만 부여한다."""

    op.execute(
        """
        CREATE TABLE tooling.tool_rate_limit_windows (
            principal_subject uuid NOT NULL,
            tool_id uuid NOT NULL REFERENCES tooling.tool_registry(tool_id),
            window_start timestamptz NOT NULL,
            request_count bigint NOT NULL CHECK (request_count > 0),
            expires_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (principal_subject, tool_id, window_start),
            CHECK (expires_at > window_start)
        );
        CREATE INDEX idx_tool_rate_limit_windows_expires
            ON tooling.tool_rate_limit_windows (expires_at)
        """
    )
    role = _runtime_role()
    # SELECT는 UPSERT의 현재 count 조건, DELETE는 bounded TTL cleanup에만 필요하다.
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE "
        f"ON tooling.tool_rate_limit_windows TO {role}"
    )


def downgrade() -> None:
    """quota row가 남아 있으면 운영 상태 보존을 위해 table 제거를 거부한다."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM tooling.tool_rate_limit_windows) THEN
                RAISE EXCEPTION
                    'MCP Tool rate limit rows must be preserved before downgrade';
            END IF;
        END $$
        """
    )
    role = _runtime_role()
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE, DELETE "
        f"ON tooling.tool_rate_limit_windows FROM {role}"
    )
    op.execute("DROP TABLE tooling.tool_rate_limit_windows")
