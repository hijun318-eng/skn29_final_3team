"""승인 Semantic Request snapshot과 Analysis Definition 결속을 불변 저장한다."""

import os
import re

from alembic import op


revision = "20260831_60"
down_revision = "20260830_59"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    """환경의 runtime DB role을 SQL identifier 규칙으로 제한해 반환한다."""

    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """독립 snapshot table과 nullable legacy Definition 참조를 추가한다."""

    op.execute(
        """
        CREATE TABLE analysis_v1.approved_semantic_request_snapshots (
            snapshot_id uuid PRIMARY KEY,
            source_request_id uuid NOT NULL UNIQUE
                REFERENCES chat.analysis_requests(request_id) ON DELETE RESTRICT,
            owner_id uuid NOT NULL,
            query_execution_id uuid NOT NULL UNIQUE
                REFERENCES query.query_executions(query_execution_id) ON DELETE RESTRICT,
            artifact_id uuid NOT NULL UNIQUE
                REFERENCES artifact.analysis_artifacts(artifact_id) ON DELETE RESTRICT,
            schema_version varchar(96) NOT NULL
                CHECK (schema_version = 'ANSWERVICE-APPROVED-SEMANTIC-REQUEST-v1'),
            snapshot_json jsonb NOT NULL,
            snapshot_hash varchar(64) NOT NULL
                CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
            product_release_id varchar(160) NOT NULL,
            permission_snapshot_id varchar(160) NOT NULL,
            semantic_release_id varchar(160) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (jsonb_typeof(snapshot_json) = 'object'),
            CHECK (jsonb_typeof(snapshot_json->'analysis_plan') IS NOT NULL
                AND jsonb_typeof(snapshot_json->'analysis_plan') = 'object'),
            CHECK (jsonb_typeof(snapshot_json->'parameter_bindings') IS NOT NULL
                AND jsonb_typeof(snapshot_json->'parameter_bindings') = 'array'),
            CHECK (jsonb_typeof(snapshot_json->'dimension_member_receipts') IS NOT NULL
                AND jsonb_typeof(snapshot_json->'dimension_member_receipts') = 'array'),
            CHECK (jsonb_typeof(snapshot_json->'lineage') IS NOT NULL
                AND jsonb_typeof(snapshot_json->'lineage') = 'object'),
            CHECK (jsonb_typeof(snapshot_json->'release_receipt') IS NOT NULL
                AND jsonb_typeof(snapshot_json->'release_receipt') = 'object'),
            CHECK (snapshot_json->>'snapshot_id' IS NOT NULL
                AND snapshot_json->>'snapshot_id' = snapshot_id::text),
            CHECK (snapshot_json->>'schema_version' IS NOT NULL
                AND snapshot_json->>'schema_version' = schema_version),
            CHECK (snapshot_json->>'snapshot_hash' IS NOT NULL
                AND snapshot_json->>'snapshot_hash' = snapshot_hash),
            CHECK (snapshot_json->>'execution_as_of' IS NOT NULL),
            CHECK (snapshot_json->>'timezone' IS NOT NULL
                AND snapshot_json->>'timezone' = 'Asia/Seoul'),
            CHECK (snapshot_json#>>'{lineage,source_request_id}' IS NOT NULL
                AND snapshot_json#>>'{lineage,source_request_id}' = source_request_id::text),
            CHECK (snapshot_json#>>'{lineage,query_execution_id}' IS NOT NULL
                AND snapshot_json#>>'{lineage,query_execution_id}' = query_execution_id::text),
            CHECK (snapshot_json#>>'{lineage,artifact_id}' IS NOT NULL
                AND snapshot_json#>>'{lineage,artifact_id}' = artifact_id::text),
            CHECK (snapshot_json#>>'{release_receipt,product_release_id}' IS NOT NULL
                AND snapshot_json#>>'{release_receipt,product_release_id}' = product_release_id),
            CHECK (snapshot_json#>>'{release_receipt,permission_snapshot_id}' IS NOT NULL
                AND snapshot_json#>>'{release_receipt,permission_snapshot_id}' = permission_snapshot_id),
            CHECK (snapshot_json#>>'{release_receipt,semantic_release_id}' IS NOT NULL
                AND snapshot_json#>>'{release_receipt,semantic_release_id}' = semantic_release_id),
            CHECK (snapshot_json#>>'{release_receipt,context_release}' IS NOT NULL
                AND btrim(snapshot_json#>>'{release_receipt,context_release}') <> ''
                AND snapshot_json#>>'{release_receipt,context_release}' = semantic_release_id),
            CHECK (snapshot_json#>>'{release_receipt,policy_version}' IS NOT NULL
                AND btrim(snapshot_json#>>'{release_receipt,policy_version}') <> ''),
            CHECK (snapshot_json#>>'{release_receipt,catalog_checksum}' IS NOT NULL
                AND snapshot_json#>>'{release_receipt,catalog_checksum}' ~ '^[0-9a-f]{64}$'),
            CHECK (snapshot_json#>>'{release_receipt,canonical_checksum}' IS NOT NULL
                AND snapshot_json#>>'{release_receipt,canonical_checksum}' ~ '^[0-9a-f]{64}$'),
            CHECK (snapshot_json#>>'{release_receipt,runtime_projection_checksum}' IS NOT NULL
                AND snapshot_json#>>'{release_receipt,runtime_projection_checksum}' ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "CREATE TRIGGER approved_semantic_request_snapshots_immutable "
        "BEFORE UPDATE OR DELETE ON analysis_v1.approved_semantic_request_snapshots "
        "FOR EACH ROW EXECUTE FUNCTION analysis_v1.reject_immutable_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION analysis_v1.validate_approved_semantic_snapshot_lineage()
        RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM chat.analysis_requests r
                JOIN query.query_executions q
                  ON q.request_id = r.request_id
                 AND q.query_execution_id = NEW.query_execution_id
                 AND q.validation_status = 'ALLOWED'
                 AND q.execution_status = 'SUCCEEDED'
                JOIN artifact.analysis_artifacts a
                  ON a.request_id = r.request_id
                 AND a.query_execution_id = q.query_execution_id
                 AND a.artifact_id = NEW.artifact_id
                 AND a.status = 'APPROVED'
                WHERE r.request_id = NEW.source_request_id
                  AND r.status IN ('SUCCEEDED', 'PARTIAL')
                  AND r.user_id = NEW.owner_id
                  AND r.product_release_id = NEW.product_release_id
                  AND r.permission_snapshot_id = NEW.permission_snapshot_id
                  AND r.semantic_release_id = NEW.semantic_release_id
                  AND a.product_release_id = NEW.product_release_id
                  AND a.permission_snapshot_id = NEW.permission_snapshot_id
                  AND a.semantic_release_id = NEW.semantic_release_id
            ) THEN
                RAISE EXCEPTION 'Approved Semantic Request lineage is not terminal and coherent'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER approved_semantic_request_snapshots_lineage "
        "BEFORE INSERT ON analysis_v1.approved_semantic_request_snapshots "
        "FOR EACH ROW EXECUTE FUNCTION "
        "analysis_v1.validate_approved_semantic_snapshot_lineage()"
    )
    op.execute(
        "ALTER TABLE analysis_v1.analysis_definitions "
        "ADD COLUMN semantic_snapshot_id uuid NULL "
        "REFERENCES analysis_v1.approved_semantic_request_snapshots(snapshot_id) "
        "ON DELETE RESTRICT"
    )
    op.execute(
        "CREATE INDEX idx_analysis_definitions_semantic_snapshot "
        "ON analysis_v1.analysis_definitions(semantic_snapshot_id) "
        "WHERE semantic_snapshot_id IS NOT NULL"
    )
    role = _runtime_role()
    op.execute(
        f"GRANT SELECT, INSERT ON analysis_v1.approved_semantic_request_snapshots TO {role}"
    )


def downgrade() -> None:
    """Definition 참조와 독립 snapshot table 권한·객체를 역순으로 제거한다."""

    role = _runtime_role()
    op.execute(
        f"REVOKE SELECT, INSERT ON analysis_v1.approved_semantic_request_snapshots FROM {role}"
    )
    op.execute("DROP INDEX analysis_v1.idx_analysis_definitions_semantic_snapshot")
    op.execute(
        "ALTER TABLE analysis_v1.analysis_definitions DROP COLUMN semantic_snapshot_id"
    )
    op.execute("DROP TABLE analysis_v1.approved_semantic_request_snapshots")
    op.execute(
        "DROP FUNCTION analysis_v1.validate_approved_semantic_snapshot_lineage()"
    )
