BEGIN;
SET LOCAL ROLE :"migration_user";

INSERT INTO app.ingestion_run
    (run_id, source_key, status, started_at, finished_at, row_count)
OVERRIDING SYSTEM VALUE
VALUES
    (1, 'pms', 'succeeded', '2026-07-01 02:00:00+09', '2026-07-01 02:04:00+09', 120),
    (2, 'banquet', 'succeeded', '2026-07-01 02:10:00+09', '2026-07-01 02:13:00+09', 36),
    (3, 'pos', 'succeeded', '2026-07-01 02:20:00+09', '2026-07-01 02:23:00+09', 480),
    (4, 'crm', 'succeeded', '2026-07-01 02:30:00+09', '2026-07-01 02:35:00+09', 250),
    (5, 'facility', 'succeeded', '2026-07-01 02:40:00+09', '2026-07-01 02:42:00+09', 75)
ON CONFLICT (run_id) DO UPDATE
SET source_key = EXCLUDED.source_key,
    status = EXCLUDED.status,
    started_at = EXCLUDED.started_at,
    finished_at = EXCLUDED.finished_at,
    row_count = EXCLUDED.row_count;

SELECT setval(
    pg_get_serial_sequence('app.ingestion_run', 'run_id'),
    (SELECT max(run_id) FROM app.ingestion_run),
    true
);

COMMIT;
