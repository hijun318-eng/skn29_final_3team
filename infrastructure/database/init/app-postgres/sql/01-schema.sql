\set ON_ERROR_STOP on

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS connection;
CREATE SCHEMA IF NOT EXISTS governance;
CREATE SCHEMA IF NOT EXISTS reference;

CREATE TABLE IF NOT EXISTS connection.data_sources (
    data_source_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_code varchar(32) NOT NULL,
    source_name varchar(120) NOT NULL,
    engine_type varchar(24) NOT NULL,
    platform_instance varchar(128) NOT NULL,
    trino_catalog varchar(128) NOT NULL,
    datahub_recipe_ref varchar(255) NOT NULL,
    connection_ref varchar(255) NOT NULL,
    owner_team varchar(100) NOT NULL,
    status varchar(16) NOT NULL,
    last_health_status varchar(16),
    last_health_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT uq_data_sources_source_code UNIQUE (source_code),
    CONSTRAINT uq_data_sources_platform_instance UNIQUE (platform_instance),
    CONSTRAINT uq_data_sources_trino_catalog UNIQUE (trino_catalog),
    CONSTRAINT ck_data_sources_source_code
        CHECK (source_code IN ('PMS', 'POS', 'CRM', 'FACILITY', 'BANQUET')),
    CONSTRAINT ck_data_sources_engine_type
        CHECK (engine_type IN ('POSTGRESQL', 'MYSQL', 'SQLSERVER', 'CLICKHOUSE')),
    CONSTRAINT ck_data_sources_status
        CHECK (status IN ('DRAFT', 'ACTIVE', 'ERROR', 'DISABLED')),
    CONSTRAINT ck_data_sources_health
        CHECK (
            last_health_status IS NULL
            OR last_health_status IN ('HEALTHY', 'DEGRADED', 'DOWN', 'UNKNOWN')
        ),
    CONSTRAINT ck_data_sources_connection_ref
        CHECK (connection_ref LIKE 'env://%')
);

CREATE TABLE IF NOT EXISTS governance.audit_events (
    audit_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id uuid,
    actor_user_id uuid,
    actor_role varchar(64) NOT NULL,
    action_code varchar(96) NOT NULL,
    object_type varchar(64) NOT NULL,
    object_id varchar(128) NOT NULL,
    context_release_id uuid,
    model_version_id uuid,
    sql_policy_version varchar(64),
    query_execution_id uuid,
    artifact_id uuid,
    report_run_id uuid,
    details_json_redacted jsonb NOT NULL DEFAULT '{}'::jsonb,
    trace_id varchar(128),
    created_at timestamptz NOT NULL,
    CONSTRAINT ck_audit_events_actor_role_nonempty
        CHECK (btrim(actor_role) <> ''),
    CONSTRAINT ck_audit_events_action_code_nonempty
        CHECK (btrim(action_code) <> ''),
    CONSTRAINT ck_audit_events_object_nonempty
        CHECK (btrim(object_type) <> '' AND btrim(object_id) <> '')
);

CREATE INDEX IF NOT EXISTS ix_audit_events_request_created
    ON governance.audit_events (request_id, created_at);
CREATE INDEX IF NOT EXISTS ix_audit_events_action_created
    ON governance.audit_events (action_code, created_at);

CREATE TABLE IF NOT EXISTS reference.calendar_daily (
    business_date date PRIMARY KEY,
    year smallint NOT NULL,
    quarter smallint NOT NULL,
    month smallint NOT NULL,
    week_of_year smallint NOT NULL,
    day_of_week smallint NOT NULL,
    is_weekend boolean NOT NULL,
    is_public_holiday boolean NOT NULL,
    is_holiday_eve boolean NOT NULL,
    season_code varchar(24) NOT NULL,
    school_vacation_code varchar(24),
    domestic_travel_index numeric(12,6) NOT NULL,
    inbound_travel_index numeric(12,6) NOT NULL,
    event_demand_index numeric(12,6) NOT NULL,
    weather_scenario_code varchar(32) NOT NULL,
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT ck_calendar_quarter CHECK (quarter BETWEEN 1 AND 4),
    CONSTRAINT ck_calendar_month CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT ck_calendar_day_of_week CHECK (day_of_week BETWEEN 1 AND 7),
    CONSTRAINT ck_calendar_season
        CHECK (season_code IN ('SPRING', 'SUMMER', 'AUTUMN', 'WINTER')),
    CONSTRAINT ck_calendar_period_status
        CHECK (
            data_period_status IN (
                'REFERENCE_CALIBRATED',
                'SYNTHETIC_ACTUAL_LIKE',
                'YTD_SYNTHETIC',
                'FORECAST_SCENARIO'
            )
        ),
    CONSTRAINT ck_calendar_forecast_consistency
        CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO')),
    CONSTRAINT ck_calendar_period_cutoff
        CHECK (
            (business_date < DATE '2026-07-29' AND NOT is_forecast)
            OR (business_date >= DATE '2026-07-29' AND is_forecast)
        )
);

COMMENT ON TABLE connection.data_sources IS
    'Logical source to DataHub recipe and Trino catalog bindings; secrets are env references only.';
COMMENT ON TABLE governance.audit_events IS
    'Append-only redacted audit events. Optional UUID references remain logical until the owning tables are introduced.';
COMMENT ON TABLE reference.calendar_daily IS
    'Synthetic business calendar with explicit actual-like/YTD/forecast policy state.';

COMMIT;
