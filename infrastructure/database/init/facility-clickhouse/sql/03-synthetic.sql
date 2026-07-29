INSERT INTO facility_master
SELECT
    'SYNTHETIC_HOTEL_001',
    concat('FAC-', upper(substring(hex(MD5(concat({synthetic_data_seed:String}, ':facility:master:1'))), 1, 8))),
    'Synthetic Fitness Center',
    'FITNESS',
    'FACILITY',
    40,
    6,
    22,
    1,
    1,
    parseDateTime64BestEffort({generated_at:String}, 3, 'UTC');

INSERT INTO facility_events
SELECT
    'SYNTHETIC_HOTEL_001',
    concat('EVT-', upper(substring(hex(MD5(concat({synthetic_data_seed:String}, ':facility:event:1'))), 1, 8))),
    concat('FAC-', upper(substring(hex(MD5(concat({synthetic_data_seed:String}, ':facility:master:1'))), 1, 8))),
    concat('FCU-', upper(substring(hex(MD5(concat({synthetic_data_seed:String}, ':cross:customer:1'))), 1, 8))),
    'USAGE',
    toDateTime64('2026-07-28 10:00:00', 3, 'UTC'),
    'COMPLETED',
    'NORMAL',
    toFloat32(60),
    toDecimal64(25000, 2),
    toUInt32(0),
    'YTD_SYNTHETIC',
    toUInt8(0),
    toUInt8(1),
    parseDateTime64BestEffort({generated_at:String}, 3, 'UTC');

INSERT INTO hotel_staffing_daily
SELECT
    'SYNTHETIC_HOTEL_001',
    concat('STF-', upper(substring(hex(MD5(concat({synthetic_data_seed:String}, ':facility:staffing:1'))), 1, 8))),
    toDate('2026-07-28'),
    'FACILITY',
    toUInt32(8),
    toFloat32(64),
    toFloat32(62),
    toDecimal64(1860000, 2),
    toFloat32(7.75),
    toUInt32(0),
    toUInt32(0),
    toUInt32(0),
    'YTD_SYNTHETIC',
    toUInt8(0),
    toUInt8(1),
    parseDateTime64BestEffort({generated_at:String}, 3, 'UTC');

INSERT INTO facility_resource_daily
SELECT
    'SYNTHETIC_HOTEL_001',
    concat('RES-', upper(substring(hex(MD5(concat({synthetic_data_seed:String}, ':facility:resource:1'))), 1, 8))),
    toDate('2026-07-28'),
    'HOTEL',
    toFloat64(12800.5),
    toFloat64(410.25),
    toFloat64(280.75),
    toDecimal64(3140000, 2),
    toFloat32(24),
    toFloat32(0.5),
    'YTD_SYNTHETIC',
    toUInt8(0),
    toUInt8(1),
    parseDateTime64BestEffort({generated_at:String}, 3, 'UTC');
