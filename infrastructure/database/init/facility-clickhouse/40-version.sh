#!/usr/bin/env sh
clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "INSERT INTO schema_version VALUES ('1.0.0')"
