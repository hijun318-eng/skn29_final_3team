"""현행 4-role 인증 계정에 관리자 CRUD와 append-only 감사 계약을 추가한다."""

import os
import re

from alembic import op


revision = "20260828_55"
down_revision = "20260828_54"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """soft delete 상태, 최소 쓰기 권한과 변경 불가 감사 ledger를 활성화한다."""

    op.execute(
        "ALTER TABLE security.auth_accounts "
        "ADD COLUMN deactivated_at timestamptz, "
        "ADD COLUMN deleted_at timestamptz"
    )
    op.execute(
        "UPDATE security.auth_accounts "
        "SET deactivated_at = COALESCE(updated_at, now()) "
        "WHERE NOT active"
    )
    op.execute(
        "ALTER TABLE security.auth_accounts "
        "ADD CONSTRAINT ck_auth_accounts_deleted_inactive "
        "CHECK (deleted_at IS NULL OR NOT active), "
        "ADD CONSTRAINT ck_auth_accounts_deactivated_state CHECK ("
        "(active AND deactivated_at IS NULL) "
        "OR (NOT active AND deactivated_at IS NOT NULL))"
    )
    op.execute(
        "CREATE INDEX ix_auth_accounts_active_role "
        "ON security.auth_accounts (role, username) "
        "WHERE active AND deleted_at IS NULL"
    )
    op.execute(
        """
        CREATE FUNCTION governance.reject_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'governance.audit_events is append-only';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_append_only "
        "BEFORE UPDATE OR DELETE ON governance.audit_events "
        "FOR EACH ROW EXECUTE FUNCTION governance.reject_audit_event_mutation()"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_events_created "
        "ON governance.audit_events (created_at DESC, audit_event_id DESC)"
    )
    op.execute(
        f"GRANT INSERT, UPDATE ON security.auth_accounts TO {_runtime_role()}"
    )


def downgrade() -> None:
    """관리자 쓰기·soft delete·append-only 보강만 제거하고 기존 계정은 보존한다."""

    op.execute(
        f"REVOKE INSERT, UPDATE ON security.auth_accounts FROM {_runtime_role()}"
    )
    op.execute("DROP TRIGGER audit_events_append_only ON governance.audit_events")
    op.execute("DROP FUNCTION governance.reject_audit_event_mutation()")
    op.execute("DROP INDEX IF EXISTS governance.ix_audit_events_created")
    op.execute("DROP INDEX security.ix_auth_accounts_active_role")
    op.execute(
        "ALTER TABLE security.auth_accounts "
        "DROP CONSTRAINT ck_auth_accounts_deactivated_state, "
        "DROP CONSTRAINT ck_auth_accounts_deleted_inactive, "
        "DROP COLUMN deleted_at, "
        "DROP COLUMN deactivated_at"
    )
