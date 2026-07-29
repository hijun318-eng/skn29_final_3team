#!/usr/bin/env sh
set -eu

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=query_user="$SOURCE_READONLY_USER" \
  --set=query_password="$SOURCE_READONLY_PASSWORD" \
  --set=query_role="$SOURCE_READONLY_ROLE" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'query_user', :'query_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'query_user')
\gexec
ALTER ROLE :"query_user" PASSWORD :'query_password';
GRANT :"query_role" TO :"query_user";
ALTER ROLE :"query_user" SET default_transaction_read_only = on;
SQL
