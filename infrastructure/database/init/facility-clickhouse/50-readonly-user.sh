#!/usr/bin/env bash
(
set -Eeuo pipefail

[[ "$FACILITY_READONLY_USER" =~ ^[A-Za-z0-9_]+$ ]] || {
  echo "FACILITY_READONLY_USER must contain only letters, numbers, and underscores" >&2
  exit 1
}
[[ "$FACILITY_READONLY_PASSWORD" =~ ^[A-Za-z0-9!_.+=-]+$ ]] || {
  echo "FACILITY_READONLY_PASSWORD contains an unsupported character" >&2
  exit 1
}

client=(
  clickhouse-client
  --host 127.0.0.1
  --user "$CLICKHOUSE_USER"
  --password "$CLICKHOUSE_PASSWORD"
)

"${client[@]}" --multiquery <<SQL
CREATE USER IF NOT EXISTS ${FACILITY_READONLY_USER}
IDENTIFIED WITH sha256_password BY '${FACILITY_READONLY_PASSWORD}';
ALTER USER ${FACILITY_READONLY_USER}
IDENTIFIED WITH sha256_password BY '${FACILITY_READONLY_PASSWORD}'
SETTINGS readonly = 1;
GRANT SELECT ON facility.* TO ${FACILITY_READONLY_USER};
GRANT SELECT ON system.databases TO ${FACILITY_READONLY_USER};
GRANT SELECT ON system.tables TO ${FACILITY_READONLY_USER};
GRANT SELECT ON system.columns TO ${FACILITY_READONLY_USER};
SQL
)
