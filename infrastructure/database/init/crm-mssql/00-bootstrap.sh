#!/usr/bin/env bash
set -euo pipefail
export SQLCMDPASSWORD="$CRM_SA_PASSWORD"
for attempt in {1..30}; do
  /opt/mssql-tools18/bin/sqlcmd -C -S crm-mssql -U sa -Q "SELECT 1" >/dev/null 2>&1 && break
  sleep 2
done
/opt/mssql-tools18/bin/sqlcmd -C -b -S crm-mssql -U sa -v CRM_DB_NAME="$CRM_DB_NAME" CRM_RO_USERNAME="$CRM_RO_USERNAME" CRM_RO_PASSWORD="$CRM_RO_PASSWORD" -i /init/10-schema.sql
