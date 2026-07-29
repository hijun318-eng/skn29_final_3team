\set ON_ERROR_STOP on

BEGIN;
SET LOCAL TIME ZONE 'UTC';

INSERT INTO connection.data_sources (
    data_source_id,
    source_code,
    source_name,
    engine_type,
    platform_instance,
    trino_catalog,
    datahub_recipe_ref,
    connection_ref,
    owner_team,
    status,
    last_health_status,
    last_health_at,
    created_at,
    updated_at
)
VALUES
    (
        '00000000-0000-4000-8000-000000000001',
        'PMS',
        'Synthetic PMS',
        'POSTGRESQL',
        'pms',
        'pms',
        'recipe://pms/v1',
        'env://PMS_DATAHUB_DSN',
        'data-platform',
        'DRAFT',
        NULL,
        NULL,
        :'generated_at'::timestamptz,
        :'generated_at'::timestamptz
    ),
    (
        '00000000-0000-4000-8000-000000000002',
        'POS',
        'Synthetic F&B POS',
        'MYSQL',
        'pos',
        'pos',
        'recipe://pos/v1',
        'env://POS_DATAHUB_DSN',
        'data-platform',
        'DRAFT',
        NULL,
        NULL,
        :'generated_at'::timestamptz,
        :'generated_at'::timestamptz
    ),
    (
        '00000000-0000-4000-8000-000000000003',
        'CRM',
        'Synthetic Membership CRM',
        'SQLSERVER',
        'crm',
        'crm',
        'recipe://crm/v1',
        'env://CRM_DATAHUB_DSN',
        'data-platform',
        'DRAFT',
        NULL,
        NULL,
        :'generated_at'::timestamptz,
        :'generated_at'::timestamptz
    ),
    (
        '00000000-0000-4000-8000-000000000004',
        'FACILITY',
        'Synthetic Facility Operations',
        'CLICKHOUSE',
        'facility',
        'facility',
        'recipe://facility/v1',
        'env://FACILITY_DATAHUB_DSN',
        'data-platform',
        'DRAFT',
        NULL,
        NULL,
        :'generated_at'::timestamptz,
        :'generated_at'::timestamptz
    ),
    (
        '00000000-0000-4000-8000-000000000005',
        'BANQUET',
        'Synthetic Banquet Operations',
        'POSTGRESQL',
        'banquet',
        'banquet',
        'recipe://banquet/v1',
        'env://BANQUET_DATAHUB_DSN',
        'data-platform',
        'DRAFT',
        NULL,
        NULL,
        :'generated_at'::timestamptz,
        :'generated_at'::timestamptz
    )
ON CONFLICT (source_code) DO UPDATE
SET
    source_name = EXCLUDED.source_name,
    engine_type = EXCLUDED.engine_type,
    platform_instance = EXCLUDED.platform_instance,
    trino_catalog = EXCLUDED.trino_catalog,
    datahub_recipe_ref = EXCLUDED.datahub_recipe_ref,
    connection_ref = EXCLUDED.connection_ref,
    owner_team = EXCLUDED.owner_team,
    updated_at = EXCLUDED.updated_at;

INSERT INTO reference.calendar_daily (
    business_date,
    year,
    quarter,
    month,
    week_of_year,
    day_of_week,
    is_weekend,
    is_public_holiday,
    is_holiday_eve,
    season_code,
    school_vacation_code,
    domestic_travel_index,
    inbound_travel_index,
    event_demand_index,
    weather_scenario_code,
    data_period_status,
    is_forecast,
    created_at
)
VALUES
    (
        DATE '2026-07-28',
        2026,
        3,
        7,
        31,
        2,
        false,
        false,
        false,
        'SUMMER',
        'SUMMER',
        1.000000,
        1.000000,
        1.000000,
        'BASELINE',
        'YTD_SYNTHETIC',
        false,
        :'generated_at'::timestamptz
    ),
    (
        DATE '2026-07-29',
        2026,
        3,
        7,
        31,
        3,
        false,
        false,
        false,
        'SUMMER',
        'SUMMER',
        1.010000,
        1.020000,
        1.000000,
        'BASELINE',
        'FORECAST_SCENARIO',
        true,
        :'generated_at'::timestamptz
    )
ON CONFLICT (business_date) DO UPDATE
SET
    domestic_travel_index = EXCLUDED.domestic_travel_index,
    inbound_travel_index = EXCLUDED.inbound_travel_index,
    event_demand_index = EXCLUDED.event_demand_index,
    weather_scenario_code = EXCLUDED.weather_scenario_code,
    data_period_status = EXCLUDED.data_period_status,
    is_forecast = EXCLUDED.is_forecast,
    created_at = EXCLUDED.created_at;

COMMIT;
