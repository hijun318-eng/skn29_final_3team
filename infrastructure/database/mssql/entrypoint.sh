#!/usr/bin/env bash
set -euo pipefail

/opt/mssql/bin/sqlservr &
server_pid=$!

for _ in $(seq 1 180); do
  if grep -q "Recovery is complete" /var/opt/mssql/log/errorlog 2>/dev/null; then
    break
  fi
  sleep 2
done

if ! grep -q "Recovery is complete" /var/opt/mssql/log/errorlog 2>/dev/null; then
  echo "SQL Server recovery did not complete within 360 seconds." >&2
  exit 1
fi

for _ in $(seq 1 180); do
  if /opt/mssql-tools18/bin/sqlcmd \
    -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" -C -b -o /dev/null \
    -Q "IF EXISTS (SELECT 1 FROM sys.databases WHERE state_desc <> 'ONLINE') THROW 51000, 'DATABASE_STARTUP_IN_PROGRESS', 1; SELECT 1;"; then
    break
  fi
  sleep 2
done

/opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" -C -b -o /dev/null \
  -Q "IF EXISTS (SELECT 1 FROM sys.databases WHERE state_desc <> 'ONLINE') THROW 51000, 'DATABASE_STARTUP_TIMEOUT', 1; SELECT 1;"

if [ ! -f /var/opt/mssql/.hotel_synthetic_initialized ]; then
  /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" -C -b -i /bootstrap/00-ddl.sql
  /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" -C -b -i /bootstrap/10-synthetic.sql
  touch /var/opt/mssql/.hotel_synthetic_initialized
fi

wait "${server_pid}"
