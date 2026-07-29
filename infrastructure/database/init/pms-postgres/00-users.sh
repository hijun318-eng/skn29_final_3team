#!/usr/bin/env bash
set -euo pipefail
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v ro_user="$PMS_RO_USERNAME" -v ro_password="$PMS_RO_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'ro_user', :'ro_password') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'ro_user') \gexec
SQL
