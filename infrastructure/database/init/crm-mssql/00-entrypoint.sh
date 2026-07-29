#!/usr/bin/env bash
set -Eeuo pipefail

case "$CRM_DB_NAME:$CRM_READONLY_USER" in
  *[!A-Za-z0-9_:]*)
    echo "CRM_DB_NAME and CRM_READONLY_USER must contain only letters, numbers, and underscores" >&2
    exit 1
    ;;
esac

if [[ ! "$CRM_READONLY_PASSWORD" =~ ^[A-Za-z0-9!_.+=-]+$ ]]; then
  echo "CRM_READONLY_PASSWORD contains an unsupported character" >&2
  exit 1
fi

if [[ -x /opt/mssql-tools18/bin/sqlcmd ]]; then
  SQLCMD=/opt/mssql-tools18/bin/sqlcmd
elif [[ -x /opt/mssql-tools/bin/sqlcmd ]]; then
  SQLCMD=/opt/mssql-tools/bin/sqlcmd
else
  echo "sqlcmd was not found in the SQL Server image" >&2
  exit 1
fi

/opt/mssql/bin/sqlservr &
sqlserver_pid=$!

shutdown_sqlserver() {
  kill -TERM "$sqlserver_pid" 2>/dev/null || true
  wait "$sqlserver_pid" 2>/dev/null || true
}
trap shutdown_sqlserver TERM INT

ready=0
for _ in $(seq 1 90); do
  if "$SQLCMD" -S 127.0.0.1 -U sa -P "$MSSQL_SA_PASSWORD" -C \
      -b -l 3 -Q "SET NOCOUNT ON; SELECT 1;" -o /dev/null; then
    ready=1
    break
  fi
  if ! kill -0 "$sqlserver_pid" 2>/dev/null; then
    wait "$sqlserver_pid"
    exit $?
  fi
  sleep 2
done

if [[ "$ready" -ne 1 ]]; then
  echo "SQL Server did not become ready before the initialization timeout" >&2
  shutdown_sqlserver
  exit 1
fi

for script in \
  /init/10-schema.sql \
  /init/20-reference-data.sql \
  /init/30-synthetic-data.sql \
  /init/40-schema-version.sql \
  /init/50-readonly-user.sql
do
  "$SQLCMD" -S 127.0.0.1 -U sa -P "$MSSQL_SA_PASSWORD" -C -b -l 30 \
    -v CRM_DB_NAME="$CRM_DB_NAME" \
       CRM_READONLY_USER="$CRM_READONLY_USER" \
       CRM_READONLY_PASSWORD="$CRM_READONLY_PASSWORD" \
    -i "$script"
done

wait "$sqlserver_pid"
