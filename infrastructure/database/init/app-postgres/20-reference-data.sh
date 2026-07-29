#!/usr/bin/env bash
(
set -Eeuo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v migration_user="$APP_MIGRATION_USER" \
  -f "$script_dir/sql/20-reference-data.sql"
)
