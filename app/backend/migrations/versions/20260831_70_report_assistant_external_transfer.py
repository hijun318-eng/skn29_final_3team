"""Report Assistant 외부 전송 동의와 호출별 불변 receipt를 추가한다."""

import os
import re

from alembic import op


revision = "20260831_70"
down_revision = "20260831_69"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    """환경의 제한된 runtime role만 SQL identifier로 허용한다."""

    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """서버 생성 disclosure·명시 consent·호출별 hash receipt를 append-only로 만든다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            ADD COLUMN model_execution_id uuid,
            ADD COLUMN model_execution_node varchar(64),
            ADD COLUMN model_execution_message_revision bigint,
            ADD COLUMN model_execution_expires_at timestamptz,
            ADD CONSTRAINT report_assistant_model_execution_check CHECK (
                (
                    model_execution_id IS NULL
                    AND model_execution_node IS NULL
                    AND model_execution_message_revision IS NULL
                    AND model_execution_expires_at IS NULL
                )
                OR (
                    model_execution_id IS NOT NULL
                    AND model_execution_node IN (
                        'report_assistant', 'report_assistant_turn',
                        'report_assistant_review'
                    )
                    AND model_execution_message_revision >= 0
                    AND model_execution_expires_at IS NOT NULL
                )
            )
        """
    )
    op.execute(
        """
        CREATE FUNCTION report_v1.guard_live_assistant_model_execution()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.model_execution_id IS NOT NULL
               AND OLD.model_execution_expires_at > now()
               AND NEW.model_execution_id IS NOT NULL THEN
                RAISE EXCEPTION 'Report Assistant model execution is already claimed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER report_assistant_model_execution_guard
        BEFORE UPDATE ON report_v1.report_assistant_requests
        FOR EACH ROW EXECUTE FUNCTION report_v1.guard_live_assistant_model_execution();
        """
    )
    op.execute(
        """
        CREATE TABLE report_v1.report_assistant_transfer_disclosures (
            disclosure_id uuid PRIMARY KEY,
            assistant_request_id uuid NOT NULL
                REFERENCES report_v1.report_assistant_requests(assistant_request_id),
            owner_id uuid NOT NULL,
            policy_version varchar(96) NOT NULL CHECK (btrim(policy_version) <> ''),
            node varchar(64) NOT NULL CHECK (btrim(node) <> ''),
            route_json jsonb NOT NULL CHECK (jsonb_typeof(route_json) = 'object'),
            route_fingerprint char(64) NOT NULL
                CHECK (route_fingerprint ~ '^[0-9a-f]{64}$'),
            binding_hash char(64) NOT NULL CHECK (binding_hash ~ '^[0-9a-f]{64}$'),
            data_scopes_json jsonb NOT NULL
                CHECK (jsonb_typeof(data_scopes_json) = 'array'),
            scope_hash char(64) NOT NULL CHECK (scope_hash ~ '^[0-9a-f]{64}$'),
            excluded_data_json jsonb NOT NULL
                CHECK (jsonb_typeof(excluded_data_json) = 'array'),
            content_warning varchar(500) NOT NULL CHECK (btrim(content_warning) <> ''),
            disclosure_hash char(64) NOT NULL UNIQUE
                CHECK (disclosure_hash ~ '^[0-9a-f]{64}$'),
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            CHECK (expires_at > created_at)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX report_assistant_transfer_disclosure_lookup
        ON report_v1.report_assistant_transfer_disclosures
            (assistant_request_id, owner_id, binding_hash, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE report_v1.report_assistant_external_consents (
            consent_id uuid PRIMARY KEY,
            disclosure_id uuid NOT NULL UNIQUE
                REFERENCES report_v1.report_assistant_transfer_disclosures(disclosure_id),
            assistant_request_id uuid NOT NULL
                REFERENCES report_v1.report_assistant_requests(assistant_request_id),
            owner_id uuid NOT NULL,
            policy_version varchar(96) NOT NULL CHECK (btrim(policy_version) <> ''),
            disclosure_hash char(64) NOT NULL
                CHECK (disclosure_hash ~ '^[0-9a-f]{64}$'),
            route_fingerprint char(64) NOT NULL
                CHECK (route_fingerprint ~ '^[0-9a-f]{64}$'),
            binding_hash char(64) NOT NULL CHECK (binding_hash ~ '^[0-9a-f]{64}$'),
            scope_hash char(64) NOT NULL CHECK (scope_hash ~ '^[0-9a-f]{64}$'),
            accepted boolean NOT NULL CHECK (accepted),
            consented_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX report_assistant_external_consent_lookup
        ON report_v1.report_assistant_external_consents
            (assistant_request_id, owner_id, binding_hash, consented_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE report_v1.report_assistant_transfer_receipts (
            transfer_receipt_id uuid PRIMARY KEY,
            assistant_request_id uuid NOT NULL
                REFERENCES report_v1.report_assistant_requests(assistant_request_id),
            owner_id uuid NOT NULL,
            disclosure_id uuid
                REFERENCES report_v1.report_assistant_transfer_disclosures(disclosure_id),
            consent_id uuid
                REFERENCES report_v1.report_assistant_external_consents(consent_id),
            policy_version varchar(96) NOT NULL CHECK (btrim(policy_version) <> ''),
            node varchar(64) NOT NULL CHECK (btrim(node) <> ''),
            attempt smallint NOT NULL CHECK (attempt BETWEEN 1 AND 4),
            data_boundary varchar(16) NOT NULL
                CHECK (data_boundary IN ('external', 'internal')),
            manifest_version varchar(96) NOT NULL CHECK (btrim(manifest_version) <> ''),
            route_id varchar(64) NOT NULL CHECK (btrim(route_id) <> ''),
            provider varchar(64) NOT NULL CHECK (btrim(provider) <> ''),
            model varchar(255) NOT NULL CHECK (btrim(model) <> ''),
            model_snapshot varchar(255) NOT NULL CHECK (btrim(model_snapshot) <> ''),
            endpoint varchar(2048) NOT NULL CHECK (btrim(endpoint) <> ''),
            route_fingerprint char(64) NOT NULL
                CHECK (route_fingerprint ~ '^[0-9a-f]{64}$'),
            binding_hash char(64) NOT NULL CHECK (binding_hash ~ '^[0-9a-f]{64}$'),
            data_scopes_json jsonb NOT NULL
                CHECK (jsonb_typeof(data_scopes_json) = 'array'),
            scope_hash char(64) NOT NULL CHECK (scope_hash ~ '^[0-9a-f]{64}$'),
            payload_hash char(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            model_execution_id uuid NOT NULL,
            authorized_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT report_assistant_transfer_receipt_attempt_unique
                UNIQUE (assistant_request_id, model_execution_id, attempt),
            CHECK (
                (data_boundary = 'external' AND disclosure_id IS NOT NULL AND consent_id IS NOT NULL)
                OR (data_boundary = 'internal' AND disclosure_id IS NULL AND consent_id IS NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX report_assistant_transfer_receipt_lookup
        ON report_v1.report_assistant_transfer_receipts
            (assistant_request_id, owner_id, authorized_at DESC)
        """
    )
    op.execute(
        """
        COMMENT ON TABLE report_v1.report_assistant_transfer_receipts IS
        'External receipts are DB-bound to immutable consent/disclosure. Internal '
        'receipt manifest and session binding are revalidated by the application '
        'immediately before insert because the database does not own the runtime manifest.'
        """
    )
    op.execute(
        """
        CREATE FUNCTION report_v1.require_assistant_transfer_owner()
        RETURNS trigger AS $$
        BEGIN
            PERFORM 1
            FROM report_v1.report_assistant_requests request
            WHERE request.assistant_request_id = NEW.assistant_request_id
              AND request.owner_id = NEW.owner_id
            FOR KEY SHARE OF request;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Report Assistant transfer owner does not match';
            END IF;

            IF TG_TABLE_NAME = 'report_assistant_external_consents' THEN
                PERFORM 1
                FROM report_v1.report_assistant_transfer_disclosures disclosure
                WHERE disclosure.disclosure_id = NEW.disclosure_id
                  AND disclosure.assistant_request_id = NEW.assistant_request_id
                  AND disclosure.owner_id = NEW.owner_id
                  AND disclosure.policy_version = NEW.policy_version
                  AND disclosure.disclosure_hash = NEW.disclosure_hash
                  AND disclosure.route_fingerprint = NEW.route_fingerprint
                  AND disclosure.binding_hash = NEW.binding_hash
                  AND disclosure.scope_hash = NEW.scope_hash
                  AND disclosure.expires_at > now();
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Report Assistant disclosure is not consentable';
                END IF;
            ELSIF TG_TABLE_NAME = 'report_assistant_transfer_receipts' THEN
                PERFORM 1
                FROM report_v1.report_assistant_requests request
                WHERE request.assistant_request_id = NEW.assistant_request_id
                  AND request.owner_id = NEW.owner_id
                  AND request.status = 'running'
                  AND request.phase IN (
                      'ready', 'waiting_patch_approval', 'waiting_artifact'
                  )
                  AND request.model_execution_id = NEW.model_execution_id
                  AND request.model_execution_node = NEW.node
                  AND request.model_execution_message_revision = request.message_revision
                  AND request.model_execution_expires_at > now()
                  AND EXISTS (
                      SELECT 1
                      FROM report_v1.report_definition_versions version
                      JOIN report_v1.report_definitions definition
                        ON definition.definition_id = version.definition_id
                      WHERE version.definition_id = request.session_definition_id
                        AND version.version = request.session_definition_version
                        AND version.revision = request.base_revision
                        AND version.status = 'draft'
                        AND definition.owner_id = request.owner_id
                  );
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Report Assistant model execution is not current';
                END IF;

                IF NEW.data_boundary = 'external' THEN
                PERFORM 1
                FROM report_v1.report_assistant_external_consents consent
                JOIN report_v1.report_assistant_transfer_disclosures disclosure
                  ON disclosure.disclosure_id = consent.disclosure_id
                WHERE consent.consent_id = NEW.consent_id
                  AND disclosure.disclosure_id = NEW.disclosure_id
                  AND consent.assistant_request_id = NEW.assistant_request_id
                  AND consent.owner_id = NEW.owner_id
                  AND consent.policy_version = NEW.policy_version
                  AND consent.route_fingerprint = NEW.route_fingerprint
                  AND consent.binding_hash = NEW.binding_hash
                  AND consent.scope_hash = NEW.scope_hash
                  AND consent.accepted
                  AND NEW.node = disclosure.node
                  AND NEW.data_scopes_json = disclosure.data_scopes_json
                  AND NEW.data_boundary = 'external'
                  AND NEW.manifest_version = disclosure.route_json->>'manifest_version'
                  AND EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(
                          disclosure.route_json->'provider_routes'
                      ) AS provider_route
                      WHERE provider_route->>'node' = NEW.node
                        AND provider_route->>'route_id' = NEW.route_id
                        AND provider_route->>'provider' = NEW.provider
                        AND provider_route->>'model' = NEW.model
                        AND provider_route->>'data_boundary' = NEW.data_boundary
                        AND NEW.endpoint LIKE
                            (provider_route->>'destination_origin') || '/%'
                  );
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Report Assistant external transfer is not consented';
                END IF;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "report_assistant_transfer_disclosures",
        "report_assistant_external_consents",
        "report_assistant_transfer_receipts",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_owner_guard "
            f"BEFORE INSERT ON report_v1.{table} "
            "FOR EACH ROW EXECUTE FUNCTION report_v1.require_assistant_transfer_owner()"
        )
    op.execute(
        """
        CREATE FUNCTION report_v1.reject_assistant_transfer_receipt_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Report Assistant transfer receipts are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "report_assistant_transfer_disclosures",
        "report_assistant_external_consents",
        "report_assistant_transfer_receipts",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable "
            f"BEFORE UPDATE OR DELETE ON report_v1.{table} "
            "FOR EACH ROW EXECUTE FUNCTION report_v1.reject_assistant_transfer_receipt_mutation()"
        )

    role = _runtime_role()
    op.execute(
        f"GRANT SELECT, INSERT ON report_v1.report_assistant_transfer_disclosures TO {role}"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON report_v1.report_assistant_external_consents TO {role}"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON report_v1.report_assistant_transfer_receipts TO {role}"
    )


def downgrade() -> None:
    """불변 동의·전송 증거가 한 건이라도 있으면 정보 손실 downgrade를 거부한다."""

    op.execute(
        """
        LOCK TABLE report_v1.report_assistant_requests,
                   report_v1.report_assistant_transfer_disclosures,
                   report_v1.report_assistant_external_consents,
                   report_v1.report_assistant_transfer_receipts
        IN ACCESS EXCLUSIVE MODE
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM report_v1.report_assistant_requests
                WHERE model_execution_id IS NOT NULL
            )
               OR EXISTS (SELECT 1 FROM report_v1.report_assistant_transfer_disclosures)
               OR EXISTS (SELECT 1 FROM report_v1.report_assistant_external_consents)
               OR EXISTS (SELECT 1 FROM report_v1.report_assistant_transfer_receipts) THEN
                RAISE EXCEPTION 'Report Assistant external transfer receipts must be preserved';
            END IF;
        END;
        $$
        """
    )
    role = _runtime_role()
    op.execute(
        f"REVOKE SELECT, INSERT ON report_v1.report_assistant_transfer_receipts FROM {role}"
    )
    op.execute(
        f"REVOKE SELECT, INSERT ON report_v1.report_assistant_external_consents FROM {role}"
    )
    op.execute(
        f"REVOKE SELECT, INSERT ON report_v1.report_assistant_transfer_disclosures FROM {role}"
    )
    for table in (
        "report_assistant_transfer_receipts",
        "report_assistant_external_consents",
        "report_assistant_transfer_disclosures",
    ):
        op.execute(f"DROP TRIGGER {table}_immutable ON report_v1.{table}")
        op.execute(f"DROP TRIGGER {table}_owner_guard ON report_v1.{table}")
    op.execute("DROP FUNCTION report_v1.reject_assistant_transfer_receipt_mutation()")
    op.execute("DROP FUNCTION report_v1.require_assistant_transfer_owner()")
    op.execute("DROP TABLE report_v1.report_assistant_transfer_receipts")
    op.execute("DROP TABLE report_v1.report_assistant_external_consents")
    op.execute("DROP TABLE report_v1.report_assistant_transfer_disclosures")
    op.execute(
        """
        DROP TRIGGER report_assistant_model_execution_guard
            ON report_v1.report_assistant_requests;
        DROP FUNCTION report_v1.guard_live_assistant_model_execution();
        ALTER TABLE report_v1.report_assistant_requests
            DROP CONSTRAINT report_assistant_model_execution_check,
            DROP COLUMN model_execution_expires_at,
            DROP COLUMN model_execution_message_revision,
            DROP COLUMN model_execution_node,
            DROP COLUMN model_execution_id;
        """
    )
