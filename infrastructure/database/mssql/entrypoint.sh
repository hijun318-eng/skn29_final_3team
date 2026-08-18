#!/usr/bin/env bash
# 책임: SQL Server가 ONLINE 상태임을 확인한 뒤 schema를 정확히 한 번 초기화한다.
# recovery timeout이나 DDL 오류가 나면 container를 준비 상태로 두지 않는다.
set -euo pipefail

/opt/mssql/bin/sqlservr &
server_pid=$!
# sqlcmd 공식 credential environment를 사용해 SA secret이 process argv와
# Docker health diagnostics에 남지 않게 한다.
export SQLCMDPASSWORD="${MSSQL_SA_PASSWORD}"

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
    -S localhost -U sa -C -b -o /dev/null \
    -Q "IF EXISTS (SELECT 1 FROM sys.databases WHERE state_desc <> 'ONLINE') THROW 51000, 'DATABASE_STARTUP_IN_PROGRESS', 1; SELECT 1;"; then
    break
  fi
  sleep 2
done

/opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -C -b -o /dev/null \
  -Q "IF EXISTS (SELECT 1 FROM sys.databases WHERE state_desc <> 'ONLINE') THROW 51000, 'DATABASE_STARTUP_TIMEOUT', 1; SELECT 1;"

# The image provisions schema only. Runtime data must arrive through the
# governed ingestion path; embedding a scenario seed here would make a clean
# deployment look production-ready without source evidence.
if [ ! -f /var/opt/mssql/.answervice_schema_initialized ]; then
  /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -b -i /bootstrap/00-ddl.sql
  touch /var/opt/mssql/.answervice_schema_initialized
fi

wait "${server_pid}"
