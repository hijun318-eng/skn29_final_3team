#!/usr/bin/env sh
set -eu
clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --multiquery <<'SQL'
CREATE TABLE schema_version (version String) ENGINE = MergeTree ORDER BY version;
CREATE TABLE seed_metadata (seed UInt32, classification String) ENGINE = MergeTree ORDER BY seed;
CREATE TABLE facility_events (event_id String, facility_name String) ENGINE = MergeTree ORDER BY event_id;
SQL
