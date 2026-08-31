"""Analysis Artifact 원본과 분리된 사용자별 비파괴 보관 lifecycle을 추가한다."""

import os
import re

from alembic import op


revision = "20260831_66"
down_revision = "20260831_65"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    """환경의 제한된 runtime role만 SQL identifier로 허용한다."""

    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """원본 승인 상태를 보존하면서 owner별 archive·restore receipt를 저장한다."""

    op.execute(
        """
        CREATE TABLE artifact.user_artifact_lifecycle (
            owner_id uuid NOT NULL,
            artifact_id uuid NOT NULL
                REFERENCES artifact.analysis_artifacts(artifact_id) ON DELETE RESTRICT,
            archived_at timestamptz,
            archived_by uuid,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (owner_id, artifact_id),
            CONSTRAINT user_artifact_archive_pair_check CHECK (
                (archived_at IS NULL AND archived_by IS NULL)
                OR (archived_at IS NOT NULL AND archived_by IS NOT NULL)
            ),
            CONSTRAINT user_artifact_actor_owner_check CHECK (
                archived_by IS NULL OR archived_by = owner_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX user_artifact_archived_owner_idx "
        "ON artifact.user_artifact_lifecycle "
        "(owner_id, archived_at DESC, artifact_id) "
        "WHERE archived_at IS NOT NULL"
    )
    op.execute(
        """
        CREATE FUNCTION artifact.require_user_artifact_lifecycle_owner()
        RETURNS trigger AS $$
        BEGIN
            PERFORM 1
            FROM artifact.analysis_artifacts a
            JOIN chat.analysis_requests r ON r.request_id = a.request_id
            WHERE a.artifact_id = NEW.artifact_id
              AND r.user_id = NEW.owner_id
            FOR KEY SHARE OF a, r;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Analysis Artifact lifecycle owner does not match';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER user_artifact_lifecycle_requires_owner
        BEFORE INSERT OR UPDATE ON artifact.user_artifact_lifecycle
        FOR EACH ROW EXECUTE FUNCTION artifact.require_user_artifact_lifecycle_owner()
        """
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON artifact.user_artifact_lifecycle "
        f"TO {_runtime_role()}"
    )


def downgrade() -> None:
    """보관·복원 receipt가 없을 때만 lifecycle 경계를 안전하게 제거한다."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM artifact.user_artifact_lifecycle) THEN
                RAISE EXCEPTION 'Analysis Artifact lifecycle receipts must be preserved';
            END IF;
        END $$
        """
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE ON artifact.user_artifact_lifecycle "
        f"FROM {_runtime_role()}"
    )
    op.execute(
        "DROP TRIGGER user_artifact_lifecycle_requires_owner "
        "ON artifact.user_artifact_lifecycle"
    )
    op.execute("DROP FUNCTION artifact.require_user_artifact_lifecycle_owner()")
    op.execute("DROP INDEX artifact.user_artifact_archived_owner_idx")
    op.execute("DROP TABLE artifact.user_artifact_lifecycle")
