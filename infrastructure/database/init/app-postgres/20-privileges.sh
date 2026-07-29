#!/usr/bin/env bash
set -euo pipefail
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v rw_user="$APP_RW_USERNAME" -v migration_user="$APP_MIGRATION_USERNAME" <<'SQL'
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'rw_user') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'migration_user') \gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', :'rw_user') \gexec
SELECT format('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO %I', :'migration_user') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', :'rw_user') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO %I', :'migration_user') \gexec
SQL
