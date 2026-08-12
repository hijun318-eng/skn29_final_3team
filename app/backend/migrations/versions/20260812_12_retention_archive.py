"""Add append-only storage for expired audit metadata."""

from alembic import op


revision = "20260812_12"
down_revision = "20260812_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE governance.audit_events_archive
            (LIKE governance.audit_events INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)
        """
    )
    op.execute(
        "ALTER TABLE governance.audit_events_archive "
        "ADD COLUMN archived_at timestamptz NOT NULL DEFAULT now()"
    )
    op.execute(
        """
        CREATE FUNCTION governance.reject_audit_archive_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Archived audit metadata is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_archive_append_only
        BEFORE UPDATE OR DELETE ON governance.audit_events_archive
        FOR EACH ROW EXECUTE FUNCTION governance.reject_audit_archive_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE governance.audit_events_archive")
    op.execute("DROP FUNCTION governance.reject_audit_archive_mutation()")
