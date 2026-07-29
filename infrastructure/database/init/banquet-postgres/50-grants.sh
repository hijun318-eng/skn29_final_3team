#!/usr/bin/env bash
set -euo pipefail
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v ro="$RO_USER" <<'SQL'
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'ro') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'ro') \gexec
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA public TO %I', :'ro') \gexec
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'ro') \gexec
SQL
