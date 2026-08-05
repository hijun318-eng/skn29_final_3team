-- REPORT-v1.1.0-DRAFT additive migration proposal owned by R5.
-- R4 must translate this file into a new Alembic revision after 20260804_04.

ALTER TABLE report_v1.report_blocks ADD COLUMN block_type varchar(16);
ALTER TABLE report_v1.report_blocks ADD COLUMN x smallint;
ALTER TABLE report_v1.report_blocks ADD COLUMN y smallint;
ALTER TABLE report_v1.report_blocks ADD COLUMN w smallint;
ALTER TABLE report_v1.report_blocks ADD COLUMN h smallint;
ALTER TABLE report_v1.report_blocks ADD COLUMN content text NOT NULL DEFAULT '';

UPDATE report_v1.report_blocks
SET block_type = 'table', x = 0, y = 0, w = columns, h = 1;

ALTER TABLE report_v1.report_blocks ALTER COLUMN block_type SET NOT NULL;
ALTER TABLE report_v1.report_blocks ALTER COLUMN x SET NOT NULL;
ALTER TABLE report_v1.report_blocks ALTER COLUMN y SET NOT NULL;
ALTER TABLE report_v1.report_blocks ALTER COLUMN w SET NOT NULL;
ALTER TABLE report_v1.report_blocks ALTER COLUMN h SET NOT NULL;
ALTER TABLE report_v1.report_blocks ALTER COLUMN artifact_id DROP NOT NULL;

ALTER TABLE report_v1.report_blocks ADD CONSTRAINT report_block_type_check
    CHECK (block_type IN ('table', 'chart', 'text'));
ALTER TABLE report_v1.report_blocks ADD CONSTRAINT report_block_layout_check
    CHECK (columns = w AND x >= 0 AND y >= 0 AND w BETWEEN 1 AND 12 AND h > 0 AND x + w <= 12);
ALTER TABLE report_v1.report_blocks ADD CONSTRAINT report_block_artifact_check
    CHECK (
        (block_type IN ('table', 'chart') AND artifact_id IS NOT NULL)
        OR (block_type = 'text' AND btrim(content) <> '')
    );

CREATE TABLE report_v1.report_manual_run_commands (
    command_id uuid PRIMARY KEY,
    definition_id uuid NOT NULL,
    definition_version integer NOT NULL,
    as_of timestamptz NOT NULL,
    idempotency_key text NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'queued' CHECK (status = 'queued'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (definition_id, definition_version, idempotency_key),
    FOREIGN KEY (definition_id, definition_version)
        REFERENCES report_v1.report_definition_versions(definition_id, version)
);

CREATE TRIGGER report_manual_command_requires_approved_definition
BEFORE INSERT ON report_v1.report_manual_run_commands
FOR EACH ROW EXECUTE FUNCTION report_v1.require_approved_definition();

-- The command table deliberately has no client-supplied run_id, policy_version,
-- context_hash, watermark, status transition or block result columns.
