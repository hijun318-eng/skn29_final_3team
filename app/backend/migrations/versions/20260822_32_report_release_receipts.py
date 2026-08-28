"""Report definition/run에 immutable product release receipt를 추가한다."""

from alembic import op


revision = "20260822_32"
down_revision = "20260822_31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 행은 보존하고 신규 Report lifecycle이 complete receipt를 저장하게 한다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_definition_versions
            ADD COLUMN product_release_id varchar(160),
            ADD COLUMN permission_snapshot_id varchar(160),
            ADD COLUMN semantic_release_id varchar(256)
        """
    )
    op.execute(
        """
        ALTER TABLE report_v1.report_runs
            ADD COLUMN product_release_id varchar(160),
            ADD COLUMN permission_snapshot_id varchar(160),
            ADD COLUMN semantic_release_id varchar(256)
        """
    )
    op.execute(
        """
        ALTER TABLE report_v1.report_definition_versions
            ADD CONSTRAINT report_definition_release_receipt_complete
            CHECK (
                (product_release_id IS NULL
                 AND permission_snapshot_id IS NULL
                 AND semantic_release_id IS NULL)
                OR
                (product_release_id IS NOT NULL
                 AND permission_snapshot_id IS NOT NULL
                 AND semantic_release_id IS NOT NULL)
            ) NOT VALID,
            ADD CONSTRAINT report_definition_product_release_fk
            FOREIGN KEY (product_release_id)
            REFERENCES governance.product_release_manifests(product_release_id)
            NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE report_v1.report_runs
            ADD CONSTRAINT report_run_release_receipt_complete
            CHECK (
                (product_release_id IS NULL
                 AND permission_snapshot_id IS NULL
                 AND semantic_release_id IS NULL)
                OR
                (product_release_id IS NOT NULL
                 AND permission_snapshot_id IS NOT NULL
                 AND semantic_release_id IS NOT NULL)
            ) NOT VALID,
            ADD CONSTRAINT report_run_product_release_fk
            FOREIGN KEY (product_release_id)
            REFERENCES governance.product_release_manifests(product_release_id)
            NOT VALID
        """
    )
    op.execute(
        """
        CREATE FUNCTION report_v1.reject_release_receipt_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF (
                NEW.product_release_id,
                NEW.permission_snapshot_id,
                NEW.semantic_release_id
            ) IS DISTINCT FROM (
                OLD.product_release_id,
                OLD.permission_snapshot_id,
                OLD.semantic_release_id
            ) THEN
                RAISE EXCEPTION 'Report release receipt is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER report_definition_release_receipt_immutable "
        "BEFORE UPDATE ON report_v1.report_definition_versions "
        "FOR EACH ROW EXECUTE FUNCTION report_v1.reject_release_receipt_mutation()"
    )
    op.execute(
        "CREATE TRIGGER report_run_release_receipt_immutable "
        "BEFORE UPDATE ON report_v1.report_runs "
        "FOR EACH ROW EXECUTE FUNCTION report_v1.reject_release_receipt_mutation()"
    )


def downgrade() -> None:
    """Phase 4 Report receipt columns와 해당 불변 경계만 제거한다."""

    op.execute(
        "DROP TRIGGER report_run_release_receipt_immutable "
        "ON report_v1.report_runs"
    )
    op.execute(
        "DROP TRIGGER report_definition_release_receipt_immutable "
        "ON report_v1.report_definition_versions"
    )
    op.execute("DROP FUNCTION report_v1.reject_release_receipt_mutation()")
    op.execute(
        "ALTER TABLE report_v1.report_runs "
        "DROP CONSTRAINT report_run_product_release_fk, "
        "DROP CONSTRAINT report_run_release_receipt_complete, "
        "DROP COLUMN semantic_release_id, "
        "DROP COLUMN permission_snapshot_id, "
        "DROP COLUMN product_release_id"
    )
    op.execute(
        "ALTER TABLE report_v1.report_definition_versions "
        "DROP CONSTRAINT report_definition_product_release_fk, "
        "DROP CONSTRAINT report_definition_release_receipt_complete, "
        "DROP COLUMN semantic_release_id, "
        "DROP COLUMN permission_snapshot_id, "
        "DROP COLUMN product_release_id"
    )
