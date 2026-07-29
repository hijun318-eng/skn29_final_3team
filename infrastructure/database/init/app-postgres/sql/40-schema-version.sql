BEGIN;
SET LOCAL ROLE :"migration_user";

CREATE TABLE IF NOT EXISTS app.schema_version (
    version text PRIMARY KEY,
    seed bigint NOT NULL,
    applied_at timestamptz NOT NULL
);

INSERT INTO app.schema_version (version, seed, applied_at)
VALUES ('1.0.0', 20260729, '2026-07-29 00:00:00+09')
ON CONFLICT (version) DO UPDATE
SET seed = EXCLUDED.seed,
    applied_at = EXCLUDED.applied_at;

COMMIT;
