"""Report Assistant의 bounded multi-turn 대화 이력을 owner 세션에 결속한다."""

import os
import re

from alembic import op


revision = "20260826_42"
down_revision = "20260826_41"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    """환경의 제한된 runtime role만 SQL identifier로 허용한다."""

    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """세션별 순번·사용자 지시·Assistant 응답·결정 종류를 저장한다."""

    op.execute(
        """
        CREATE TABLE report_v1.report_assistant_turns (
            assistant_request_id uuid NOT NULL
                REFERENCES report_v1.report_assistant_requests(assistant_request_id)
                ON DELETE CASCADE,
            turn_number integer NOT NULL CHECK (turn_number > 0),
            user_instruction varchar(500) NOT NULL CHECK (length(trim(user_instruction)) > 0),
            assistant_message varchar(1000) NOT NULL CHECK (length(trim(assistant_message)) > 0),
            change_kind varchar(24) NOT NULL CHECK (
                change_kind IN ('clarification', 'existing_artifact', 'new_data')
            ),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (assistant_request_id, turn_number)
        )
        """
    )
    role = _runtime_role()
    op.execute(
        f"GRANT SELECT, INSERT ON report_v1.report_assistant_turns TO {role}"
    )


def downgrade() -> None:
    """대화 turn만 제거하고 Assistant 세션과 보고서 revision은 보존한다."""

    op.execute("DROP TABLE report_v1.report_assistant_turns")
