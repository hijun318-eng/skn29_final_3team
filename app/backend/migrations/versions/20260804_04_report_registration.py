"""기존 backend head 뒤에 REPORT-v1.0.0 persistence schema를 등록한다."""

import os
import re

from alembic import op


revision = "20260804_04"
down_revision = "20260731_03"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """owner-scoped Report 정의·block·run table과 최소권한 grant를 생성한다."""

    op.execute("CREATE SCHEMA report_v1")
    op.execute(
        """
        CREATE TABLE report_v1.report_definitions (
            definition_id uuid PRIMARY KEY,
            owner_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE report_v1.report_definition_versions (
            definition_id uuid NOT NULL REFERENCES report_v1.report_definitions(definition_id),
            version integer NOT NULL CHECK (version >= 1),
            status varchar(16) NOT NULL CHECK (status IN ('draft', 'approved')),
            title text NOT NULL,
            approved_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (definition_id, version),
            CHECK ((status = 'approved' AND approved_at IS NOT NULL)
                OR (status = 'draft' AND approved_at IS NULL))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE report_v1.report_blocks (
            definition_id uuid NOT NULL,
            definition_version integer NOT NULL,
            block_id uuid NOT NULL,
            title text NOT NULL,
            artifact_id uuid NOT NULL,
            query_id text,
            columns smallint NOT NULL CHECK (columns BETWEEN 1 AND 12),
            PRIMARY KEY (definition_id, definition_version, block_id),
            FOREIGN KEY (definition_id, definition_version)
                REFERENCES report_v1.report_definition_versions(definition_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE report_v1.report_runs (
            run_id uuid PRIMARY KEY,
            definition_id uuid NOT NULL,
            definition_version integer NOT NULL,
            as_of timestamptz NOT NULL,
            policy_version text NOT NULL,
            context_hash text NOT NULL,
            watermark jsonb NOT NULL,
            status varchar(16) NOT NULL CHECK (
                status IN ('queued', 'running', 'success', 'partial', 'failed', 'cancelled')
            ),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (definition_id, definition_version)
                REFERENCES report_v1.report_definition_versions(definition_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE report_v1.report_block_runs (
            run_id uuid NOT NULL REFERENCES report_v1.report_runs(run_id),
            block_id uuid NOT NULL,
            artifact_id uuid NOT NULL,
            query_id text NOT NULL,
            snapshot_checksum text NOT NULL,
            status varchar(16) NOT NULL CHECK (
                status IN ('success', 'partial', 'failed', 'cancelled')
            ),
            PRIMARY KEY (run_id, block_id)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION report_v1.reject_approved_version_mutation() RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'approved' THEN
                RAISE EXCEPTION 'approved Report version is immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER report_approved_version_immutable
        BEFORE UPDATE OR DELETE ON report_v1.report_definition_versions
        FOR EACH ROW EXECUTE FUNCTION report_v1.reject_approved_version_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION report_v1.reject_approved_block_mutation() RETURNS trigger AS $$
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
            IF EXISTS (
                SELECT 1 FROM report_v1.report_definition_versions
                WHERE definition_id = target_definition_id
                  AND version = target_version AND status = 'approved'
            ) THEN
                RAISE EXCEPTION 'approved Report blocks are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER report_approved_blocks_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON report_v1.report_blocks
        FOR EACH ROW EXECUTE FUNCTION report_v1.reject_approved_block_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION report_v1.require_approved_definition() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM report_v1.report_definition_versions
                WHERE definition_id = NEW.definition_id
                  AND version = NEW.definition_version
                  AND status = 'approved'
            ) THEN
                RAISE EXCEPTION 'only approved Report definitions can run';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER report_run_requires_approved_definition
        BEFORE INSERT ON report_v1.report_runs
        FOR EACH ROW EXECUTE FUNCTION report_v1.require_approved_definition()
        """
    )
    role = _runtime_role()
    op.execute(f"GRANT USAGE ON SCHEMA report_v1 TO {role}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA report_v1 TO {role}"
    )


def downgrade() -> None:
    """runtime 권한을 먼저 회수한 뒤 REPORT-v1 schema 전체를 제거한다."""

    role = _runtime_role()
    op.execute(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA report_v1 FROM {role}")
    op.execute(f"REVOKE USAGE ON SCHEMA report_v1 FROM {role}")
    op.execute("DROP SCHEMA report_v1 CASCADE")
