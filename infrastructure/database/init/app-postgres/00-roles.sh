#!/usr/bin/env bash
(
set -Eeuo pipefail

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v app_user="$APP_DB_USER" \
  -v app_password="$APP_DB_PASSWORD" \
  -v migration_user="$APP_MIGRATION_USER" \
  -v migration_password="$APP_MIGRATION_PASSWORD" <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE',
  :'app_user', :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

SELECT format('ALTER ROLE %I PASSWORD %L', :'app_user', :'app_password')
\gexec

SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE',
  :'migration_user', :'migration_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migration_user')
\gexec

SELECT format('ALTER ROLE %I PASSWORD %L', :'migration_user', :'migration_password')
\gexec

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION %I', :'migration_user')
\gexec
SELECT format('ALTER SCHEMA app OWNER TO %I', :'migration_user')
\gexec
SELECT format('ALTER ROLE %I SET search_path = app, public', :'app_user')
\gexec
SELECT format('ALTER ROLE %I SET search_path = app, public', :'migration_user')
\gexec
SQL
)
