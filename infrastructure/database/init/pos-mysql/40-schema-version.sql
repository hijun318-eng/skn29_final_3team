INSERT INTO schema_version (version, seed, applied_at)
VALUES ('1.0.0', 20260729, '2026-07-29 00:00:00')
ON DUPLICATE KEY UPDATE
    seed = VALUES(seed),
    applied_at = VALUES(applied_at);
