BEGIN;
SET LOCAL ROLE :"migration_user";

INSERT INTO app.integration_source
    (source_key, display_name, platform_instance, trino_catalog, enabled)
VALUES
    ('pms', 'PMS PostgreSQL', 'pms', 'pms', true),
    ('banquet', 'Banquet PostgreSQL', 'banquet', 'banquet', true),
    ('pos', 'F&B POS MySQL', 'pos', 'pos', true),
    ('crm', 'Membership CRM SQL Server', 'crm', 'crm', true),
    ('facility', 'Facility ClickHouse', 'facility', 'facility', true)
ON CONFLICT (source_key) DO UPDATE
SET display_name = EXCLUDED.display_name,
    platform_instance = EXCLUDED.platform_instance,
    trino_catalog = EXCLUDED.trino_catalog,
    enabled = EXCLUDED.enabled;

COMMIT;
