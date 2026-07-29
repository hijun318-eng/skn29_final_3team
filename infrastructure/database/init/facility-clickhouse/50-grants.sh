#!/usr/bin/env sh
set -eu
clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery <<SQL
CREATE USER IF NOT EXISTS $RO_USER IDENTIFIED WITH sha256_password BY '$RO_PASSWORD';
GRANT SELECT ON $CLICKHOUSE_DB.* TO $RO_USER;
ALTER USER $RO_USER SETTINGS readonly = 1;
SQL
