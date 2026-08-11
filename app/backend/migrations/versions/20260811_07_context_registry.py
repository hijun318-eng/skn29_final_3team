"""Add Context Registry idempotency and immutable state enforcement."""

import os
import re

from alembic import op


revision = "20260811_07"
down_revision = "20260810_06"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    for table, identifier in (
        ("context_records", "context_record_id"),
        ("context_releases", "context_release_id"),
        ("context_packages", "context_package_id"),
    ):
        op.execute(
            f"ALTER TABLE context.{table} "
            "ADD COLUMN IF NOT EXISTS idempotency_key varchar(128)"
        )
        op.execute(
            f"UPDATE context.{table} SET idempotency_key = "
            f"'legacy:' || {identifier}::text WHERE idempotency_key IS NULL"
        )
        op.execute(
            f"ALTER TABLE context.{table} ALTER COLUMN idempotency_key SET NOT NULL"
        )
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_idempotency_key "
            f"ON context.{table}(idempotency_key)"
        )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION context.enforce_registry_immutability()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF TG_TABLE_NAME = 'context_packages' THEN
                    RAISE EXCEPTION 'Context package is immutable';
                ELSIF OLD.status <> 'DRAFT' THEN
                    RAISE EXCEPTION 'Published Context Registry data is immutable';
                END IF;
                RETURN OLD;
            END IF;

            IF TG_TABLE_NAME = 'context_records' THEN
                IF (OLD.status, NEW.status) NOT IN (
                    ('DRAFT', 'DRAFT'), ('DRAFT', 'APPROVED'),
                    ('APPROVED', 'APPROVED'), ('APPROVED', 'DEPRECATED'),
                    ('DEPRECATED', 'DEPRECATED')
                ) THEN
                    RAISE EXCEPTION 'Invalid Context record status transition';
                END IF;
                IF OLD.status <> 'DRAFT' AND (
                    NEW.record_type, NEW.record_key, NEW.version_no, NEW.payload_json,
                    NEW.owner_role, NEW.valid_from, NEW.valid_to, NEW.checksum,
                    NEW.idempotency_key
                ) IS DISTINCT FROM (
                    OLD.record_type, OLD.record_key, OLD.version_no, OLD.payload_json,
                    OLD.owner_role, OLD.valid_from, OLD.valid_to, OLD.checksum,
                    OLD.idempotency_key
                ) THEN
                    RAISE EXCEPTION 'Approved Context record payload is immutable';
                END IF;
            ELSIF TG_TABLE_NAME = 'context_releases' THEN
                IF (OLD.status, NEW.status) NOT IN (
                    ('DRAFT', 'DRAFT'), ('DRAFT', 'PUBLISHED'),
                    ('PUBLISHED', 'PUBLISHED'), ('PUBLISHED', 'RETIRED'),
                    ('RETIRED', 'RETIRED')
                ) THEN
                    RAISE EXCEPTION 'Invalid Context release status transition';
                END IF;
                IF OLD.status <> 'DRAFT' AND (
                    NEW.release_key, NEW.version_no, NEW.included_record_refs_json,
                    NEW.release_hash, NEW.rollback_release_id, NEW.idempotency_key
                ) IS DISTINCT FROM (
                    OLD.release_key, OLD.version_no, OLD.included_record_refs_json,
                    OLD.release_hash, OLD.rollback_release_id, OLD.idempotency_key
                ) THEN
                    RAISE EXCEPTION 'Published Context release payload is immutable';
                END IF;
            ELSIF TG_TABLE_NAME = 'context_packages' THEN
                RAISE EXCEPTION 'Context package is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("context_records", "context_releases", "context_packages"):
        op.execute(
            f"CREATE TRIGGER {table}_registry_immutable "
            f"BEFORE UPDATE OR DELETE ON context.{table} FOR EACH ROW "
            "EXECUTE FUNCTION context.enforce_registry_immutability()"
        )

    op.execute(
        """
        ALTER TABLE context.context_records
        ADD CONSTRAINT ck_context_records_approved_actor
        CHECK (status <> 'APPROVED' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
        """
    )
    op.execute(
        """
        ALTER TABLE context.context_releases
        ADD CONSTRAINT ck_context_releases_published_actor
        CHECK (status <> 'PUBLISHED' OR (published_by IS NOT NULL AND published_at IS NOT NULL))
        """
    )
    role = _runtime_role()
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON context.context_records TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON context.context_releases TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON context.context_packages TO {role}")


def downgrade() -> None:
    role = _runtime_role()
    op.execute(f"REVOKE SELECT, INSERT ON context.context_packages FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON context.context_releases FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON context.context_records FROM {role}")
    op.execute(
        "ALTER TABLE context.context_releases "
        "DROP CONSTRAINT IF EXISTS ck_context_releases_published_actor"
    )
    op.execute(
        "ALTER TABLE context.context_records "
        "DROP CONSTRAINT IF EXISTS ck_context_records_approved_actor"
    )
    for table in ("context_packages", "context_releases", "context_records"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_registry_immutable ON context.{table}")
    op.execute("DROP FUNCTION IF EXISTS context.enforce_registry_immutability()")
    for table in ("context_packages", "context_releases", "context_records"):
        op.execute(f"DROP INDEX IF EXISTS context.ux_{table}_idempotency_key")
        op.execute(
            f"ALTER TABLE context.{table} DROP COLUMN IF EXISTS idempotency_key"
        )
