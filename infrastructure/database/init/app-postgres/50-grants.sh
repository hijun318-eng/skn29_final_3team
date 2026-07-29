#!/usr/bin/env bash
set -euo pipefail
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v migration="$APP_MIGRATION_USER" -v app="$APP_DB_USER" <<'SQL'
SELECT format('GRANT USAGE, CREATE ON SCHEMA app TO %I', :'migration') \gexec
SELECT format('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA app TO %I', :'migration') \gexec
SELECT format('GRANT USAGE ON SCHEMA app TO %I', :'app') \gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO %I', :'app') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', :'app') \gexec
SQL
