"""단일한 승인 Artifact receipt로 입증되는 legacy Report draft를 backfill한다."""

from alembic import op


revision = "20260901_71"
down_revision = "20260831_70"
branch_labels = None
depends_on = None


_MIGRATION_EVIDENCE = "migration-20260901-71"


def _create_immutable_trigger() -> None:
    op.execute(
        "CREATE TRIGGER report_definition_release_receipt_immutable "
        "BEFORE UPDATE ON report_v1.report_definition_versions "
        "FOR EACH ROW EXECUTE FUNCTION report_v1.reject_release_receipt_mutation()"
    )


def _create_binding_immutable_trigger() -> None:
    op.execute(
        "CREATE TRIGGER product_release_bindings_immutable "
        "BEFORE UPDATE OR DELETE ON governance.product_release_bindings "
        "FOR EACH ROW EXECUTE FUNCTION "
        "governance.reject_product_release_evidence_mutation()"
    )


def upgrade() -> None:
    """owner와 receipt가 하나로 일치하는 active draft만 기존 Artifact receipt에 결속한다."""

    # 후보를 계산한 뒤 다른 세션이 보고서나 Artifact lifecycle을 바꾸는 시간차를
    # 없앤다. 배포 migration이므로 짧은 전체 잠금 뒤 한 transaction에서 이관한다.
    op.execute(
        "LOCK TABLE report_v1.report_definitions, "
        "report_v1.report_definition_versions, report_v1.report_blocks, "
        "artifact.user_artifact_lifecycle IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        """
        CREATE TEMP TABLE report_receipt_backfill_candidates (
            definition_id uuid NOT NULL,
            version integer NOT NULL,
            product_release_id varchar(160) NOT NULL,
            permission_snapshot_id varchar(160) NOT NULL,
            semantic_release_id varchar(256) NOT NULL,
            PRIMARY KEY (definition_id, version)
        ) ON COMMIT DROP
        """
    )
    op.execute(
        """
        INSERT INTO report_receipt_backfill_candidates (
            definition_id, version, product_release_id,
            permission_snapshot_id, semantic_release_id
        )
        WITH uniform_receipts AS (
            SELECT
                version.definition_id,
                version.version,
                min(artifact.product_release_id) AS product_release_id,
                min(artifact.permission_snapshot_id) AS permission_snapshot_id,
                min(artifact.semantic_release_id) AS semantic_release_id
            FROM report_v1.report_definition_versions version
            JOIN report_v1.report_definitions definition
              ON definition.definition_id = version.definition_id
            JOIN report_v1.report_blocks block
              ON block.definition_id = version.definition_id
             AND block.definition_version = version.version
             AND block.artifact_id IS NOT NULL
            JOIN artifact.analysis_artifacts artifact
              ON artifact.artifact_id = block.artifact_id
            JOIN chat.analysis_requests request
              ON request.request_id = artifact.request_id
            WHERE version.status = 'draft'
              AND definition.archived_at IS NULL
              AND version.product_release_id IS NULL
              AND version.permission_snapshot_id IS NULL
              AND version.semantic_release_id IS NULL
            GROUP BY version.definition_id, version.version, definition.owner_id
            HAVING bool_and(
                artifact.status = 'APPROVED'
                AND request.status IN ('SUCCEEDED', 'PARTIAL')
                AND request.user_id = definition.owner_id
                AND artifact.product_release_id IS NOT NULL
                AND artifact.permission_snapshot_id IS NOT NULL
                AND artifact.semantic_release_id IS NOT NULL
                AND EXISTS (
                    SELECT 1
                    FROM governance.product_release_manifests manifest
                    WHERE manifest.product_release_id = artifact.product_release_id
                      AND manifest.release_vector_json->>'semantic_release_id'
                          = artifact.semantic_release_id
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM artifact.user_artifact_lifecycle lifecycle
                    WHERE lifecycle.owner_id = definition.owner_id
                      AND lifecycle.artifact_id = artifact.artifact_id
                      AND lifecycle.archived_at IS NOT NULL
                )
            )
              AND count(DISTINCT (
                  artifact.product_release_id,
                  artifact.permission_snapshot_id,
                  artifact.semantic_release_id
              )) = 1
        )
        SELECT
            receipt.definition_id,
            receipt.version,
            receipt.product_release_id,
            receipt.permission_snapshot_id,
            receipt.semantic_release_id
        FROM uniform_receipts receipt
        WHERE NOT EXISTS (
            SELECT 1
            FROM governance.product_release_bindings binding
            WHERE binding.object_kind = 'REPORT'
              AND binding.object_id = (
                  'definition:' || receipt.definition_id::text
                  || ':' || 'v' || receipt.version::text
              )
              AND (
                  binding.product_release_id,
                  binding.permission_snapshot_id,
                  binding.semantic_release_id
              ) IS DISTINCT FROM (
                  receipt.product_release_id,
                  receipt.permission_snapshot_id,
                  receipt.semantic_release_id
              )
        )
        """
    )
    op.execute(
        "DROP TRIGGER report_definition_release_receipt_immutable "
        "ON report_v1.report_definition_versions"
    )
    op.execute(
        """
        UPDATE report_v1.report_definition_versions version
        SET product_release_id = candidate.product_release_id,
            permission_snapshot_id = candidate.permission_snapshot_id,
            semantic_release_id = candidate.semantic_release_id
        FROM report_receipt_backfill_candidates candidate
        WHERE version.definition_id = candidate.definition_id
          AND version.version = candidate.version
          AND version.status = 'draft'
          AND version.product_release_id IS NULL
          AND version.permission_snapshot_id IS NULL
          AND version.semantic_release_id IS NULL
        """
    )
    _create_immutable_trigger()
    op.execute(
        f"""
        INSERT INTO governance.product_release_bindings (
            object_kind, object_id, product_release_id,
            permission_snapshot_id, semantic_release_id,
            capability_release_vector_json, evidence_refs_json
        )
        SELECT
            'REPORT',
            'definition:' || candidate.definition_id::text
                || ':' || 'v' || candidate.version::text,
            candidate.product_release_id,
            candidate.permission_snapshot_id,
            candidate.semantic_release_id,
            '{{"report.lifecycle":"1.0.0"}}'::jsonb,
            '["{_MIGRATION_EVIDENCE}"]'::jsonb
        FROM report_receipt_backfill_candidates candidate
        ON CONFLICT (object_kind, object_id) DO NOTHING
        """
    )


def downgrade() -> None:
    """backfill 이후 사용되지 않은 draft만 legacy nullable receipt로 되돌린다."""

    # 사용 여부를 검사한 뒤 UPDATE/DELETE할 때까지 다른 세션이 version이나 binding을
    # 바꾸지 못하게 먼저 잠근다. 증적 binding은 기존 불변 trigger를 명시적으로 복구한다.
    op.execute(
        "LOCK TABLE report_v1.report_definition_versions, "
        "governance.product_release_bindings IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM governance.product_release_bindings binding
                JOIN report_v1.report_definition_versions version
                  ON binding.object_id = (
                      'definition:' || version.definition_id::text
                      || ':' || 'v' || version.version::text
                  )
                WHERE binding.object_kind = 'REPORT'
                  AND binding.evidence_refs_json = '["{_MIGRATION_EVIDENCE}"]'::jsonb
                  AND (version.status <> 'draft' OR version.revision <> 1)
            ) THEN
                RAISE EXCEPTION 'Backfilled Report receipt is already in use';
            END IF;
        END $$
        """
    )
    op.execute(
        "DROP TRIGGER report_definition_release_receipt_immutable "
        "ON report_v1.report_definition_versions"
    )
    op.execute(
        "DROP TRIGGER product_release_bindings_immutable "
        "ON governance.product_release_bindings"
    )
    op.execute(
        f"""
        UPDATE report_v1.report_definition_versions version
        SET product_release_id = NULL,
            permission_snapshot_id = NULL,
            semantic_release_id = NULL
        FROM governance.product_release_bindings binding
        WHERE binding.object_kind = 'REPORT'
          AND binding.evidence_refs_json = '["{_MIGRATION_EVIDENCE}"]'::jsonb
          AND binding.object_id = (
              'definition:' || version.definition_id::text
              || ':' || 'v' || version.version::text
          )
          AND (
              version.product_release_id,
              version.permission_snapshot_id,
              version.semantic_release_id
          ) = (
              binding.product_release_id,
              binding.permission_snapshot_id,
              binding.semantic_release_id
          )
        """
    )
    op.execute(
        f"""
        DELETE FROM governance.product_release_bindings
        WHERE object_kind = 'REPORT'
          AND evidence_refs_json = '["{_MIGRATION_EVIDENCE}"]'::jsonb
        """
    )
    _create_immutable_trigger()
    _create_binding_immutable_trigger()
