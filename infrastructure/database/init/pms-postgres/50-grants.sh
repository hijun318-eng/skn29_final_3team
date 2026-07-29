#!/usr/bin/env bash
(
set -Eeuo pipefail

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v readonly_user="$PMS_READONLY_USER" \
  -v admin_user="$POSTGRES_USER" <<'SQL'
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'readonly_user')
\gexec
SELECT format('GRANT USAGE ON SCHEMA pms TO %I', :'readonly_user')
\gexec
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA pms TO %I', :'readonly_user')
\gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA pms GRANT SELECT ON TABLES TO %I',
  :'admin_user', :'readonly_user'
)
\gexec
SQL
)
