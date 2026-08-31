"""Analysis Artifact lifecycle 직렬화를 최소 권한 owner request lock으로 맞춘다."""

from alembic import op


revision = "20260831_69"
down_revision = "20260831_68"
branch_labels = None
depends_on = None


def _owner_guard(*, artifact_lock: bool) -> str:
    """runtime 권한에 맞는 lifecycle owner trigger 함수 SQL을 만든다."""

    lock_targets = "a, r" if artifact_lock else "r"
    return f"""
        CREATE OR REPLACE FUNCTION artifact.require_user_artifact_lifecycle_owner()
        RETURNS trigger AS $$
        BEGIN
            PERFORM 1
            FROM artifact.analysis_artifacts a
            JOIN chat.analysis_requests r ON r.request_id = a.request_id
            WHERE a.artifact_id = NEW.artifact_id
              AND r.user_id = NEW.owner_id
            FOR KEY SHARE OF {lock_targets};
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Analysis Artifact lifecycle owner does not match';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


def upgrade() -> None:
    """불변 Artifact 대신 기존 runtime UPDATE 권한이 있는 owner request를 잠근다."""

    op.execute(_owner_guard(artifact_lock=False))


def downgrade() -> None:
    """이전 Artifact·request 동시 row-lock trigger 계약으로 되돌린다."""

    op.execute(_owner_guard(artifact_lock=True))
