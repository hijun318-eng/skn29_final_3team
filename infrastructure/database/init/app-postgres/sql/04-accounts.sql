\set ON_ERROR_STOP on

SELECT 'CREATE ROLE app_migration LOGIN'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'app_migration'
)
\gexec

SELECT 'CREATE ROLE app_runtime LOGIN'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'app_runtime'
)
\gexec

ALTER ROLE app_migration
    WITH LOGIN PASSWORD :'app_migration_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE app_runtime
    WITH LOGIN PASSWORD :'app_runtime_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

ALTER ROLE app_migration SET search_path = connection, governance, reference, public, pg_catalog;
ALTER ROLE app_runtime SET search_path = connection, governance, reference, public, pg_catalog;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE hotel_datahub_app FROM PUBLIC;

GRANT CONNECT, CREATE ON DATABASE hotel_datahub_app TO app_migration;
GRANT CONNECT ON DATABASE hotel_datahub_app TO app_runtime;

ALTER SCHEMA connection OWNER TO app_migration;
ALTER SCHEMA governance OWNER TO app_migration;
ALTER SCHEMA reference OWNER TO app_migration;

ALTER TABLE connection.data_sources OWNER TO app_migration;
ALTER TABLE governance.audit_events OWNER TO app_migration;
ALTER TABLE reference.calendar_daily OWNER TO app_migration;

GRANT USAGE, CREATE ON SCHEMA connection, governance, reference TO app_migration;
GRANT USAGE ON SCHEMA connection, governance, reference TO app_runtime;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON connection.data_sources, reference.calendar_daily
    TO app_runtime;
GRANT SELECT, INSERT ON governance.audit_events TO app_runtime;
REVOKE UPDATE, DELETE, TRUNCATE
    ON governance.audit_events
    FROM app_runtime;

GRANT USAGE, SELECT, UPDATE
    ON ALL SEQUENCES IN SCHEMA connection, governance, reference
    TO app_runtime;

ALTER DEFAULT PRIVILEGES FOR ROLE app_migration IN SCHEMA connection
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_migration IN SCHEMA governance
    GRANT SELECT, INSERT ON TABLES TO app_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_migration IN SCHEMA reference
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime;

ALTER DEFAULT PRIVILEGES FOR ROLE app_migration IN SCHEMA connection
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO app_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_migration IN SCHEMA governance
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO app_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE app_migration IN SCHEMA reference
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO app_runtime;
