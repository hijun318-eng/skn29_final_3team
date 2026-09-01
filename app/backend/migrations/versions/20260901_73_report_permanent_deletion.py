"""휴지통 보고서의 복원 불가능한 삭제와 최소 감사 보존 경계를 추가한다."""

import os
import re

from alembic import op


revision = "20260901_73"
down_revision = "20260901_72"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    """환경의 제한된 runtime role만 SQL identifier로 허용한다."""

    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """보관·권한 검사를 내장한 SECURITY DEFINER purge 함수와 제한적 trigger 예외를 설치한다."""

    op.execute(
        """
        CREATE OR REPLACE FUNCTION report_v1.reject_approved_version_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND current_setting('report_v1.permanent_delete_definition_id', true)
                   = OLD.definition_id::text THEN
                RETURN OLD;
            END IF;
            IF OLD.status = 'approved' THEN
                RAISE EXCEPTION 'approved Report version is immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION report_v1.reject_approved_block_mutation()
        RETURNS trigger AS $$
        DECLARE
            target_definition_id uuid;
            target_version integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                target_definition_id := OLD.definition_id;
                target_version := OLD.definition_version;
            ELSE
                target_definition_id := NEW.definition_id;
                target_version := NEW.definition_version;
            END IF;
            IF TG_OP = 'DELETE'
               AND current_setting('report_v1.permanent_delete_definition_id', true)
                   = target_definition_id::text THEN
                RETURN OLD;
            END IF;
            IF EXISTS (
                SELECT 1 FROM report_v1.report_definition_versions
                WHERE definition_id = target_definition_id
                  AND version = target_version AND status = 'approved'
            ) THEN
                RAISE EXCEPTION 'approved Report blocks are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION report_v1.reject_archived_report_content_mutation()
        RETURNS trigger AS $$
        DECLARE
            target_definition_id uuid;
        BEGIN
            target_definition_id := CASE
                WHEN TG_OP = 'DELETE' THEN OLD.definition_id
                ELSE NEW.definition_id
            END;
            IF TG_OP = 'DELETE'
               AND current_setting('report_v1.permanent_delete_definition_id', true)
                   = target_definition_id::text THEN
                RETURN OLD;
            END IF;
            PERFORM 1
            FROM report_v1.report_definitions
            WHERE definition_id = target_definition_id
              AND archived_at IS NULL
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'archived Report definition is read-only';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION report_v1.reject_report_document_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND current_setting('report_v1.permanent_delete_definition_id', true)
                   = OLD.definition_id::text THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'confirmed Report documents are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION chat.enforce_conversation_history_immutability()
        RETURNS trigger AS $$
        BEGIN
            IF TG_TABLE_NAME = 'turns' THEN
                IF TG_OP = 'UPDATE'
                   AND OLD.report_draft_definition_id IS NOT NULL
                   AND current_setting('report_v1.permanent_delete_definition_id', true)
                       = OLD.report_draft_definition_id::text
                   AND NEW.report_draft_definition_id IS NULL
                   AND (to_jsonb(NEW) - 'report_draft_definition_id')
                       IS NOT DISTINCT FROM
                       (to_jsonb(OLD) - 'report_draft_definition_id') THEN
                    RETURN NEW;
                END IF;
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
        """
        CREATE FUNCTION report_v1.permanently_delete_archived_definition(
            target_definition_id uuid,
            effective_owner_id uuid,
            manage_all boolean,
            effective_actor_role text,
            effective_trace_id text
        ) RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            archived_at_value timestamptz;
        BEGIN
            SELECT definition.archived_at
            INTO archived_at_value
            FROM report_v1.report_definitions definition
            WHERE definition.definition_id = target_definition_id
              AND (manage_all OR definition.owner_id = effective_owner_id)
            FOR UPDATE;
            IF NOT FOUND THEN RETURN 'not_found'; END IF;
            IF archived_at_value IS NULL THEN RETURN 'requires_archive'; END IF;

            PERFORM set_config(
                'report_v1.permanent_delete_definition_id',
                target_definition_id::text,
                true
            );

            UPDATE chat.turns
            SET report_draft_definition_id = NULL
            WHERE report_draft_definition_id = target_definition_id;

            DELETE FROM report_v1.report_assistant_turns
            WHERE assistant_request_id IN (
                SELECT assistant_request_id
                FROM report_v1.report_assistant_requests
                WHERE session_definition_id = target_definition_id
                   OR definition_id = target_definition_id
            );
            DELETE FROM report_v1.report_assistant_artifact_bindings
            WHERE assistant_request_id IN (
                SELECT assistant_request_id
                FROM report_v1.report_assistant_requests
                WHERE session_definition_id = target_definition_id
                   OR definition_id = target_definition_id
            );
            UPDATE report_v1.report_assistant_evaluations evaluation
            SET definition_id = NULL,
                definition_version = NULL,
                revision_created = false
            WHERE evaluation.assistant_request_id IN (
                SELECT assistant_request_id
                FROM report_v1.report_assistant_requests
                WHERE session_definition_id = target_definition_id
                   OR definition_id = target_definition_id
            );
            UPDATE report_v1.report_assistant_requests
            SET status = 'failed',
                definition_id = NULL,
                definition_version = NULL,
                output_hash = NULL,
                error_code = 'REPORT_PERMANENTLY_DELETED',
                completed_at = COALESCE(completed_at, now()),
                phase = NULL,
                session_definition_id = NULL,
                session_definition_version = NULL,
                base_revision = NULL,
                analysis_plan_json = NULL,
                data_request_id = NULL,
                decision_hash = NULL,
                approved_at = NULL,
                rejected_at = NULL,
                result_revision = NULL,
                report_patch_json = NULL,
                patch_request_id = NULL,
                patch_preview_json = NULL,
                approved_operation_indexes = NULL,
                source_instruction = NULL,
                exact_page_count = NULL,
                verified_page_count = NULL,
                page_renderer_fingerprint = NULL,
                model_execution_id = NULL,
                model_execution_node = NULL,
                model_execution_message_revision = NULL,
                model_execution_expires_at = NULL
            WHERE session_definition_id = target_definition_id
               OR definition_id = target_definition_id;

            DELETE FROM report_v1.report_schedules
            WHERE definition_id = target_definition_id;
            DELETE FROM report_v1.report_manual_run_commands
            WHERE definition_id = target_definition_id;
            DELETE FROM report_v1.report_block_runs
            WHERE run_id IN (
                SELECT run_id FROM report_v1.report_runs
                WHERE definition_id = target_definition_id
            );
            DELETE FROM report_v1.report_runs
            WHERE definition_id = target_definition_id;
            DELETE FROM report_v1.report_documents
            WHERE definition_id = target_definition_id;
            DELETE FROM report_v1.report_blocks
            WHERE definition_id = target_definition_id;
            DELETE FROM report_v1.report_definition_versions
            WHERE definition_id = target_definition_id;
            DELETE FROM report_v1.report_definitions
            WHERE definition_id = target_definition_id;

            INSERT INTO governance.audit_events (
                actor_user_id, actor_role, action_code,
                object_type, object_id, details_json_redacted, trace_id
            ) VALUES (
                effective_owner_id, effective_actor_role,
                'REPORT_PERMANENTLY_DELETED', 'REPORT_DEFINITION',
                target_definition_id::text,
                '{"deletion_mode":"permanent","retained_evidence":"audit_and_external_transfer"}'::jsonb,
                effective_trace_id
            );
            RETURN 'deleted';
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION report_v1.permanently_delete_archived_definition"
        "(uuid, uuid, boolean, text, text) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION report_v1.permanently_delete_archived_definition"
        f"(uuid, uuid, boolean, text, text) TO {_runtime_role()}"
    )


def downgrade() -> None:
    """purge 진입점을 제거한다. 이미 영구삭제된 데이터와 감사 이벤트는 복원하지 않는다."""

    op.execute(
        "REVOKE EXECUTE ON FUNCTION report_v1.permanently_delete_archived_definition"
        f"(uuid, uuid, boolean, text, text) FROM {_runtime_role()}"
    )
    op.execute(
        "DROP FUNCTION report_v1.permanently_delete_archived_definition"
        "(uuid, uuid, boolean, text, text)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION report_v1.reject_approved_version_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'approved' THEN
                RAISE EXCEPTION 'approved Report version is immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE OR REPLACE FUNCTION report_v1.reject_approved_block_mutation()
        RETURNS trigger AS $$
        DECLARE target_definition_id uuid; target_version integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                target_definition_id := OLD.definition_id;
                target_version := OLD.definition_version;
            ELSE
                target_definition_id := NEW.definition_id;
                target_version := NEW.definition_version;
            END IF;
            IF EXISTS (
                SELECT 1 FROM report_v1.report_definition_versions
                WHERE definition_id = target_definition_id
                  AND version = target_version AND status = 'approved'
            ) THEN RAISE EXCEPTION 'approved Report blocks are immutable'; END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE OR REPLACE FUNCTION report_v1.reject_report_document_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'confirmed Report documents are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION report_v1.reject_archived_report_content_mutation()
        RETURNS trigger AS $$
        DECLARE target_definition_id uuid;
        BEGIN
            target_definition_id := CASE
                WHEN TG_OP = 'DELETE' THEN OLD.definition_id
                ELSE NEW.definition_id
            END;
            PERFORM 1 FROM report_v1.report_definitions
            WHERE definition_id = target_definition_id AND archived_at IS NULL
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'archived Report definition is read-only';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
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
                IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'conversation commands are immutable'; END IF;
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
                ) THEN RAISE EXCEPTION 'conversation command admission is immutable'; END IF;
                IF (OLD.status, NEW.status) NOT IN (
                    ('RUNNING','RUNNING'), ('RUNNING','COMPLETED'),
                    ('RUNNING','FAILED'), ('COMPLETED','COMPLETED'), ('FAILED','FAILED')
                ) THEN RAISE EXCEPTION 'invalid conversation command terminal transition'; END IF;
                IF OLD.status <> 'RUNNING' AND NEW IS DISTINCT FROM OLD THEN
                    RAISE EXCEPTION 'terminal conversation command is immutable';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
