"""수기 Conversation DDL을 Alembic으로 이전하고 receipt·recovery 경계를 추가한다."""

import os
import re

from alembic import op


revision = "20260822_30"
down_revision = "20260822_29"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def _add_constraint(table: str, name: str, definition: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = '{name}' AND conrelid = '{table}'::regclass
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} {definition};
            END IF;
        END;
        $$
        """
    )


def upgrade() -> None:
    """Conversation schema 소유권과 신규 command/run receipt 불변식을 원자적으로 추가한다."""

    # 일부 환경에는 과거 수기 DDL이 이미 존재한다. downgrade가 그 사용자 데이터를
    # 삭제하지 않으면서도 새 DB에서는 실제 rollback을 수행하도록 upgrade 전 상태를 남긴다.
    op.execute(
        """
        CREATE TABLE governance.phase_20260822_30_preexisting_objects (
            object_name text PRIMARY KEY
        )
        """
    )
    op.execute(
        """
        INSERT INTO governance.phase_20260822_30_preexisting_objects(object_name)
        SELECT object_name
        FROM (VALUES
            ('table:artifact.view_specs', to_regclass('artifact.view_specs') IS NOT NULL),
            ('table:chat.turns', to_regclass('chat.turns') IS NOT NULL),
            ('table:chat.turn_commands', to_regclass('chat.turn_commands') IS NOT NULL),
            ('index:artifact.idx_view_specs_artifact', to_regclass('artifact.idx_view_specs_artifact') IS NOT NULL),
            ('index:chat.idx_chat_turns_conv', to_regclass('chat.idx_chat_turns_conv') IS NOT NULL)
        ) AS existing(object_name, present)
        WHERE present
        """
    )
    op.execute(
        """
        INSERT INTO governance.phase_20260822_30_preexisting_objects(object_name)
        SELECT 'column:query.query_executions.trino_cancel_uri'
        FROM information_schema.columns
        WHERE table_schema = 'query' AND table_name = 'query_executions'
          AND column_name = 'trino_cancel_uri'
        """
    )
    op.execute(
        """
        INSERT INTO governance.phase_20260822_30_preexisting_objects(object_name)
        SELECT 'column:chat.conversations.' || column_name
        FROM information_schema.columns
        WHERE table_schema = 'chat' AND table_name = 'conversations'
          AND column_name IN (
              'head_turn_id', 'turn_count', 'active_command_id', 'lease_expires_at'
          )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS artifact.view_specs (
            view_spec_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            artifact_id uuid NOT NULL REFERENCES artifact.analysis_artifacts(artifact_id),
            view_type varchar(32) NOT NULL CHECK (view_type IN (
                'TABLE','BAR','LINE','PIE','AREA','SCATTER','KPI'
            )),
            spec_json jsonb NOT NULL CHECK (jsonb_typeof(spec_json) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat.turns (
            turn_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id uuid NOT NULL REFERENCES chat.conversations(conversation_id),
            turn_index integer NOT NULL CHECK (turn_index >= 0),
            user_message text NOT NULL,
            route varchar(32) NOT NULL CHECK (route IN (
                'ANALYSIS','PRESENTATION','REPORT_ACTION'
            )),
            source_turn_ids jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(source_turn_ids) = 'array'),
            request_id uuid REFERENCES chat.analysis_requests(request_id),
            artifact_id uuid REFERENCES artifact.analysis_artifacts(artifact_id),
            view_spec_id uuid REFERENCES artifact.view_specs(view_spec_id),
            report_definition_id uuid REFERENCES report.report_definitions(report_definition_id),
            resolved_slots jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(resolved_slots) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (conversation_id, turn_index)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat.turn_commands (
            command_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id uuid NOT NULL REFERENCES chat.conversations(conversation_id),
            idempotency_key varchar(128) NOT NULL CHECK (btrim(idempotency_key) <> ''),
            canonical_input_hash char(64) NOT NULL
                CHECK (canonical_input_hash ~ '^[0-9a-f]{64}$'),
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
            ADD COLUMN IF NOT EXISTS head_turn_id uuid REFERENCES chat.turns(turn_id),
            ADD COLUMN IF NOT EXISTS turn_count integer NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS active_command_id uuid REFERENCES chat.turn_commands(command_id),
            ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz,
            ADD COLUMN IF NOT EXISTS product_release_id varchar(160),
            ADD COLUMN IF NOT EXISTS permission_snapshot_id varchar(160),
            ADD COLUMN IF NOT EXISTS semantic_release_id varchar(256),
            ADD COLUMN IF NOT EXISTS release_pinned_at timestamptz
        """
    )
    op.execute(
        """
        ALTER TABLE chat.turns
            ADD COLUMN IF NOT EXISTS product_release_id varchar(160),
            ADD COLUMN IF NOT EXISTS permission_snapshot_id varchar(160),
            ADD COLUMN IF NOT EXISTS semantic_release_id varchar(256)
        """
    )
    op.execute(
        """
        ALTER TABLE chat.turn_commands
            ADD COLUMN IF NOT EXISTS expected_head_turn_id uuid,
            ADD COLUMN IF NOT EXISTS effective_subject_id uuid,
            ADD COLUMN IF NOT EXISTS product_release_id varchar(160),
            ADD COLUMN IF NOT EXISTS permission_snapshot_id varchar(160),
            ADD COLUMN IF NOT EXISTS semantic_release_id varchar(256),
            ADD COLUMN IF NOT EXISTS terminal_at timestamptz
        """
    )
    op.execute(
        """
        ALTER TABLE chat.analysis_requests
            ADD COLUMN IF NOT EXISTS command_id uuid REFERENCES chat.turn_commands(command_id),
            ADD COLUMN IF NOT EXISTS product_release_id varchar(160),
            ADD COLUMN IF NOT EXISTS permission_snapshot_id varchar(160),
            ADD COLUMN IF NOT EXISTS semantic_release_id varchar(256)
        """
    )
    op.execute(
        "ALTER TABLE query.query_executions "
        "ADD COLUMN IF NOT EXISTS trino_cancel_uri text"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_analysis_requests_command_id "
        "ON chat.analysis_requests(command_id) WHERE command_id IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE chat.analysis_requests "
        "DROP CONSTRAINT IF EXISTS ck_chat_analysis_requests_error_type"
    )
    op.execute(
        "ALTER TABLE chat.analysis_requests "
        "ADD CONSTRAINT ck_chat_analysis_requests_error_type CHECK ("
        "error_type IS NULL OR error_type IN ("
        "'AMBIGUOUS','UNSUPPORTED','PERMISSION','QUERY','PARTIAL',"
        "'INSUFFICIENT_EVIDENCE','PERSISTENCE','RECOVERY'))"
    )
    op.execute(
        """
        ALTER TABLE artifact.analysis_artifacts
            ADD COLUMN IF NOT EXISTS product_release_id varchar(160),
            ADD COLUMN IF NOT EXISTS permission_snapshot_id varchar(160),
            ADD COLUMN IF NOT EXISTS semantic_release_id varchar(256)
        """
    )
    op.execute(
        """
        ALTER TABLE artifact.view_specs
            ADD COLUMN IF NOT EXISTS product_release_id varchar(160),
            ADD COLUMN IF NOT EXISTS permission_snapshot_id varchar(160),
            ADD COLUMN IF NOT EXISTS semantic_release_id varchar(256)
        """
    )
    op.execute(
        """
        ALTER TABLE context.context_packages
            ADD COLUMN IF NOT EXISTS product_release_id varchar(160),
            ADD COLUMN IF NOT EXISTS permission_snapshot_id varchar(160),
            ADD COLUMN IF NOT EXISTS semantic_release_id varchar(256)
        """
    )

    _add_constraint(
        "chat.conversations",
        "conversation_release_receipt_required",
        "CHECK (product_release_id IS NOT NULL AND permission_snapshot_id IS NOT NULL "
        "AND semantic_release_id IS NOT NULL AND release_pinned_at IS NOT NULL) NOT VALID",
    )
    _add_constraint(
        "artifact.view_specs",
        "view_spec_json_object",
        "CHECK (jsonb_typeof(spec_json) = 'object') NOT VALID",
    )
    _add_constraint(
        "chat.turns",
        "turn_source_ids_array",
        "CHECK (jsonb_typeof(source_turn_ids) = 'array') NOT VALID",
    )
    _add_constraint(
        "chat.turns",
        "turn_resolved_slots_object",
        "CHECK (jsonb_typeof(resolved_slots) = 'object') NOT VALID",
    )
    _add_constraint(
        "chat.turn_commands",
        "command_idempotency_key_nonempty",
        "CHECK (btrim(idempotency_key) <> '') NOT VALID",
    )
    _add_constraint(
        "chat.turn_commands",
        "command_canonical_hash_format",
        "CHECK (canonical_input_hash ~ '^[0-9a-f]{64}$') NOT VALID",
    )
    _add_constraint(
        "chat.turns",
        "turn_release_receipt_required",
        "CHECK (product_release_id IS NOT NULL AND permission_snapshot_id IS NOT NULL "
        "AND semantic_release_id IS NOT NULL) NOT VALID",
    )
    _add_constraint(
        "chat.turn_commands",
        "command_admission_receipt_required",
        "CHECK (effective_subject_id IS NOT NULL AND product_release_id IS NOT NULL "
        "AND permission_snapshot_id IS NOT NULL AND semantic_release_id IS NOT NULL) NOT VALID",
    )
    _add_constraint(
        "chat.analysis_requests",
        "conversation_run_receipt_required",
        "CHECK (command_id IS NULL OR (conversation_id IS NOT NULL "
        "AND product_release_id IS NOT NULL AND permission_snapshot_id IS NOT NULL "
        "AND semantic_release_id IS NOT NULL)) NOT VALID",
    )
    _add_constraint(
        "query.query_executions",
        "running_query_has_durable_cancel_receipt",
        "CHECK (execution_status <> 'RUNNING' OR (trino_query_id IS NOT NULL "
        "AND btrim(trino_query_id) <> '' AND trino_cancel_uri IS NOT NULL "
        "AND btrim(trino_cancel_uri) <> '')) NOT VALID",
    )
    _add_constraint(
        "artifact.analysis_artifacts",
        "artifact_release_receipt_complete",
        "CHECK (product_release_id IS NULL OR (permission_snapshot_id IS NOT NULL "
        "AND semantic_release_id IS NOT NULL)) NOT VALID",
    )
    _add_constraint(
        "artifact.view_specs",
        "view_release_receipt_complete",
        "CHECK (product_release_id IS NULL OR (permission_snapshot_id IS NOT NULL "
        "AND semantic_release_id IS NOT NULL)) NOT VALID",
    )
    _add_constraint(
        "context.context_packages",
        "context_release_receipt_complete",
        "CHECK (product_release_id IS NULL OR (permission_snapshot_id IS NOT NULL "
        "AND semantic_release_id IS NOT NULL)) NOT VALID",
    )
    for table, constraint in (
        ("chat.conversations", "conversation_product_release_fk"),
        ("chat.turns", "turn_product_release_fk"),
        ("chat.turn_commands", "command_product_release_fk"),
        ("chat.analysis_requests", "analysis_request_product_release_fk"),
        ("artifact.analysis_artifacts", "artifact_product_release_fk"),
        ("artifact.view_specs", "view_product_release_fk"),
        ("context.context_packages", "context_package_product_release_fk"),
    ):
        _add_constraint(
            table,
            constraint,
            "FOREIGN KEY (product_release_id) REFERENCES "
            "governance.product_release_manifests(product_release_id) NOT VALID",
        )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION chat.enforce_conversation_history_immutability()
        RETURNS trigger AS $$
        BEGIN
            IF TG_TABLE_NAME IN ('turns') THEN
                RAISE EXCEPTION 'conversation turns are immutable';
            END IF;
            IF TG_TABLE_NAME = 'turn_commands' THEN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'conversation commands are immutable';
                END IF;
                IF (
                    NEW.command_id, NEW.conversation_id, NEW.idempotency_key,
                    NEW.canonical_input_hash, NEW.expected_head_turn_id,
                    NEW.effective_subject_id, NEW.product_release_id,
                    NEW.permission_snapshot_id, NEW.semantic_release_id, NEW.created_at
                ) IS DISTINCT FROM (
                    OLD.command_id, OLD.conversation_id, OLD.idempotency_key,
                    OLD.canonical_input_hash, OLD.expected_head_turn_id,
                    OLD.effective_subject_id, OLD.product_release_id,
                    OLD.permission_snapshot_id, OLD.semantic_release_id, OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'conversation command admission is immutable';
                END IF;
                IF (OLD.status, NEW.status) NOT IN (
                    ('RUNNING','RUNNING'), ('RUNNING','COMPLETED'),
                    ('RUNNING','FAILED'), ('COMPLETED','COMPLETED'), ('FAILED','FAILED')
                ) THEN
                    RAISE EXCEPTION 'invalid conversation command terminal transition';
                END IF;
                IF OLD.status <> 'RUNNING' AND NEW IS DISTINCT FROM OLD THEN
                    RAISE EXCEPTION 'terminal conversation command is immutable';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS turns_immutable ON chat.turns"
    )
    op.execute(
        "CREATE TRIGGER turns_immutable BEFORE UPDATE OR DELETE ON chat.turns "
        "FOR EACH ROW EXECUTE FUNCTION chat.enforce_conversation_history_immutability()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS turn_commands_immutable ON chat.turn_commands"
    )
    op.execute(
        "CREATE TRIGGER turn_commands_immutable BEFORE UPDATE OR DELETE ON chat.turn_commands "
        "FOR EACH ROW EXECUTE FUNCTION chat.enforce_conversation_history_immutability()"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION artifact.reject_view_spec_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'view specs are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS view_specs_immutable ON artifact.view_specs")
    op.execute(
        "CREATE TRIGGER view_specs_immutable BEFORE UPDATE OR DELETE ON artifact.view_specs "
        "FOR EACH ROW EXECUTE FUNCTION artifact.reject_view_spec_mutation()"
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_chat_turns_conv ON chat.turns(conversation_id, turn_index)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_commands_recovery "
        "ON chat.turn_commands(status, created_at) WHERE status = 'RUNNING'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_view_specs_artifact ON artifact.view_specs(artifact_id)")

    role = _runtime_role()
    op.execute(f"GRANT SELECT, INSERT ON chat.turns TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON chat.turn_commands TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON artifact.view_specs TO {role}")
    op.execute(
        f"GRANT UPDATE (trino_cancel_uri, execution_status, row_count, scan_bytes, "
        f"error_code, error_message_redacted) "
        f"ON query.query_executions TO {role}"
    )
    op.execute(f"GRANT SELECT, INSERT ON chat.conversations TO {role}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE (head_turn_id, turn_count, active_command_id, "
        f"lease_expires_at, updated_at) ON chat.conversations TO {role}"
    )


def downgrade() -> None:
    """Phase 1 확장만 제거하되 migration 이전 수기 table은 보존한다."""

    role = _runtime_role()
    op.execute(
        f"REVOKE UPDATE (trino_cancel_uri, execution_status, row_count, scan_bytes, "
        f"error_code, error_message_redacted) "
        f"ON query.query_executions FROM {role}"
    )
    op.execute(
        f"REVOKE UPDATE (head_turn_id, turn_count, active_command_id, "
        f"lease_expires_at, updated_at) ON chat.conversations FROM {role}"
    )
    op.execute(f"REVOKE SELECT, INSERT ON chat.conversations FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT ON artifact.view_specs FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON chat.turn_commands FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT ON chat.turns FROM {role}")
    op.execute("DROP TRIGGER IF EXISTS view_specs_immutable ON artifact.view_specs")
    op.execute("DROP FUNCTION IF EXISTS artifact.reject_view_spec_mutation()")
    op.execute("DROP TRIGGER IF EXISTS turn_commands_immutable ON chat.turn_commands")
    op.execute("DROP TRIGGER IF EXISTS turns_immutable ON chat.turns")
    op.execute("DROP FUNCTION IF EXISTS chat.enforce_conversation_history_immutability()")
    op.execute("DROP INDEX IF EXISTS chat.idx_chat_commands_recovery")
    op.execute("DROP INDEX IF EXISTS chat.ux_analysis_requests_command_id")
    op.execute(
        "UPDATE chat.analysis_requests SET error_type = 'UNSUPPORTED' "
        "WHERE error_type = 'RECOVERY'"
    )
    op.execute(
        "ALTER TABLE chat.analysis_requests "
        "DROP CONSTRAINT IF EXISTS ck_chat_analysis_requests_error_type"
    )
    op.execute(
        "ALTER TABLE chat.analysis_requests "
        "ADD CONSTRAINT ck_chat_analysis_requests_error_type CHECK ("
        "error_type IS NULL OR error_type IN ("
        "'AMBIGUOUS','UNSUPPORTED','PERMISSION','QUERY','PARTIAL',"
        "'INSUFFICIENT_EVIDENCE','PERSISTENCE'))"
    )

    for table, constraint in (
        ("context.context_packages", "context_package_product_release_fk"),
        ("artifact.view_specs", "view_product_release_fk"),
        ("artifact.analysis_artifacts", "artifact_product_release_fk"),
        ("chat.analysis_requests", "analysis_request_product_release_fk"),
        ("chat.turn_commands", "command_product_release_fk"),
        ("chat.turns", "turn_product_release_fk"),
        ("chat.conversations", "conversation_product_release_fk"),
        ("context.context_packages", "context_release_receipt_complete"),
        ("artifact.view_specs", "view_release_receipt_complete"),
        ("artifact.analysis_artifacts", "artifact_release_receipt_complete"),
        ("chat.analysis_requests", "conversation_run_receipt_required"),
        ("query.query_executions", "running_query_has_durable_cancel_receipt"),
        ("chat.turn_commands", "command_admission_receipt_required"),
        ("chat.turns", "turn_release_receipt_required"),
        ("chat.conversations", "conversation_release_receipt_required"),
        ("chat.turn_commands", "command_canonical_hash_format"),
        ("chat.turn_commands", "command_idempotency_key_nonempty"),
        ("chat.turns", "turn_resolved_slots_object"),
        ("chat.turns", "turn_source_ids_array"),
        ("artifact.view_specs", "view_spec_json_object"),
    ):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")

    op.execute(
        "ALTER TABLE context.context_packages DROP COLUMN semantic_release_id, "
        "DROP COLUMN permission_snapshot_id, DROP COLUMN product_release_id"
    )
    op.execute(
        "ALTER TABLE artifact.view_specs DROP COLUMN semantic_release_id, "
        "DROP COLUMN permission_snapshot_id, DROP COLUMN product_release_id"
    )
    op.execute(
        "ALTER TABLE artifact.analysis_artifacts DROP COLUMN semantic_release_id, "
        "DROP COLUMN permission_snapshot_id, DROP COLUMN product_release_id"
    )
    op.execute(
        "ALTER TABLE chat.analysis_requests DROP COLUMN semantic_release_id, "
        "DROP COLUMN permission_snapshot_id, DROP COLUMN product_release_id, DROP COLUMN command_id"
    )
    op.execute(
        "ALTER TABLE chat.turn_commands DROP COLUMN terminal_at, DROP COLUMN semantic_release_id, "
        "DROP COLUMN permission_snapshot_id, DROP COLUMN product_release_id, "
        "DROP COLUMN effective_subject_id, DROP COLUMN expected_head_turn_id"
    )
    op.execute(
        "ALTER TABLE chat.turns DROP COLUMN semantic_release_id, "
        "DROP COLUMN permission_snapshot_id, DROP COLUMN product_release_id"
    )
    op.execute(
        "ALTER TABLE chat.conversations DROP COLUMN release_pinned_at, "
        "DROP COLUMN semantic_release_id, DROP COLUMN permission_snapshot_id, "
        "DROP COLUMN product_release_id"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM governance.phase_20260822_30_preexisting_objects
                WHERE object_name = 'column:query.query_executions.trino_cancel_uri'
            ) THEN
                ALTER TABLE query.query_executions
                    DROP COLUMN IF EXISTS trino_cancel_uri;
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        DO $$
        DECLARE column_name text;
        BEGIN
            FOREACH column_name IN ARRAY ARRAY[
                'head_turn_id', 'turn_count', 'active_command_id', 'lease_expires_at'
            ] LOOP
                IF NOT EXISTS (
                    SELECT 1
                    FROM governance.phase_20260822_30_preexisting_objects
                    WHERE object_name = 'column:chat.conversations.' || column_name
                ) THEN
                    EXECUTE format(
                        'ALTER TABLE chat.conversations DROP COLUMN IF EXISTS %I',
                        column_name
                    );
                END IF;
            END LOOP;
        END;
        $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM governance.phase_20260822_30_preexisting_objects
                WHERE object_name = 'index:chat.idx_chat_turns_conv'
            ) THEN
                DROP INDEX IF EXISTS chat.idx_chat_turns_conv;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM governance.phase_20260822_30_preexisting_objects
                WHERE object_name = 'index:artifact.idx_view_specs_artifact'
            ) THEN
                DROP INDEX IF EXISTS artifact.idx_view_specs_artifact;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM governance.phase_20260822_30_preexisting_objects
                WHERE object_name = 'table:chat.turn_commands'
            ) THEN
                DROP TABLE IF EXISTS chat.turn_commands;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM governance.phase_20260822_30_preexisting_objects
                WHERE object_name = 'table:chat.turns'
            ) THEN
                DROP TABLE IF EXISTS chat.turns;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM governance.phase_20260822_30_preexisting_objects
                WHERE object_name = 'table:artifact.view_specs'
            ) THEN
                DROP TABLE IF EXISTS artifact.view_specs;
            END IF;
        END;
        $$
        """
    )
    op.execute("DROP TABLE governance.phase_20260822_30_preexisting_objects")
