"""Versioned capability evidence와 제품 release object binding을 추가한다."""

import json
import os
import re

from alembic import op
from sqlalchemy import text


revision = "20260822_29"
down_revision = "20260820_28"
branch_labels = None
depends_on = None


_LEGACY_PRODUCT_RELEASE_ID = (
    "ANSWERVICE-LEGACY-UNVERIFIED-v1:"
    "d3ad30ebad6b36f0c0347df769096c886031fd59d3afd1d34feb88e98e7dcdb6"
)
_LEGACY_MANIFEST_SHA256 = (
    "8e097efb7b63385dc1dfdbcf009ae9c5f0f3707dcebe83df53b8f3aeb144c24e"
)
_ZERO_SHA256 = "0" * 64
_LEGACY_RELEASE_VECTOR = {
    "data_release_id": "legacy-unverified",
    "semantic_release_id": "legacy-unverified",
    "prompt_release_id": "legacy-unverified",
    "policy_release_id": "legacy-unverified",
    "runtime_release_id": "legacy-unverified",
}
_LEGACY_IMAGES = [
    {"component": "legacy-unverified", "digest": f"sha256:{_ZERO_SHA256}"}
]
_LEGACY_MANIFEST = {
    "schema_version": "ProductReleaseEvidenceManifest.v1",
    "product_release_id": _LEGACY_PRODUCT_RELEASE_ID,
    "evidence": {
        "source": {
            "commit_sha": "0" * 40,
            "dirty": False,
            "dirty_patch_sha256": None,
        },
        "images": _LEGACY_IMAGES,
        "migration": {
            "revision": "pre-20260822_30",
            "chain_sha256": _ZERO_SHA256,
        },
        "model": {
            "release_id": "legacy-unverified",
            "manifest_sha256": _ZERO_SHA256,
        },
        "catalog": {
            "release_id": "legacy-unverified",
            "manifest_sha256": _ZERO_SHA256,
            "projection_sha256": _ZERO_SHA256,
        },
        "release_vector": _LEGACY_RELEASE_VECTOR,
    },
    "created_at": "1970-01-01T00:00:00Z",
    "manifest_sha256": _LEGACY_MANIFEST_SHA256,
}


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def _insert_legacy_unverified_release() -> None:
    """기존 row를 새 release로 오표기하지 않도록 명시적인 sentinel을 봉인한다."""

    op.get_bind().execute(
        text(
            """
            INSERT INTO governance.product_release_manifests (
                product_release_id, contract_version, manifest_sha256,
                manifest_json, source_commit_sha, source_dirty,
                dirty_patch_sha256, image_digests_json, migration_revision,
                migration_chain_sha256, model_release_id,
                model_manifest_sha256, catalog_release_id,
                catalog_manifest_sha256, catalog_projection_sha256,
                release_vector_json, created_at
            ) VALUES (
                :product_release_id, 'ProductReleaseEvidenceManifest.v1',
                :manifest_sha256, CAST(:manifest_json AS jsonb),
                :source_commit_sha, false, NULL, CAST(:images_json AS jsonb),
                'pre-20260822_30', :zero_sha256, 'legacy-unverified',
                :zero_sha256, 'legacy-unverified', :zero_sha256,
                :zero_sha256, CAST(:release_vector_json AS jsonb),
                TIMESTAMPTZ '1970-01-01 00:00:00+00'
            )
            ON CONFLICT (product_release_id) DO NOTHING
            """
        ),
        {
            "product_release_id": _LEGACY_PRODUCT_RELEASE_ID,
            "manifest_sha256": _LEGACY_MANIFEST_SHA256,
            "manifest_json": json.dumps(
                _LEGACY_MANIFEST,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "source_commit_sha": "0" * 40,
            "images_json": json.dumps(_LEGACY_IMAGES, separators=(",", ":")),
            "zero_sha256": _ZERO_SHA256,
            "release_vector_json": json.dumps(
                _LEGACY_RELEASE_VECTOR,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    )


def upgrade() -> None:
    """불변 manifest와 7종 domain object의 release binding을 생성한다."""

    op.execute(
        """
        CREATE TABLE governance.product_release_manifests (
            product_release_id varchar(160) PRIMARY KEY
                CHECK (btrim(product_release_id) <> ''),
            contract_version varchar(64) NOT NULL
                CHECK (contract_version = 'ProductReleaseEvidenceManifest.v1'),
            manifest_sha256 char(64) NOT NULL UNIQUE
                CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
            manifest_json jsonb NOT NULL
                CHECK (jsonb_typeof(manifest_json) = 'object'),
            source_commit_sha varchar(64) NOT NULL
                CHECK (source_commit_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'),
            source_dirty boolean NOT NULL,
            dirty_patch_sha256 char(64)
                CHECK (dirty_patch_sha256 IS NULL OR dirty_patch_sha256 ~ '^[0-9a-f]{64}$'),
            image_digests_json jsonb NOT NULL
                CHECK (jsonb_typeof(image_digests_json) = 'array'
                       AND jsonb_array_length(image_digests_json) > 0),
            migration_revision varchar(64) NOT NULL CHECK (btrim(migration_revision) <> ''),
            migration_chain_sha256 char(64) NOT NULL
                CHECK (migration_chain_sha256 ~ '^[0-9a-f]{64}$'),
            model_release_id varchar(160) NOT NULL CHECK (btrim(model_release_id) <> ''),
            model_manifest_sha256 char(64) NOT NULL
                CHECK (model_manifest_sha256 ~ '^[0-9a-f]{64}$'),
            catalog_release_id varchar(256) NOT NULL CHECK (btrim(catalog_release_id) <> ''),
            catalog_manifest_sha256 char(64) NOT NULL
                CHECK (catalog_manifest_sha256 ~ '^[0-9a-f]{64}$'),
            catalog_projection_sha256 char(64) NOT NULL
                CHECK (catalog_projection_sha256 ~ '^[0-9a-f]{64}$'),
            release_vector_json jsonb NOT NULL
                CHECK (jsonb_typeof(release_vector_json) = 'object'
                       AND release_vector_json <> '{}'::jsonb),
            created_at timestamptz NOT NULL,
            CHECK (source_dirty = (dirty_patch_sha256 IS NOT NULL)),
            CHECK (
                manifest_json ?& ARRAY[
                    'schema_version','product_release_id','evidence',
                    'created_at','manifest_sha256'
                ]
                AND jsonb_typeof(manifest_json->'evidence') = 'object'
                AND (manifest_json->'evidence') ?& ARRAY[
                    'source','images','migration','model','catalog','release_vector'
                ]
                AND manifest_json->>'schema_version' = contract_version
                AND manifest_json->>'product_release_id' = product_release_id
                AND manifest_json->>'manifest_sha256' = manifest_sha256
                AND manifest_json #>> '{evidence,source,commit_sha}' = source_commit_sha
                AND (manifest_json #>> '{evidence,source,dirty}')::boolean = source_dirty
                AND manifest_json #>> '{evidence,source,dirty_patch_sha256}'
                    IS NOT DISTINCT FROM dirty_patch_sha256
                AND manifest_json #> '{evidence,images}' = image_digests_json
                AND manifest_json #>> '{evidence,migration,revision}' = migration_revision
                AND manifest_json #>> '{evidence,migration,chain_sha256}'
                    = migration_chain_sha256
                AND manifest_json #>> '{evidence,model,release_id}' = model_release_id
                AND manifest_json #>> '{evidence,model,manifest_sha256}'
                    = model_manifest_sha256
                AND manifest_json #>> '{evidence,catalog,release_id}' = catalog_release_id
                AND manifest_json #>> '{evidence,catalog,manifest_sha256}'
                    = catalog_manifest_sha256
                AND manifest_json #>> '{evidence,catalog,projection_sha256}'
                    = catalog_projection_sha256
                AND manifest_json #> '{evidence,release_vector}' = release_vector_json
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE governance.product_release_bindings (
            binding_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            object_kind varchar(16) NOT NULL CHECK (object_kind IN (
                'CONVERSATION','TURN','CONTEXT','RUN','ARTIFACT','VIEW','REPORT'
            )),
            object_id varchar(256) NOT NULL CHECK (btrim(object_id) <> ''),
            product_release_id varchar(160) NOT NULL
                REFERENCES governance.product_release_manifests(product_release_id),
            permission_snapshot_id varchar(160) NOT NULL
                CHECK (btrim(permission_snapshot_id) <> ''),
            semantic_release_id varchar(256) NOT NULL
                CHECK (btrim(semantic_release_id) <> ''),
            capability_release_vector_json jsonb NOT NULL
                CHECK (jsonb_typeof(capability_release_vector_json) = 'object'
                       AND capability_release_vector_json <> '{}'::jsonb),
            evidence_refs_json jsonb NOT NULL
                CHECK (jsonb_typeof(evidence_refs_json) = 'array'),
            bound_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (object_kind, object_id)
        )
        """
    )
    _insert_legacy_unverified_release()
    op.execute(
        """
        CREATE FUNCTION governance.reject_product_release_evidence_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'product release evidence is immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("product_release_manifests", "product_release_bindings"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE "
            f"ON governance.{table} FOR EACH ROW "
            "EXECUTE FUNCTION governance.reject_product_release_evidence_mutation()"
        )
    role = _runtime_role()
    op.execute(f"GRANT SELECT, INSERT ON governance.product_release_manifests TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON governance.product_release_bindings TO {role}")


def downgrade() -> None:
    """추가한 grant·binding·manifest·trigger function을 의존성 역순으로 제거한다."""

    role = _runtime_role()
    op.execute(f"REVOKE SELECT, INSERT ON governance.product_release_bindings FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT ON governance.product_release_manifests FROM {role}")
    op.execute("DROP TABLE governance.product_release_bindings")
    op.execute("DROP TABLE governance.product_release_manifests")
    op.execute("DROP FUNCTION governance.reject_product_release_evidence_mutation()")
