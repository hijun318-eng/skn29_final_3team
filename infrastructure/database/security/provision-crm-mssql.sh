#!/usr/bin/env sh
set -eu

/opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -b \
  -v QueryUser="$CRM_READONLY_USER" \
  -v QueryPassword="$CRM_READONLY_PASSWORD" \
  -i /security/provision-crm-mssql.sql
