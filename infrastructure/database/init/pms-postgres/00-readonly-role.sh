#!/usr/bin/env bash
(
set -Eeuo pipefail

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v readonly_user="$PMS_READONLY_USER" \
  -v readonly_password="$PMS_READONLY_PASSWORD" <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE',
  :'readonly_user', :'readonly_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'readonly_user')
\gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'readonly_user', :'readonly_password')
\gexec
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'readonly_user')
\gexec
SELECT format('ALTER ROLE %I SET search_path = pms, pg_catalog', :'readonly_user')
\gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
)
