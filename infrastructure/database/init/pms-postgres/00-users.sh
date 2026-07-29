#!/usr/bin/env bash
set -euo pipefail
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v ro="$RO_USER" -v password="$RO_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'ro', :'password') WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'ro') \gexec
SQL
