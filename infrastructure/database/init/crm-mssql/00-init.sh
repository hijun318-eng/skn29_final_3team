#!/usr/bin/env bash
set -Eeuo pipefail

: "${MSSQL_SA_PASSWORD:?MSSQL_SA_PASSWORD is required}"
: "${CRM_DATABASE:?CRM_DATABASE is required}"
: "${CRM_DATAHUB_PASSWORD:?CRM_DATAHUB_PASSWORD is required}"
: "${CRM_TRINO_PASSWORD:?CRM_TRINO_PASSWORD is required}"
: "${DATABASE_SCHEMA_VERSION:?DATABASE_SCHEMA_VERSION is required}"
: "${SYNTHETIC_DATA_SEED:?SYNTHETIC_DATA_SEED is required}"
: "${SCENARIO_VERSION:?SCENARIO_VERSION is required}"
: "${FIXTURE_VERSION:?FIXTURE_VERSION is required}"
: "${GENERATED_AT:?GENERATED_AT is required}"

if [[ ! "$CRM_DATABASE" =~ ^[A-Za-z][A-Za-z0-9_]{0,62}$ ]]; then
  echo "CRM_DATABASE must be a simple SQL identifier." >&2
  exit 64
fi

for password_name in CRM_DATAHUB_PASSWORD CRM_TRINO_PASSWORD; do
  password_value="${!password_name}"
  if [[ ! "$password_value" =~ ^[A-Za-z0-9_!@#%^+=.,:-]{12,128}$ ]]; then
    echo "$password_name contains unsupported characters or is shorter than 12 characters." >&2
    exit 64
  fi
done

sqlcmd=/opt/mssql-tools18/bin/sqlcmd
if [[ ! -x "$sqlcmd" ]]; then
  sqlcmd=/opt/mssql-tools/bin/sqlcmd
fi
if [[ ! -x "$sqlcmd" ]]; then
  echo "sqlcmd was not found in the SQL Server image." >&2
  exit 69
fi

for attempt in $(seq 1 90); do
  if "$sqlcmd" \
    -S crm-mssql \
    -U sa \
    -P "$MSSQL_SA_PASSWORD" \
    -C \
    -b \
    -Q "SELECT 1" \
    -o /dev/null; then
    break
  fi
  if [[ "$attempt" -eq 90 ]]; then
    echo "SQL Server did not become ready within 180 seconds." >&2
    exit 70
  fi
  sleep 2
done

sqlcmd_args=(
  -S crm-mssql
  -U sa
  -P "$MSSQL_SA_PASSWORD"
  -C
  -b
  -V 16
  -v
  "CRM_DATABASE=$CRM_DATABASE"
  "CRM_DATAHUB_PASSWORD=$CRM_DATAHUB_PASSWORD"
  "CRM_TRINO_PASSWORD=$CRM_TRINO_PASSWORD"
  "DATABASE_SCHEMA_VERSION=$DATABASE_SCHEMA_VERSION"
  "SYNTHETIC_DATA_SEED=$SYNTHETIC_DATA_SEED"
  "SCENARIO_VERSION=$SCENARIO_VERSION"
  "FIXTURE_VERSION=$FIXTURE_VERSION"
  "GENERATED_AT=$GENERATED_AT"
)

for sql_file in \
  /init/sql/10-schema.sql \
  /init/sql/20-reference-data.sql \
  /init/sql/30-synthetic-data.sql \
  /init/sql/90-accounts.sql \
  /init/sql/99-schema-ready.sql; do
  "$sqlcmd" "${sqlcmd_args[@]}" -i "$sql_file"
done

"$sqlcmd" "${sqlcmd_args[@]}" \
  -d "$CRM_DATABASE" \
  -Q "SET NOCOUNT ON;
      IF NOT EXISTS (
        SELECT 1
        FROM dbo.environment_manifest
        WHERE schema_version = N'$(printf '%s' "$DATABASE_SCHEMA_VERSION")'
      ) THROW 50001, 'SCHEMA_NOT_READY', 1;" \
  -o /dev/null

echo "SQL Server schema initialization completed."
