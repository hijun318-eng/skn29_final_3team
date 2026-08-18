"""확정된 Report HTML/PDF document와 Artifact version snapshot을 불변 보관한다."""

import os
import re

from alembic import op


revision = "20260814_21"
down_revision = "20260814_20"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """불변 report document table·mutation 차단 trigger·읽기/삽입 권한을 추가한다."""

    op.execute(
        """
        CREATE TABLE report_v1.report_documents (
            definition_id uuid NOT NULL,
            definition_version integer NOT NULL,
            orientation varchar(16) NOT NULL CHECK (orientation IN ('portrait','landscape')),
            renderer_version varchar(40) NOT NULL,
            source_checksum varchar(64) NOT NULL CHECK (source_checksum ~ '^[0-9a-f]{64}$'),
            html_checksum varchar(64) NOT NULL CHECK (html_checksum ~ '^[0-9a-f]{64}$'),
            pdf_checksum varchar(64) NOT NULL CHECK (pdf_checksum ~ '^[0-9a-f]{64}$'),
            html_snapshot text NOT NULL CHECK (btrim(html_snapshot) <> ''),
            pdf_bytes bytea NOT NULL CHECK (octet_length(pdf_bytes) > 5),
            artifact_versions jsonb NOT NULL CHECK (jsonb_typeof(artifact_versions) = 'array'),
            confirmed_at timestamptz NOT NULL,
            PRIMARY KEY (definition_id, definition_version),
            FOREIGN KEY (definition_id, definition_version)
                REFERENCES report_v1.report_definition_versions(definition_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION report_v1.reject_report_document_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'confirmed Report documents are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER report_document_immutable
        BEFORE UPDATE OR DELETE ON report_v1.report_documents
        FOR EACH ROW EXECUTE FUNCTION report_v1.reject_report_document_mutation()
        """
    )
    role = _runtime_role()
    op.execute(f"GRANT SELECT, INSERT ON report_v1.report_documents TO {role}")


def downgrade() -> None:
    """document 권한·table·mutation 차단 function을 안전한 역순으로 제거한다."""

    role = _runtime_role()
    op.execute(f"REVOKE SELECT, INSERT ON report_v1.report_documents FROM {role}")
    op.execute("DROP TABLE report_v1.report_documents")
    op.execute("DROP FUNCTION report_v1.reject_report_document_mutation()")
