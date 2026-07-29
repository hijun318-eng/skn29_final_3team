CREATE TABLE IF NOT EXISTS facility.facility
(
    facility_id UInt32,
    facility_name String,
    facility_type LowCardinality(String),
    building_code LowCardinality(String),
    active UInt8
)
ENGINE = MergeTree
ORDER BY facility_id;

CREATE TABLE IF NOT EXISTS facility.work_order
(
    work_order_id UInt64,
    facility_id UInt32,
    opened_at DateTime('Asia/Seoul'),
    closed_at Nullable(DateTime('Asia/Seoul')),
    priority LowCardinality(String),
    status LowCardinality(String),
    description String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(opened_at)
ORDER BY (facility_id, opened_at, work_order_id);

CREATE TABLE IF NOT EXISTS facility.sensor_reading
(
    facility_id UInt32,
    measured_at DateTime('Asia/Seoul'),
    metric LowCardinality(String),
    value Float64,
    unit LowCardinality(String)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(measured_at)
ORDER BY (facility_id, metric, measured_at);

CREATE TABLE IF NOT EXISTS facility.schema_version
(
    version String,
    seed UInt64,
    applied_at DateTime('Asia/Seoul')
)
ENGINE = ReplacingMergeTree
ORDER BY version;
