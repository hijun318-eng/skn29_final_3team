"""bounded multi-turn 종결 상태·시계 anchor·focus receipt를 추가하는 migration."""

import os
import re

from alembic import op


revision = "20260822_33"
down_revision = "20260822_32"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """Phase 7 트랜잭션 Gate에 필요한 서버 소유 상태만 추가한다."""

    op.execute(
        """
        ALTER TABLE chat.conversations
            ADD COLUMN wall_clock_anchor date,
            ADD COLUMN data_focus_turn_id uuid REFERENCES chat.turns(turn_id),
            ADD COLUMN data_focus_artifact_id uuid
                REFERENCES artifact.analysis_artifacts(artifact_id),
            ADD COLUMN view_focus_turn_id uuid REFERENCES chat.turns(turn_id),
            ADD COLUMN view_focus_spec_id uuid REFERENCES artifact.view_specs(view_spec_id)
        """
    )
    op.execute(
        """
        UPDATE chat.conversations
        SET wall_clock_anchor = (created_at AT TIME ZONE 'Asia/Seoul')::date
        WHERE wall_clock_anchor IS NULL
        """
    )
    op.execute(
        "ALTER TABLE chat.conversations ALTER COLUMN wall_clock_anchor SET NOT NULL"
    )

    op.execute(
        """
        ALTER TABLE chat.turns
            ADD COLUMN reply_to_turn_id uuid REFERENCES chat.turns(turn_id),
            ADD COLUMN clarifies_turn_id uuid REFERENCES chat.turns(turn_id),
            ADD COLUMN report_draft_definition_id uuid
                REFERENCES report_v1.report_definitions(definition_id),
            ADD COLUMN terminal_status varchar(16),
            ADD COLUMN reason_code varchar(64)
        """
    )
    # Phase 1 installed an immutability trigger. Disable it only inside this
    # versioned migration to label historical rows, then restore it immediately.
    op.execute("ALTER TABLE chat.turns DISABLE TRIGGER turns_immutable")
    op.execute(
        """
        WITH ordered AS (
            SELECT turn_id,
                   lag(turn_id) OVER (
                       PARTITION BY conversation_id ORDER BY turn_index
                   ) AS parent_turn_id
            FROM chat.turns
        )
        UPDATE chat.turns target
        SET reply_to_turn_id = ordered.parent_turn_id
        FROM ordered
        WHERE target.turn_id = ordered.turn_id
        """
    )
    op.execute(
        """
        UPDATE chat.turns turn_row
        SET terminal_status = CASE
                WHEN request.status IN ('SUCCEEDED','BLOCKED','PARTIAL','FAILED','CANCELLED')
                    THEN request.status
                WHEN turn_row.resolved_slots->>'ambiguity_status' = 'NEEDS_CLARIFICATION'
                    THEN 'BLOCKED'
                WHEN command.status = 'FAILED' THEN 'FAILED'
                ELSE 'SUCCEEDED'
            END,
            reason_code = CASE
                WHEN turn_row.resolved_slots->>'ambiguity_status' = 'NEEDS_CLARIFICATION'
                    THEN 'CONTEXT_INCOMPLETE'
                WHEN command.status = 'FAILED'
                    THEN COALESCE(command.error_response->>'code', 'CONVERSATION_COMMAND_FAILED')
                ELSE NULL
            END
        FROM chat.turn_commands command
        LEFT JOIN chat.analysis_requests request
          ON request.command_id = command.command_id
        WHERE command.turn_id = turn_row.turn_id
        """
    )
    op.execute(
        "UPDATE chat.turns SET terminal_status = 'FAILED' "
        "WHERE terminal_status IS NULL"
    )
    op.execute("ALTER TABLE chat.turns ENABLE TRIGGER turns_immutable")
    op.execute(
        """
        ALTER TABLE chat.turns
            ALTER COLUMN terminal_status SET NOT NULL,
            ADD CONSTRAINT turn_terminal_status_valid CHECK (
                terminal_status IN ('SUCCEEDED','BLOCKED','PARTIAL','FAILED','CANCELLED')
            ),
            ADD CONSTRAINT turn_source_ids_bounded CHECK (
                jsonb_array_length(source_turn_ids) <= 2
            ),
            ADD CONSTRAINT turn_reason_code_nonempty CHECK (
                reason_code IS NULL OR btrim(reason_code) <> ''
            )
        """
    )

    op.execute("ALTER TABLE artifact.view_specs ADD COLUMN spec_sha256 char(64)")
    op.execute("ALTER TABLE artifact.view_specs DISABLE TRIGGER view_specs_immutable")
    op.execute(
        """
        UPDATE artifact.view_specs
        SET spec_sha256 = encode(
            digest(convert_to(spec_json::text, 'UTF8'), 'sha256'), 'hex'
        )
        WHERE spec_sha256 IS NULL
        """
    )
    op.execute("ALTER TABLE artifact.view_specs ENABLE TRIGGER view_specs_immutable")
    op.execute(
        """
        ALTER TABLE artifact.view_specs
            ALTER COLUMN spec_sha256 SET NOT NULL,
            ADD CONSTRAINT view_spec_sha256_format CHECK (
                spec_sha256 ~ '^[0-9a-f]{64}$'
            )
        """
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks ADD COLUMN view_spec_id uuid "
        "REFERENCES artifact.view_specs(view_spec_id)"
    )

    role = _runtime_role()
    op.execute(
        f"GRANT UPDATE (data_focus_turn_id, data_focus_artifact_id, "
        f"view_focus_turn_id, view_focus_spec_id) "
        f"ON chat.conversations TO {role}"
    )


def downgrade() -> None:
    """Conversation 이력을 삭제하지 않고 Phase 7 상태 컬럼과 제약을 제거한다."""

    role = _runtime_role()
    op.execute(
        f"REVOKE UPDATE (data_focus_turn_id, data_focus_artifact_id, "
        f"view_focus_turn_id, view_focus_spec_id) ON chat.conversations FROM {role}"
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks DROP COLUMN view_spec_id"
    )
    op.execute(
        "ALTER TABLE artifact.view_specs "
        "DROP CONSTRAINT view_spec_sha256_format, DROP COLUMN spec_sha256"
    )
    op.execute(
        "ALTER TABLE chat.turns "
        "DROP CONSTRAINT turn_reason_code_nonempty, "
        "DROP CONSTRAINT turn_source_ids_bounded, "
        "DROP CONSTRAINT turn_terminal_status_valid, "
        "DROP COLUMN reason_code, DROP COLUMN terminal_status, "
        "DROP COLUMN report_draft_definition_id, "
        "DROP COLUMN clarifies_turn_id, DROP COLUMN reply_to_turn_id"
    )
    op.execute(
        "ALTER TABLE chat.conversations "
        "DROP COLUMN view_focus_spec_id, DROP COLUMN view_focus_turn_id, "
        "DROP COLUMN data_focus_artifact_id, DROP COLUMN data_focus_turn_id, "
        "DROP COLUMN wall_clock_anchor"
    )
