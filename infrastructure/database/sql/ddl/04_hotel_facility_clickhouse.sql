-- 책임: facility source의 빈 ClickHouse table 계약과 정렬 key만 생성한다. 운영
-- event는 외부 ingestion에서 오며 고정 fixture로 누락을 채우지 않는다.
-- source_id=facility; engine=ClickHouse; database=facility
-- ingestion_role=facility_ingest; query_role=facility_readonly
-- datahub_platform_instance=facility; trino_catalog=facility
-- schema_version=1.0.0
CREATE DATABASE IF NOT EXISTS facility;

CREATE ROLE IF NOT EXISTS facility_ingest;
CREATE ROLE IF NOT EXISTS facility_readonly;

CREATE TABLE IF NOT EXISTS facility.facility_master (
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
    source_updated_at DateTime64(3, 'UTC'),
    CONSTRAINT ck_facility_master_hours CHECK close_hour > open_hour
) ENGINE = MergeTree
ORDER BY (property_id, facility_id)
COMMENT 'Facility master';

CREATE TABLE IF NOT EXISTS facility.facility_events (
    property_id String,
    event_id String,
    facility_id String,
    facility_user_ref Nullable(String),
    event_type LowCardinality(String),
    event_at DateTime64(3, 'UTC'),
    event_status LowCardinality(String),
    severity LowCardinality(Nullable(String)),
    duration_minutes Float32,
    amount Decimal(14,2),
    downtime_minutes UInt32,
    data_period_status LowCardinality(String),
    is_forecast UInt8,
    is_synthetic UInt8,
    source_updated_at DateTime64(3, 'UTC'),
    CONSTRAINT ck_facility_event_type CHECK event_type IN ('USAGE','INSPECTION','INCIDENT'),
    CONSTRAINT ck_facility_event_nonnegative CHECK duration_minutes >= 0 AND amount >= 0
) ENGINE = MergeTree
ORDER BY (property_id, facility_id, event_at, event_id)
COMMENT 'Facility usage, inspection, and incident events';

CREATE TABLE IF NOT EXISTS facility.hotel_staffing_daily (
    property_id String,
    staffing_id String,
    business_date Date,
    department LowCardinality(String),
    approved_positions UInt32,
    scheduled_hours Float32,
    worked_hours Float32,
    labor_cost Decimal(14,2),
    fte Float32,
    vacancies UInt32,
    new_hires UInt32,
    separations UInt32,
    data_period_status LowCardinality(String),
    is_forecast UInt8,
    is_synthetic UInt8,
    source_updated_at DateTime64(3, 'UTC'),
    CONSTRAINT ck_staffing_hours CHECK scheduled_hours >= 0 AND worked_hours >= 0,
    CONSTRAINT ck_staffing_vacancies CHECK vacancies <= approved_positions
) ENGINE = MergeTree
ORDER BY (property_id, business_date, department)
COMMENT 'Daily staffing and labor cost';

CREATE TABLE IF NOT EXISTS facility.facility_resource_daily (
    property_id String,
    resource_id String,
    business_date Date,
    resource_scope LowCardinality(String),
    energy_kwh Float64,
    water_m3 Float64,
    waste_kg Float64,
    resource_cost Decimal(14,2),
    scheduled_hours Float32,
    downtime_hours Float32,
    data_period_status LowCardinality(String),
    is_forecast UInt8,
    is_synthetic UInt8,
    source_updated_at DateTime64(3, 'UTC'),
    CONSTRAINT ck_resource_nonnegative CHECK energy_kwh >= 0 AND water_m3 >= 0 AND waste_kg >= 0 AND resource_cost >= 0,
    CONSTRAINT ck_resource_downtime CHECK downtime_hours >= 0 AND downtime_hours <= scheduled_hours
) ENGINE = MergeTree
ORDER BY (property_id, business_date, resource_scope)
COMMENT 'Daily energy, water, waste, and resource cost';

CREATE TABLE IF NOT EXISTS facility.schema_version (
    version String
) ENGINE = ReplacingMergeTree
ORDER BY version;
-- DDL versioning is deterministic. Dataset/release provenance is intentionally
-- not bootstrapped, because doing so would certify data that was never loaded.
INSERT INTO facility.schema_version SELECT '1.0.0' WHERE NOT EXISTS (SELECT 1 FROM facility.schema_version WHERE version = '1.0.0');

GRANT SELECT, INSERT, ALTER DELETE ON facility.* TO facility_ingest;
GRANT SELECT ON facility.* TO facility_readonly;

SELECT count() AS facility_table_count
FROM system.tables
WHERE database = 'facility';
