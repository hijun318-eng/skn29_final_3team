\set ON_ERROR_STOP on

SELECT 'CREATE ROLE pms_ingest NOLOGIN'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'pms_ingest'
)
\gexec

SELECT 'CREATE ROLE pms_query NOLOGIN'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'pms_query'
)
\gexec

SELECT 'CREATE ROLE pms_datahub LOGIN'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'pms_datahub'
)
\gexec

SELECT 'CREATE ROLE pms_trino LOGIN'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'pms_trino'
)
\gexec

ALTER ROLE pms_ingest
    WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE pms_query
    WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE pms_datahub
    WITH LOGIN PASSWORD :'pms_datahub_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE pms_trino
    WITH LOGIN PASSWORD :'pms_trino_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

GRANT pms_query TO pms_datahub, pms_trino;
REVOKE pms_ingest FROM pms_datahub, pms_trino;

ALTER ROLE pms_datahub SET default_transaction_read_only = on;
ALTER ROLE pms_trino SET default_transaction_read_only = on;
ALTER ROLE pms_datahub SET search_path = public, pg_catalog;
ALTER ROLE pms_trino SET search_path = public, pg_catalog;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE hotel_pms FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM pms_ingest, pms_query, pms_datahub, pms_trino;
REVOKE TEMPORARY ON DATABASE hotel_pms
    FROM pms_ingest, pms_query, pms_datahub, pms_trino;

GRANT CONNECT ON DATABASE hotel_pms
    TO pms_ingest, pms_query, pms_datahub, pms_trino;
GRANT USAGE ON SCHEMA public TO pms_ingest, pms_query;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA public
    TO pms_ingest;
GRANT USAGE, SELECT, UPDATE
    ON ALL SEQUENCES IN SCHEMA public
    TO pms_ingest;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO pms_query;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON ALL TABLES IN SCHEMA public
    FROM pms_query, pms_datahub, pms_trino;
REVOKE USAGE, UPDATE
    ON ALL SEQUENCES IN SCHEMA public
    FROM pms_query, pms_datahub, pms_trino;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pms_ingest;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO pms_ingest;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO pms_query;
