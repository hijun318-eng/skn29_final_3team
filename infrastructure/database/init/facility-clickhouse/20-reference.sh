#!/usr/bin/env sh
clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --query "INSERT INTO facility_events VALUES ('FAC-0001', 'Synthetic Pool')"
