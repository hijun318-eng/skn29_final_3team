\set ON_ERROR_STOP on

BEGIN;

CREATE OR REPLACE VIEW public.environment_manifest AS
SELECT
    current_database()::text AS database_name,
    :'database_schema_version'::text AS schema_version,
    :'synthetic_data_seed'::bigint AS synthetic_data_seed,
    :'scenario_version'::text AS scenario_version,
    :'fixture_version'::text AS fixture_version,
    :'generated_at'::timestamptz AS generated_at,
    true::boolean AS is_synthetic;

REVOKE ALL ON public.environment_manifest FROM PUBLIC;
GRANT SELECT ON public.environment_manifest TO pms_ingest, pms_query;

COMMENT ON VIEW public.environment_manifest IS
    'Initialization manifest and healthcheck target. Query schema_version only after all bootstrap stages complete.';

COMMIT;
