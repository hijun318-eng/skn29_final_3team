BEGIN;
SET LOCAL ROLE :"migration_user";

CREATE TABLE IF NOT EXISTS app.integration_source (
    source_key text PRIMARY KEY,
    display_name text NOT NULL,
    platform_instance text,
    trino_catalog text,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.ingestion_run (
    run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_key text NOT NULL REFERENCES app.integration_source(source_key),
    status text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    row_count bigint NOT NULL DEFAULT 0 CHECK (row_count >= 0)
);

CREATE TABLE IF NOT EXISTS app.health_probe (
    probe_key text PRIMARY KEY,
    note text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
