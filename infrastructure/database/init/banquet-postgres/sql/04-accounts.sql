\set ON_ERROR_STOP on

SELECT 'CREATE ROLE banquet_ingest NOLOGIN'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'banquet_ingest'
)
\gexec

SELECT 'CREATE ROLE banquet_query NOLOGIN'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'banquet_query'
)
\gexec

SELECT 'CREATE ROLE banquet_datahub LOGIN'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'banquet_datahub'
)
\gexec

SELECT 'CREATE ROLE banquet_trino LOGIN'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'banquet_trino'
)
\gexec

ALTER ROLE banquet_ingest
    WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE banquet_query
    WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE banquet_datahub
    WITH LOGIN PASSWORD :'banquet_datahub_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE banquet_trino
    WITH LOGIN PASSWORD :'banquet_trino_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

GRANT banquet_query TO banquet_datahub, banquet_trino;
REVOKE banquet_ingest FROM banquet_datahub, banquet_trino;

ALTER ROLE banquet_datahub SET default_transaction_read_only = on;
ALTER ROLE banquet_trino SET default_transaction_read_only = on;
ALTER ROLE banquet_datahub SET search_path = public, pg_catalog;
ALTER ROLE banquet_trino SET search_path = public, pg_catalog;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE hotel_banquet FROM PUBLIC;
REVOKE CREATE ON SCHEMA public
    FROM banquet_ingest, banquet_query, banquet_datahub, banquet_trino;
REVOKE TEMPORARY ON DATABASE hotel_banquet
    FROM banquet_ingest, banquet_query, banquet_datahub, banquet_trino;

GRANT CONNECT ON DATABASE hotel_banquet
    TO banquet_ingest, banquet_query, banquet_datahub, banquet_trino;
GRANT USAGE ON SCHEMA public TO banquet_ingest, banquet_query;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA public
    TO banquet_ingest;
GRANT USAGE, SELECT, UPDATE
    ON ALL SEQUENCES IN SCHEMA public
    TO banquet_ingest;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO banquet_query;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON ALL TABLES IN SCHEMA public
    FROM banquet_query, banquet_datahub, banquet_trino;
REVOKE USAGE, UPDATE
    ON ALL SEQUENCES IN SCHEMA public
    FROM banquet_query, banquet_datahub, banquet_trino;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO banquet_ingest;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO banquet_ingest;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO banquet_query;
