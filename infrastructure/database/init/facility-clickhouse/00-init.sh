#!/bin/bash
set -Eeuo pipefail

required_variables=(
    CLICKHOUSE_DB
    CLICKHOUSE_USER
    CLICKHOUSE_PASSWORD
    DATABASE_SCHEMA_VERSION
    SYNTHETIC_DATA_SEED
    SCENARIO_VERSION
    FIXTURE_VERSION
    GENERATED_AT
    FACILITY_DATAHUB_PASSWORD
    FACILITY_TRINO_PASSWORD
)

for variable_name in "${required_variables[@]}"; do
    if [ -z "${!variable_name:-}" ]; then
        echo "[facility-clickhouse:init] missing required variable: ${variable_name}" >&2
        exit 1
    fi
done

password_pattern='^[A-Za-z0-9_!@#%^+=.,:-]{12,128}$'
for password_variable in FACILITY_DATAHUB_PASSWORD FACILITY_TRINO_PASSWORD; do
    password_value="${!password_variable}"
    if ! [[ "$password_value" =~ $password_pattern ]]; then
        echo "[facility-clickhouse:init] ${password_variable} contains unsupported characters or has invalid length" >&2
        exit 1
    fi
done

client=(
    clickhouse-client
    --user "$CLICKHOUSE_USER"
    --password "$CLICKHOUSE_PASSWORD"
    --database "$CLICKHOUSE_DB"
    --multiquery
)

"${client[@]}" \
    --param_database_schema_version "$DATABASE_SCHEMA_VERSION" \
    --param_synthetic_data_seed "$SYNTHETIC_DATA_SEED" \
    --param_scenario_version "$SCENARIO_VERSION" \
    --param_fixture_version "$FIXTURE_VERSION" \
    --param_generated_at "$GENERATED_AT" \
    --queries-file /docker-entrypoint-initdb.d/sql/01-schema.sql

"${client[@]}" --queries-file /docker-entrypoint-initdb.d/sql/02-reference.sql

"${client[@]}" \
    --param_synthetic_data_seed "$SYNTHETIC_DATA_SEED" \
    --param_generated_at "$GENERATED_AT" \
    --queries-file /docker-entrypoint-initdb.d/sql/03-synthetic.sql

"${client[@]}" --query "
CREATE ROLE IF NOT EXISTS facility_ingest;
CREATE ROLE IF NOT EXISTS facility_query;
GRANT SELECT, INSERT ON ${CLICKHOUSE_DB}.* TO facility_ingest;
GRANT SELECT ON ${CLICKHOUSE_DB}.* TO facility_query;
CREATE USER IF NOT EXISTS facility_datahub
    IDENTIFIED WITH sha256_password BY '${FACILITY_DATAHUB_PASSWORD}';
CREATE USER IF NOT EXISTS facility_trino
    IDENTIFIED WITH sha256_password BY '${FACILITY_TRINO_PASSWORD}';
ALTER USER facility_datahub
    IDENTIFIED WITH sha256_password BY '${FACILITY_DATAHUB_PASSWORD}';
ALTER USER facility_trino
    IDENTIFIED WITH sha256_password BY '${FACILITY_TRINO_PASSWORD}';
GRANT facility_query TO facility_datahub;
GRANT facility_query TO facility_trino;
"

echo "[facility-clickhouse:init] initialization complete"
