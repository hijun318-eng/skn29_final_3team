#!/usr/bin/env bash
set -euo pipefail
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v migration="$APP_MIGRATION_USER" -v migration_password="$APP_MIGRATION_PASSWORD" -v app="$APP_DB_USER" -v app_password="$APP_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'migration', :'migration_password') WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'migration') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app', :'app_password') WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app') \gexec
SQL
