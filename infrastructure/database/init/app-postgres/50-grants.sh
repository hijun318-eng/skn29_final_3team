#!/usr/bin/env bash
(
set -Eeuo pipefail

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v app_user="$APP_DB_USER" \
  -v migration_user="$APP_MIGRATION_USER" <<'SQL'
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'app_user')
\gexec
SELECT format('GRANT USAGE ON SCHEMA app TO %I', :'app_user')
\gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO %I', :'app_user')
\gexec
SELECT format('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA app TO %I', :'app_user')
\gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
  :'migration_user', :'app_user'
)
\gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA app GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I',
  :'migration_user', :'app_user'
)
\gexec
SQL
)
