"""Immutable RuntimeCatalogProjection과 CAS activation pointer를 추가한다."""

import os
import re

from alembic import op


revision = "20260822_31"
down_revision = "20260822_30"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """Projection 내용·source receipt·활성 pointer·rollback 계보를 생성한다."""

    op.execute(
        """
        CREATE TABLE governance.runtime_catalog_projections (
            projection_id varchar(160) PRIMARY KEY
                CHECK (projection_id ~ '^runtime-catalog:[0-9a-f]{64}$'),
            contract_version varchar(64) NOT NULL
                CHECK (contract_version = 'RuntimeCatalogProjection.v1'),
            projection_sha256 char(64) NOT NULL UNIQUE
                CHECK (projection_sha256 ~ '^[0-9a-f]{64}$'),
            catalog_release_id varchar(256) NOT NULL
                CHECK (btrim(catalog_release_id) <> ''),
            catalog_sha256 char(64) NOT NULL
                CHECK (catalog_sha256 ~ '^[0-9a-f]{64}$'),
            canonical_sha256 char(64) NOT NULL
                CHECK (canonical_sha256 ~ '^[0-9a-f]{64}$'),
            manifest_sha256 char(64) NOT NULL
                CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
            membership_sha256 char(64) NOT NULL
                CHECK (membership_sha256 ~ '^[0-9a-f]{64}$'),
            source_selection_sha256 char(64) NOT NULL
                CHECK (source_selection_sha256 ~ '^[0-9a-f]{64}$'),
            trino_fingerprint_sha256 char(64) NOT NULL
                CHECK (trino_fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
            authority_mode varchar(32) NOT NULL
                CHECK (authority_mode IN ('NATIVE_PRIORITY','LEGACY_SHADOW')),
            projection_json jsonb NOT NULL
                CHECK (jsonb_typeof(projection_json) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (projection_id = 'runtime-catalog:' || projection_sha256),
            CHECK (
                projection_json ?& ARRAY[
                    'schema_version','projection_id','projection_sha256',
                    'catalog_release_id','catalog_sha256','canonical_sha256',
                    'manifest_sha256','membership_sha256',
                    'source_selection_sha256','trino_fingerprint_sha256',
                    'source_selection','trino_fingerprints','snapshot'
                ]
                AND projection_json->>'schema_version' = contract_version
                AND projection_json->>'projection_id' = projection_id
                AND projection_json->>'projection_sha256' = projection_sha256
                AND projection_json->>'catalog_release_id' = catalog_release_id
                AND projection_json->>'catalog_sha256' = catalog_sha256
                AND projection_json->>'canonical_sha256' = canonical_sha256
                AND projection_json->>'manifest_sha256' = manifest_sha256
                AND projection_json->>'membership_sha256' = membership_sha256
                AND projection_json->>'source_selection_sha256'
                    = source_selection_sha256
                AND projection_json->>'trino_fingerprint_sha256'
                    = trino_fingerprint_sha256
                AND projection_json #>> '{source_selection,authority_mode}'
                    = authority_mode
                AND jsonb_typeof(projection_json->'trino_fingerprints') = 'array'
                AND jsonb_typeof(projection_json->'snapshot') = 'object'
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE governance.runtime_catalog_active_pointer (
            pointer_name varchar(64) PRIMARY KEY
                CHECK (pointer_name = 'analysis'),
            projection_id varchar(160) NOT NULL
                REFERENCES governance.runtime_catalog_projections(projection_id),
            product_release_id varchar(160) NOT NULL
                REFERENCES governance.product_release_manifests(product_release_id),
            generation bigint NOT NULL CHECK (generation >= 1),
            activated_by varchar(160) NOT NULL CHECK (btrim(activated_by) <> ''),
            activated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE governance.runtime_catalog_activation_receipts (
            activation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            pointer_name varchar(64) NOT NULL CHECK (pointer_name = 'analysis'),
            action varchar(16) NOT NULL CHECK (action IN ('ACTIVATE','ROLLBACK')),
            previous_projection_id varchar(160)
                REFERENCES governance.runtime_catalog_projections(projection_id),
            previous_product_release_id varchar(160)
                REFERENCES governance.product_release_manifests(product_release_id),
            target_projection_id varchar(160) NOT NULL
                REFERENCES governance.runtime_catalog_projections(projection_id),
            target_product_release_id varchar(160) NOT NULL
                REFERENCES governance.product_release_manifests(product_release_id),
            expected_generation bigint NOT NULL CHECK (expected_generation >= 0),
            resulting_generation bigint NOT NULL,
            actor varchar(160) NOT NULL CHECK (btrim(actor) <> ''),
            reason varchar(500) NOT NULL CHECK (btrim(reason) <> ''),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (resulting_generation = expected_generation + 1),
            CHECK (
                (previous_projection_id IS NULL)
                = (previous_product_release_id IS NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE TRIGGER runtime_catalog_projections_immutable "
        "BEFORE UPDATE OR DELETE ON governance.runtime_catalog_projections "
        "FOR EACH ROW EXECUTE FUNCTION governance.reject_product_release_evidence_mutation()"
    )
    op.execute(
        "CREATE TRIGGER runtime_catalog_activation_receipts_immutable "
        "BEFORE UPDATE OR DELETE ON governance.runtime_catalog_activation_receipts "
        "FOR EACH ROW EXECUTE FUNCTION governance.reject_product_release_evidence_mutation()"
    )
    role = _runtime_role()
    op.execute(
        f"GRANT SELECT ON governance.runtime_catalog_projections, "
        f"governance.runtime_catalog_active_pointer, "
        f"governance.runtime_catalog_activation_receipts TO {role}"
    )


def downgrade() -> None:
    """Phase 4 projection·pointer·receipt만 의존성 역순으로 제거한다."""

    role = _runtime_role()
    op.execute(
        f"REVOKE SELECT ON governance.runtime_catalog_projections, "
        f"governance.runtime_catalog_active_pointer, "
        f"governance.runtime_catalog_activation_receipts FROM {role}"
    )
    op.execute(
        "DROP TRIGGER runtime_catalog_activation_receipts_immutable "
        "ON governance.runtime_catalog_activation_receipts"
    )
    op.execute(
        "DROP TRIGGER runtime_catalog_projections_immutable "
        "ON governance.runtime_catalog_projections"
    )
    op.execute("DROP TABLE governance.runtime_catalog_activation_receipts")
    op.execute("DROP TABLE governance.runtime_catalog_active_pointer")
    op.execute("DROP TABLE governance.runtime_catalog_projections")
