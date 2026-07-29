#!/bin/sh
set -eu

: "${POSTGRES_USER:=postgres}"
: "${POSTGRES_DB:?POSTGRES_DB must be set to hotel_pms}"
: "${DATABASE_SCHEMA_VERSION:?DATABASE_SCHEMA_VERSION is required}"
: "${SYNTHETIC_DATA_SEED:?SYNTHETIC_DATA_SEED is required}"
: "${SCENARIO_VERSION:?SCENARIO_VERSION is required}"
: "${FIXTURE_VERSION:?FIXTURE_VERSION is required}"
: "${GENERATED_AT:?GENERATED_AT is required}"
: "${PMS_DATAHUB_PASSWORD:?PMS_DATAHUB_PASSWORD is required}"
: "${PMS_TRINO_PASSWORD:?PMS_TRINO_PASSWORD is required}"

if [ "$POSTGRES_DB" != "hotel_pms" ]; then
    echo "[pms-postgres:init] expected POSTGRES_DB=hotel_pms, got $POSTGRES_DB" >&2
    exit 1
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || true)
if [ -n "$script_dir" ] && [ -d "$script_dir/sql" ]; then
    init_dir=$script_dir
else
    init_dir=/docker-entrypoint-initdb.d
fi

run_sql() {
    file_name=$1
    echo "[pms-postgres:init] running $file_name"
    psql \
        --no-psqlrc \
        --username "$POSTGRES_USER" \
        --dbname "$POSTGRES_DB" \
        --set=ON_ERROR_STOP=1 \
        --set="database_schema_version=$DATABASE_SCHEMA_VERSION" \
        --set="synthetic_data_seed=$SYNTHETIC_DATA_SEED" \
        --set="scenario_version=$SCENARIO_VERSION" \
        --set="fixture_version=$FIXTURE_VERSION" \
        --set="generated_at=$GENERATED_AT" \
        --file "$init_dir/sql/$file_name"
}

run_sql 01-schema.sql
run_sql 02-reference.sql
run_sql 03-synthetic.sql

echo "[pms-postgres:init] configuring isolated source accounts"
psql \
    --no-psqlrc \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set=ON_ERROR_STOP=1 \
    --set="pms_datahub_password=$PMS_DATAHUB_PASSWORD" \
    --set="pms_trino_password=$PMS_TRINO_PASSWORD" \
    --file "$init_dir/sql/04-accounts.sql"

# Healthchecks target this view, so it must be the final initialization step.
run_sql 05-environment-manifest.sql

echo "[pms-postgres:init] initialization complete"
