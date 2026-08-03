-- REPORT-v1.0.0 migration proposal owned by R5.
-- R4 must assign the Alembic revision/down_revision and register this in the single chain.
CREATE TABLE report_definitions (
    definition_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE report_definition_versions (
    definition_id uuid NOT NULL REFERENCES report_definitions(definition_id),
    version integer NOT NULL CHECK (version >= 1),
    status varchar(16) NOT NULL CHECK (status IN ('draft', 'approved')),
    title text NOT NULL,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (definition_id, version),
    CHECK ((status = 'approved' AND approved_at IS NOT NULL) OR (status = 'draft' AND approved_at IS NULL))
);

CREATE TABLE report_blocks (
    definition_id uuid NOT NULL,
    definition_version integer NOT NULL,
    block_id uuid NOT NULL,
    title text NOT NULL,
    artifact_id uuid NOT NULL,
    query_id text,
    columns smallint NOT NULL CHECK (columns BETWEEN 1 AND 12),
    PRIMARY KEY (definition_id, definition_version, block_id),
    FOREIGN KEY (definition_id, definition_version)
        REFERENCES report_definition_versions(definition_id, version)
);

CREATE TABLE report_runs (
    run_id uuid PRIMARY KEY,
    definition_id uuid NOT NULL,
    definition_version integer NOT NULL,
    as_of timestamptz NOT NULL,
    policy_version text NOT NULL,
    context_hash text NOT NULL,
    watermark jsonb NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('queued', 'running', 'success', 'partial', 'failed', 'cancelled')),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (definition_id, definition_version)
        REFERENCES report_definition_versions(definition_id, version)
);

CREATE TABLE report_block_runs (
    run_id uuid NOT NULL REFERENCES report_runs(run_id),
    block_id uuid NOT NULL,
    artifact_id uuid NOT NULL,
    query_id text NOT NULL,
    snapshot_checksum text NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('success', 'partial', 'failed', 'cancelled')),
    PRIMARY KEY (run_id, block_id)
);

-- Immutability must also be enforced in the R4 repository: approved versions are insert-only,
-- and report_runs always retain the exact definition_version used at execution time.