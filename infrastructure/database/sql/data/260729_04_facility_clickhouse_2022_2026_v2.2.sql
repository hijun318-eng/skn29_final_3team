-- Facility deterministic synthetic load v2.2 for contract 1.0.0
-- seed=20260729; schema_version=1.0.0; scenario_version=1.0.0
-- fixture_version=1.0.0; synthetic=true; property_id=SYNTHETIC_HOTEL_001
SET session_timezone = 'UTC';
SET max_execution_time = 1800;
SET mutations_sync = 2;

SELECT throwIf(
    (SELECT count() FROM facility.facility_master WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0)
  + (SELECT count() FROM facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0)
  + (SELECT count() FROM facility.hotel_staffing_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0)
  + (SELECT count() FROM facility.facility_resource_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0) > 0,
  'SCHEMA_CONTRACT_MISMATCH'
);

ALTER TABLE facility.facility_events DELETE WHERE property_id='SYNTHETIC_HOTEL_001';
ALTER TABLE facility.hotel_staffing_daily DELETE WHERE property_id='SYNTHETIC_HOTEL_001';
ALTER TABLE facility.facility_resource_daily DELETE WHERE property_id='SYNTHETIC_HOTEL_001';
ALTER TABLE facility.facility_master DELETE WHERE property_id='SYNTHETIC_HOTEL_001';

INSERT INTO facility.facility_master
SELECT 'SYNTHETIC_HOTEL_001',
       concat('FAC-',leftPad(toString(number+1),3,'0')),
       concat('Synthetic Facility ',leftPad(toString(number+1),2,'0')),
       multiIf(number<4,'SPA',number<8,'POOL',number<11,'FITNESS',number<15,'ACTIVITY','BACK_OF_HOUSE'),
       multiIf(number<15,'FACILITY','ENGINEERING'),
       toUInt32(20 + (number%6)*15),
       toUInt8(6 + number%3),
       toUInt8(20 + number%4),
       toUInt8(1),toUInt8(1),
       toDateTime64('2026-07-28 05:00:00',3,'UTC')
FROM numbers(20);

INSERT INTO facility.facility_events
SELECT 'SYNTHETIC_HOTEL_001',
       concat('EVT-',substring(hex(cityHash64(
           concat('SYNTHETIC_HOTEL_001|',facility_id,'|',toString(event_at),'|',event_type,'|',toString(number))
       )),1,16)),
       facility_id,
       if(event_type='USAGE' AND facility_no<=15 AND number%10<3,
          concat('FACU-',leftPad(toString(1+number%80000),8,'0')),NULL),
       event_type,event_at,
       multiIf(event_type='USAGE',if(number%50=0,'FAILED','COMPLETED'),
               event_type='INSPECTION',if(number%20=0,'FAILED','COMPLETED'),
               if(number%3=0,'OPEN','CLOSED')),
       if(event_type='INCIDENT',if(number%100=0,'CRITICAL','WARNING'),'NORMAL'),
       toFloat32(15 + number%180),
       if(event_type='USAGE',toDecimal64(10000 + (number%9)*2500,2),toDecimal64(0,2)),
       toUInt32(if(event_type='INCIDENT',10+number%240,0)),
       multiIf(event_date<toDate('2025-01-01'),'REFERENCE_CALIBRATED',
               event_date<toDate('2026-01-01'),'SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC'),
       toUInt8(0),toUInt8(1),event_at + INTERVAL 1 HOUR
FROM (
    SELECT number,
           toUInt32(1+number%20) facility_no,
           concat('FAC-',leftPad(toString(1+number%20),3,'0')) facility_id,
           toDate('2022-01-01') + toIntervalDay(number%1669) event_date,
           toDateTime64(toDate('2022-01-01') + toIntervalDay(number%1669),3,'UTC')
             + toIntervalHour(6+number%14) + toIntervalMinute(number%60) event_at,
           multiIf(number%20<18,'USAGE',number%20=18,'INSPECTION','INCIDENT') event_type
    FROM numbers(700000)
);

INSERT INTO facility.hotel_staffing_daily
SELECT 'SYNTHETIC_HOTEL_001',
       concat('STF-',substring(hex(cityHash64(concat('SYNTHETIC_HOTEL_001|',toString(business_date),'|',department))),1,16)),
       business_date,department,
       toUInt32(approved_positions),
       toFloat32(approved_positions*8),
       toFloat32(approved_positions*8 - (day_no+department_no)%9),
       toDecimal64((approved_positions*8 - (day_no+department_no)%9) * (22000+department_no*1000),2),
       toFloat32(approved_positions - ((day_no+department_no)%3)/2),
       toUInt32((day_no+department_no)%3),
       toUInt32(if(day_no%90=0,1,0)),
       toUInt32(if(day_no%120=0,1,0)),
       multiIf(business_date<toDate('2025-01-01'),'REFERENCE_CALIBRATED',
               business_date<toDate('2026-01-01'),'SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC'),
       toUInt8(0),toUInt8(1),
       toDateTime64(business_date,3,'UTC') + INTERVAL 23 HOUR
FROM (
    SELECT days.number AS day_no,departments.number AS department_no,
           toDate('2022-01-01') + toIntervalDay(day_no) business_date,
           arrayElement(['ROOMS','FNB','FACILITY','ENGINEERING','BANQUET','SALES','ADMIN'],department_no+1) department,
           8 + department_no*3 approved_positions
    FROM numbers(1670) days
    CROSS JOIN numbers(7) departments
);

INSERT INTO facility.facility_resource_daily
SELECT 'SYNTHETIC_HOTEL_001',
       concat('RES-',substring(hex(cityHash64(concat('SYNTHETIC_HOTEL_001|',toString(business_date),'|',resource_scope))),1,16)),
       business_date,resource_scope,
       5000 + scope_no*1200 + (day_no%30)*25,
       120 + scope_no*35 + (day_no%20)*2,
       45 + scope_no*12 + day_no%10,
       toDecimal64(
           (5000 + scope_no*1200 + (day_no%30)*25)*130
           + (120 + scope_no*35 + (day_no%20)*2)*900,
           2
       ),
       toFloat32(24),
       toFloat32(if(day_no%45=0,1+scope_no,0)),
       multiIf(business_date<toDate('2025-01-01'),'REFERENCE_CALIBRATED',
               business_date<toDate('2026-01-01'),'SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC'),
       toUInt8(0),toUInt8(1),
       toDateTime64(business_date,3,'UTC') + INTERVAL 23 HOUR
FROM (
    SELECT days.number AS day_no,scopes.number AS scope_no,
           toDate('2022-01-01') + toIntervalDay(day_no) business_date,
           arrayElement(['HOTEL','ROOMS','FNB','FACILITY'],scope_no+1) resource_scope
    FROM numbers(1670) days
    CROSS JOIN numbers(4) scopes
);

SELECT 'facility_master' table_name,count() row_count,max(source_updated_at) watermark,
       hex(groupBitXor(cityHash64(facility_id))) checksum
FROM facility.facility_master WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'facility_events',count(),max(source_updated_at),hex(groupBitXor(cityHash64(event_id)))
FROM facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'hotel_staffing_daily',count(),max(source_updated_at),hex(groupBitXor(cityHash64(staffing_id)))
FROM facility.hotel_staffing_daily WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'facility_resource_daily',count(),max(source_updated_at),hex(groupBitXor(cityHash64(resource_id)))
FROM facility.facility_resource_daily WHERE property_id='SYNTHETIC_HOTEL_001';
