\set ON_ERROR_STOP on

BEGIN;
SET LOCAL TIME ZONE 'UTC';

WITH fixture_hash AS (
    SELECT md5(:'synthetic_data_seed' || ':app:audit:1') AS value
),
fixture_id AS (
    SELECT (
        substr(value, 1, 8) || '-' ||
        substr(value, 9, 4) || '-' ||
        substr(value, 13, 4) || '-' ||
        substr(value, 17, 4) || '-' ||
        substr(value, 21, 12)
    )::uuid AS audit_event_id
    FROM fixture_hash
)
INSERT INTO governance.audit_events (
    audit_event_id,
    request_id,
    actor_user_id,
    actor_role,
    action_code,
    object_type,
    object_id,
    context_release_id,
    model_version_id,
    sql_policy_version,
    query_execution_id,
    artifact_id,
    report_run_id,
    details_json_redacted,
    trace_id,
    created_at
)
SELECT
    audit_event_id,
    NULL,
    NULL,
    'SYSTEM',
    'SYNTHETIC_FIXTURE_INITIALIZED',
    'DATABASE_ENVIRONMENT',
    current_database(),
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    jsonb_build_object(
        'is_synthetic', true,
        'schema_version', :'database_schema_version',
        'synthetic_data_seed', :'synthetic_data_seed',
        'scenario_version', :'scenario_version',
        'fixture_version', :'fixture_version'
    ),
    NULL,
    :'generated_at'::timestamptz
FROM fixture_id
ON CONFLICT (audit_event_id) DO UPDATE
SET
    details_json_redacted = EXCLUDED.details_json_redacted,
    created_at = EXCLUDED.created_at;

COMMIT;
