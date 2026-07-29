#!/usr/bin/env sh
clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "INSERT INTO seed_metadata VALUES (20260729, 'synthetic')"
