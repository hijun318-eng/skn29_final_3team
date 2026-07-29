CREATE TABLE IF NOT EXISTS facility_master (
    property_id String,
    facility_id String,
    facility_name String,
    facility_type LowCardinality(String),
    owner_team LowCardinality(String),
    capacity UInt32,
    open_hour UInt8,
    close_hour UInt8,
    is_active UInt8,
    is_synthetic UInt8,
    source_updated_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(source_updated_at)
ORDER BY facility_id
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS facility_events (
    property_id String,
    event_id String,
    facility_id String,
    facility_user_ref Nullable(String),
    event_type LowCardinality(String),
    event_at DateTime64(3, 'UTC'),
    event_status LowCardinality(String),
    severity Nullable(String),
    duration_minutes Float32,
    amount Decimal(14, 2),
    downtime_minutes UInt32,
    data_period_status LowCardinality(String),
    is_forecast UInt8,
    is_synthetic UInt8,
    source_updated_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(source_updated_at)
ORDER BY (event_at, event_id)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS hotel_staffing_daily (
    property_id String,
    staffing_id String,
    business_date Date,
    department LowCardinality(String),
    approved_positions UInt32,
    scheduled_hours Float32,
    worked_hours Float32,
    labor_cost Decimal(14, 2),
    fte Float32,
    vacancies UInt32,
    new_hires UInt32,
    separations UInt32,
    data_period_status LowCardinality(String),
    is_forecast UInt8,
    is_synthetic UInt8,
    source_updated_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(source_updated_at)
ORDER BY (business_date, department, staffing_id)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS facility_resource_daily (
    property_id String,
    resource_id String,
    business_date Date,
    resource_scope LowCardinality(String),
    energy_kwh Float64,
    water_m3 Float64,
    waste_kg Float64,
    resource_cost Decimal(14, 2),
    scheduled_hours Float32,
    downtime_hours Float32,
    data_period_status LowCardinality(String),
    is_forecast UInt8,
    is_synthetic UInt8,
    source_updated_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(source_updated_at)
ORDER BY (business_date, resource_scope, resource_id)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS environment_manifest (
    database_name String,
    schema_version String,
    synthetic_data_seed UInt64,
    scenario_version String,
    fixture_version String,
    generated_at DateTime64(3, 'UTC'),
    is_synthetic UInt8
) ENGINE = TinyLog;

TRUNCATE TABLE environment_manifest;

INSERT INTO environment_manifest VALUES (
    currentDatabase(),
    {database_schema_version:String},
    toUInt64({synthetic_data_seed:String}),
    {scenario_version:String},
    {fixture_version:String},
    parseDateTime64BestEffort({generated_at:String}, 3, 'UTC'),
    toUInt8(1)
);
