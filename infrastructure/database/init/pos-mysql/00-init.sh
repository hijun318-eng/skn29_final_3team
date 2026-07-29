#!/bin/bash
set -Eeuo pipefail

required_variables=(
    MYSQL_DATABASE
    MYSQL_ROOT_PASSWORD
    DATABASE_SCHEMA_VERSION
    SYNTHETIC_DATA_SEED
    SCENARIO_VERSION
    FIXTURE_VERSION
    GENERATED_AT
    POS_DATAHUB_PASSWORD
    POS_TRINO_PASSWORD
)

for variable_name in "${required_variables[@]}"; do
    if [ -z "${!variable_name:-}" ]; then
        echo "[pos-mysql:init] missing required variable: ${variable_name}" >&2
        exit 1
    fi
done

password_pattern='^[A-Za-z0-9_!@#%^+=.,:-]{12,128}$'
for password_variable in POS_DATAHUB_PASSWORD POS_TRINO_PASSWORD; do
    password_value="${!password_variable}"
    if ! [[ "$password_value" =~ $password_pattern ]]; then
        echo "[pos-mysql:init] ${password_variable} contains unsupported characters or has invalid length" >&2
        exit 1
    fi
done

mysql=(mysql --protocol=socket -uroot "-p${MYSQL_ROOT_PASSWORD}" "${MYSQL_DATABASE}")

"${mysql[@]}" --execute="
SET @database_schema_version = '${DATABASE_SCHEMA_VERSION}';
SET @synthetic_data_seed = '${SYNTHETIC_DATA_SEED}';
SET @scenario_version = '${SCENARIO_VERSION}';
SET @fixture_version = '${FIXTURE_VERSION}';
SET @generated_at = '${GENERATED_AT}';
SET @pos_datahub_password = '${POS_DATAHUB_PASSWORD}';
SET @pos_trino_password = '${POS_TRINO_PASSWORD}';
SOURCE /docker-entrypoint-initdb.d/sql/01-schema.sql;
SOURCE /docker-entrypoint-initdb.d/sql/02-reference.sql;
SOURCE /docker-entrypoint-initdb.d/sql/03-synthetic.sql;
SOURCE /docker-entrypoint-initdb.d/sql/04-accounts.sql;
SOURCE /docker-entrypoint-initdb.d/sql/05-environment-manifest.sql;
"

echo "[pos-mysql:init] initialization complete"
