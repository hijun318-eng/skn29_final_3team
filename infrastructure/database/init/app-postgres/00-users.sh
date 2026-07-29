#!/usr/bin/env bash
set -euo pipefail
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v rw_user="$APP_RW_USERNAME" -v rw_password="$APP_RW_PASSWORD" -v migration_user="$APP_MIGRATION_USERNAME" -v migration_password="$APP_MIGRATION_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'rw_user', :'rw_password') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'rw_user') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'migration_user', :'migration_password') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migration_user') \gexec
SQL
