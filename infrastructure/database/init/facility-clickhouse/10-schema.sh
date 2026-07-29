#!/usr/bin/env sh
set -eu
clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --multiquery <<'SQL'
CREATE TABLE IF NOT EXISTS schema_version (version String, applied_at DateTime64(3, 'Asia/Seoul')) ENGINE = MergeTree ORDER BY version;
CREATE TABLE IF NOT EXISTS seed_metadata (seed_name String, seed_value UInt32, data_classification String) ENGINE = MergeTree ORDER BY seed_name;
CREATE TABLE IF NOT EXISTS facility_events (event_id String, facility_name String, event_at DateTime64(3, 'Asia/Seoul')) ENGINE = MergeTree ORDER BY (facility_name, event_at);
INSERT INTO schema_version VALUES ('facility-clickhouse/v1', now64(3));
INSERT INTO seed_metadata VALUES ('synthetic-demo', 20260729, 'synthetic');
INSERT INTO facility_events VALUES ('FAC-0001', 'Synthetic Pool', toDateTime64('2026-07-29 09:00:00', 3, 'Asia/Seoul'));
SQL
