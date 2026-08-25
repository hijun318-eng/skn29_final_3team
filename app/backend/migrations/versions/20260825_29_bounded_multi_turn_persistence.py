"""멀티턴 대화와 Artifact 표현 변경을 저장하는 DB 계약을 runtime에 추가한다."""

import os
import re

from alembic import op


revision = "20260825_29"
down_revision = "20260820_28"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    """환경이 지정한 runtime role을 검증해 안전한 PostgreSQL 식별자로 반환한다."""

    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """불변 turn·command·ViewSpec 구조와 repository 최소권한을 추가한다."""

    op.execute(
        """
        CREATE TABLE artifact.view_specs (
            view_spec_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            artifact_id uuid NOT NULL REFERENCES artifact.analysis_artifacts(artifact_id),
            view_type varchar(32) NOT NULL CHECK (
                view_type IN ('SUMMARY','TABLE','BAR','LINE','PIE','HORIZONTAL_BAR','DONUT')
            ),
            spec_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chat.turns (
            turn_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id uuid NOT NULL REFERENCES chat.conversations(conversation_id),
            turn_index integer NOT NULL CHECK (turn_index >= 0),
            user_message text NOT NULL,
            route varchar(32) NOT NULL CHECK (
                route IN ('ANALYSIS','PRESENTATION','REPORT_ACTION')
            ),
            source_turn_ids jsonb NOT NULL DEFAULT '[]',
            request_id uuid REFERENCES chat.analysis_requests(request_id),
            artifact_id uuid REFERENCES artifact.analysis_artifacts(artifact_id),
            view_spec_id uuid REFERENCES artifact.view_specs(view_spec_id),
            report_definition_id uuid REFERENCES report.report_definitions(report_definition_id),
            resolved_slots jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (conversation_id, turn_index)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chat.turn_commands (
            command_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id uuid NOT NULL REFERENCES chat.conversations(conversation_id),
            idempotency_key varchar(128) NOT NULL,
            canonical_input_hash char(64) NOT NULL,
            status varchar(32) NOT NULL CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
            turn_id uuid REFERENCES chat.turns(turn_id),
            error_response jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (conversation_id, idempotency_key)
        )
        """
    )
    op.execute(
        """
        ALTER TABLE chat.conversations
            ADD COLUMN head_turn_id uuid REFERENCES chat.turns(turn_id),
            ADD COLUMN turn_count integer NOT NULL DEFAULT 0,
            ADD COLUMN active_command_id uuid REFERENCES chat.turn_commands(command_id),
            ADD COLUMN lease_expires_at timestamptz
        """
    )
    op.execute(
        "CREATE INDEX idx_chat_turns_conv ON chat.turns(conversation_id, turn_index)"
    )
    op.execute(
        "CREATE INDEX idx_chat_commands_lookup "
        "ON chat.turn_commands(conversation_id, idempotency_key)"
    )
    op.execute(
        "CREATE INDEX idx_view_specs_artifact ON artifact.view_specs(artifact_id)"
    )

    role = _runtime_role()
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON chat.conversations TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON chat.turns TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON chat.turn_commands TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON artifact.view_specs TO {role}")


def downgrade() -> None:
    """runtime 권한을 회수하고 멀티턴 구조를 참조 역순으로 제거한다."""

    role = _runtime_role()
    op.execute(f"REVOKE SELECT, INSERT ON artifact.view_specs FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON chat.turn_commands FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT ON chat.turns FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON chat.conversations FROM {role}")
    op.execute(
        """
        ALTER TABLE chat.conversations
            DROP COLUMN lease_expires_at,
            DROP COLUMN active_command_id,
            DROP COLUMN turn_count,
            DROP COLUMN head_turn_id
        """
    )
    op.execute("DROP TABLE chat.turn_commands")
    op.execute("DROP TABLE chat.turns")
    op.execute("DROP TABLE artifact.view_specs")
