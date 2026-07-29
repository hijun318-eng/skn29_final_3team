INSERT INTO banquet.schema_version (version, seed, applied_at)
VALUES ('1.0.0', 20260729, '2026-07-29 00:00:00+09')
ON CONFLICT (version) DO UPDATE
SET seed = EXCLUDED.seed,
    applied_at = EXCLUDED.applied_at;
