#!/usr/bin/env bash
set -euo pipefail
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v ro_user="$BANQUET_RO_USERNAME" <<'SQL'
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'ro_user') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'ro_user') \gexec
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA public TO %I', :'ro_user') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO %I', :'ro_user') \gexec
SQL
