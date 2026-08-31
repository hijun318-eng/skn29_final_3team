"""Report definition에 비파괴 보관 상태와 쓰기 차단 경계를 추가한다."""

from alembic import op


revision = "20260831_65"
down_revision = "20260831_64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """보관 metadata와 부모 row lock 기반의 active-only 쓰기 제약을 등록한다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_definitions
            ADD COLUMN archived_at timestamptz,
            ADD COLUMN archived_by uuid,
            ADD CONSTRAINT report_definition_archive_pair_check CHECK (
                (archived_at IS NULL AND archived_by IS NULL)
                OR (archived_at IS NOT NULL AND archived_by IS NOT NULL)
            )
        """
    )
    op.execute(
        "CREATE INDEX report_definition_active_owner_idx "
        "ON report_v1.report_definitions (owner_id, created_at DESC, definition_id) "
        "WHERE archived_at IS NULL"
    )
    op.execute(
        "CREATE INDEX report_definition_archived_owner_idx "
        "ON report_v1.report_definitions (owner_id, archived_at DESC, definition_id) "
        "WHERE archived_at IS NOT NULL"
    )

    op.execute(
        """
        CREATE FUNCTION report_v1.reject_archived_report_content_mutation()
        RETURNS trigger AS $$
        DECLARE
            target_definition_id uuid;
        BEGIN
            target_definition_id := CASE
                WHEN TG_OP = 'DELETE' THEN OLD.definition_id
                ELSE NEW.definition_id
            END;
            PERFORM 1
            FROM report_v1.report_definitions
            WHERE definition_id = target_definition_id
              AND archived_at IS NULL
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'archived Report definition is read-only';
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
        CREATE TRIGGER report_definition_version_requires_active_definition
        BEFORE INSERT OR UPDATE OR DELETE ON report_v1.report_definition_versions
        FOR EACH ROW EXECUTE FUNCTION report_v1.reject_archived_report_content_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER report_block_requires_active_definition
        BEFORE INSERT OR UPDATE OR DELETE ON report_v1.report_blocks
        FOR EACH ROW EXECUTE FUNCTION report_v1.reject_archived_report_content_mutation()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION report_v1.require_approved_definition()
        RETURNS trigger AS $$
        BEGIN
            PERFORM 1
            FROM report_v1.report_definition_versions version
            JOIN report_v1.report_definitions definition USING (definition_id)
            WHERE version.definition_id = NEW.definition_id
              AND version.version = NEW.definition_version
              AND version.status = 'approved'
              AND definition.archived_at IS NULL
            FOR KEY SHARE OF definition;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'only active approved Report definitions can run';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.execute(
        """
        CREATE FUNCTION report_v1.require_active_report_schedule()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' OR NEW.enabled THEN
                PERFORM 1
                FROM report_v1.report_definitions
                WHERE definition_id = NEW.definition_id
                  AND archived_at IS NULL
                FOR KEY SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'archived Report schedule cannot be enabled';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER report_schedule_requires_active_definition
        BEFORE INSERT OR UPDATE ON report_v1.report_schedules
        FOR EACH ROW EXECUTE FUNCTION report_v1.require_active_report_schedule()
        """
    )

    op.execute(
        """
        CREATE FUNCTION report_v1.require_active_report_assistant_definition()
        RETURNS trigger AS $$
        DECLARE
            target_definition_id uuid;
        BEGIN
            IF TG_OP = 'INSERT'
               OR NEW.status = 'running'
               OR NEW.phase NOT IN ('completed', 'failed', 'cancelled') THEN
                FOR target_definition_id IN
                    SELECT DISTINCT definition_id
                    FROM (VALUES
                        (NEW.session_definition_id),
                        (NEW.definition_id)
                    ) AS referenced(definition_id)
                    WHERE definition_id IS NOT NULL
                LOOP
                    PERFORM 1
                    FROM report_v1.report_definitions
                    WHERE definition_id = target_definition_id
                      AND archived_at IS NULL
                    FOR KEY SHARE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'archived Report Assistant session is read-only';
                    END IF;
                END LOOP;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER report_assistant_requires_active_definition
        BEFORE INSERT OR UPDATE ON report_v1.report_assistant_requests
        FOR EACH ROW EXECUTE FUNCTION report_v1.require_active_report_assistant_definition()
        """
    )


def downgrade() -> None:
    """보관 이력이 남아 있지 않을 때만 직전 active-only schema로 되돌린다."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM report_v1.report_definitions
                WHERE archived_at IS NOT NULL OR archived_by IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'archived Report definitions must be restored before downgrade';
            END IF;
        END $$
        """
    )
    op.execute(
        "DROP TRIGGER report_assistant_requires_active_definition "
        "ON report_v1.report_assistant_requests"
    )
    op.execute("DROP FUNCTION report_v1.require_active_report_assistant_definition()")
    op.execute(
        "DROP TRIGGER report_schedule_requires_active_definition "
        "ON report_v1.report_schedules"
    )
    op.execute("DROP FUNCTION report_v1.require_active_report_schedule()")
    op.execute(
        "DROP TRIGGER report_block_requires_active_definition "
        "ON report_v1.report_blocks"
    )
    op.execute(
        "DROP TRIGGER report_definition_version_requires_active_definition "
        "ON report_v1.report_definition_versions"
    )
    op.execute("DROP FUNCTION report_v1.reject_archived_report_content_mutation()")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION report_v1.require_approved_definition()
        RETURNS trigger AS $$
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
    op.execute("DROP INDEX report_v1.report_definition_archived_owner_idx")
    op.execute("DROP INDEX report_v1.report_definition_active_owner_idx")
    op.execute(
        """
        ALTER TABLE report_v1.report_definitions
            DROP CONSTRAINT report_definition_archive_pair_check,
            DROP COLUMN archived_by,
            DROP COLUMN archived_at
        """
    )
