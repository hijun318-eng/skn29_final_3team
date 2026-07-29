-- ============================================================================
-- Answervice 팀공유 SQL 산출물
-- ownership_contract=team-ownership-v2.1
-- schema_version=schema-v4.6-websql
-- snapshot_as_of_at=2026-07-28T05:00:00Z
-- generation_as_of_at=2026-07-28T05:00:00Z
-- evaluation_as_of=2026-07-28T14:00:00+09:00
-- GENERATE_FILES=true / RUN_STATIC_VALIDATION=true / EXECUTE_DB=false
-- 접속정보·healthy 컨테이너는 실행 승인으로 간주하지 않는다.
-- 실제 실행 전 해당 owner의 approval_id가 필요하다.
-- ============================================================================
-- owner=R2_정승
-- work_card=R2-SEED
-- source_document=v2.3
-- output=260729_04_facility_clickhouse_2022_2026_v2.3.sql

-- Answervice 합성 Source 데이터 적재 SQL
-- seed=20260728
-- schema_version=schema-v4.6-websql
-- scenario_version=scenario-v4.6
-- fixture_version=source-fixture-v4.6
-- property_id=SYNTHETIC_HOTEL_001
-- synthetic=true
-- generated_at=2026-07-28T05:00:00Z
-- simulation_as_of_date=2026-07-28
-- evaluation_as_of=2026-07-28T14:00:00+09:00
-- storage_timezone=UTC / business_timezone=Asia/Seoul
-- 주의: 이 파일은 DDL을 생성하지 않는다. v4.6 DDL이 먼저 적용되어 있어야 한다.
-- 검증 상태: STATIC_REVALIDATED_PASS / DB_EXECUTION_NOT_RUN. 실제 ClickHouse 실행 결과는 하단 검증 SELECT로 확인한다.

-- source_id=facility / engine=ClickHouse 24+ / database=hotel_facility
-- ingestion_role=facility_ingest / query_role=facility_query
-- datahub_platform_instance=hotel_facility / trino_catalog=facility
-- output=260728_04_facility_clickhouse_2022_2026_v2.3.sql

USE hotel_facility;
SET session_timezone = 'UTC';
SET max_execution_time = 1800;
SET mutations_sync = 2;
SET join_use_nulls = 1;

-- 스키마 계약과 비합성 행 보호.
SELECT throwIf((SELECT groupArray((name,replaceAll(type,' ',''))) FROM (SELECT name,type FROM system.columns WHERE database='hotel_facility' AND table='facility_master' ORDER BY position)) != [('property_id','String'),('facility_id','String'),('facility_name','String'),('facility_type','LowCardinality(String)'),('owner_team','LowCardinality(String)'),('capacity','UInt32'),('open_hour','UInt8'),('close_hour','UInt8'),('is_active','UInt8'),('is_synthetic','UInt8'),('source_updated_at','DateTime64(3,\'UTC\')')],'SCHEMA_CONTRACT_MISMATCH: facility_master');
SELECT throwIf((SELECT groupArray((name,replaceAll(type,' ',''))) FROM (SELECT name,type FROM system.columns WHERE database='hotel_facility' AND table='facility_events' ORDER BY position)) != [('property_id','String'),('event_id','String'),('facility_id','String'),('facility_user_ref','Nullable(String)'),('event_type','LowCardinality(String)'),('event_at','DateTime64(3,\'UTC\')'),('event_status','LowCardinality(String)'),('severity','Nullable(LowCardinality(String))'),('duration_minutes','Float32'),('amount','Decimal(14,2)'),('downtime_minutes','UInt32'),('data_period_status','LowCardinality(String)'),('is_forecast','UInt8'),('is_synthetic','UInt8'),('source_updated_at','DateTime64(3,\'UTC\')')],'SCHEMA_CONTRACT_MISMATCH: facility_events');
SELECT throwIf((SELECT groupArray((name,replaceAll(type,' ',''))) FROM (SELECT name,type FROM system.columns WHERE database='hotel_facility' AND table='hotel_staffing_daily' ORDER BY position)) != [('property_id','String'),('staffing_id','String'),('business_date','Date'),('department','LowCardinality(String)'),('approved_positions','UInt32'),('scheduled_hours','Float32'),('worked_hours','Float32'),('labor_cost','Decimal(14,2)'),('fte','Float32'),('vacancies','UInt32'),('new_hires','UInt32'),('separations','UInt32'),('data_period_status','LowCardinality(String)'),('is_forecast','UInt8'),('is_synthetic','UInt8'),('source_updated_at','DateTime64(3,\'UTC\')')],'SCHEMA_CONTRACT_MISMATCH: hotel_staffing_daily');
SELECT throwIf((SELECT groupArray((name,replaceAll(type,' ',''))) FROM (SELECT name,type FROM system.columns WHERE database='hotel_facility' AND table='facility_resource_daily' ORDER BY position)) != [('property_id','String'),('resource_id','String'),('business_date','Date'),('resource_scope','LowCardinality(String)'),('energy_kwh','Float64'),('water_m3','Float64'),('waste_kg','Float64'),('resource_cost','Decimal(14,2)'),('scheduled_hours','Float32'),('downtime_hours','Float32'),('data_period_status','LowCardinality(String)'),('is_forecast','UInt8'),('is_synthetic','UInt8'),('source_updated_at','DateTime64(3,\'UTC\')')],'SCHEMA_CONTRACT_MISMATCH: facility_resource_daily');
SELECT throwIf(replaceAll((SELECT sorting_key FROM system.tables WHERE database='hotel_facility' AND name='facility_master'),' ','') != 'property_id,facility_id','SCHEMA_CONTRACT_MISMATCH: facility_master ORDER BY');
SELECT throwIf(replaceAll((SELECT sorting_key FROM system.tables WHERE database='hotel_facility' AND name='facility_events'),' ','') != 'property_id,facility_id,event_at,event_id','SCHEMA_CONTRACT_MISMATCH: facility_events ORDER BY');
SELECT throwIf(replaceAll((SELECT sorting_key FROM system.tables WHERE database='hotel_facility' AND name='hotel_staffing_daily'),' ','') != 'property_id,business_date,department','SCHEMA_CONTRACT_MISMATCH: hotel_staffing_daily ORDER BY');
SELECT throwIf(replaceAll((SELECT sorting_key FROM system.tables WHERE database='hotel_facility' AND name='facility_resource_daily'),' ','') != 'property_id,business_date,resource_scope','SCHEMA_CONTRACT_MISMATCH: facility_resource_daily ORDER BY');
SELECT throwIf(
 (SELECT count() FROM hotel_facility.facility_master WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0)
 +(SELECT count() FROM hotel_facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0)
 +(SELECT count() FROM hotel_facility.hotel_staffing_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0)
 +(SELECT count() FROM hotel_facility.facility_resource_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=0)>0,
 'NON_SYNTHETIC_ROW_PRESENT');

ALTER TABLE hotel_facility.facility_events DELETE WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=1;
ALTER TABLE hotel_facility.hotel_staffing_daily DELETE WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=1;
ALTER TABLE hotel_facility.facility_resource_daily DELETE WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=1;
ALTER TABLE hotel_facility.facility_master DELETE WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=1;

INSERT INTO hotel_facility.facility_master
SELECT 'SYNTHETIC_HOTEL_001',concat('FAC-',leftPad(toString(number+1),3,'0')),
       concat('Synthetic Facility ',leftPad(toString(number+1),2,'0')),
       arrayElement(['SPA','POOL','FITNESS','ACTIVITY','MEETING_SUPPORT','BACK_OF_HOUSE'],1+(number%6)),
       arrayElement(['FACILITY','RECREATION','ENGINEERING','BANQUET'],1+(number%4)),
       toUInt32(20+(number%8)*15),toUInt8(if(number%6=5,0,6+(number%3))),toUInt8(if(number%6=5,23,20+(number%3))),
       toUInt8(1),toUInt8(1),toDateTime64('2026-07-28 04:00:00',3,'UTC')
FROM numbers(20);

-- 과거 관측 이벤트 800,000건. event_id는 승인 자연키로 생성한다.
INSERT INTO hotel_facility.facility_events
WITH
  toDateTime64('2022-01-01 00:00:00',3,'UTC') AS start_at,
  toDateTime64('2026-07-28 05:00:00',3,'UTC') AS generation_at,
  base AS (
    SELECT number,
      concat('FAC-',leftPad(toString(1+(number%20)),3,'0')) facility_id,
      if(number%100<90,'USAGE',if(number%100<97,'INSPECTION','INCIDENT')) event_type,
      start_at + toIntervalSecond((number*7919)%143078400) event_at
    FROM numbers(800000)
  )
SELECT
 'SYNTHETIC_HOTEL_001',
 concat('EVT-',lower(hex(MD5(concat('SYNTHETIC_HOTEL_001|',facility_id,'|',formatDateTime(event_at,'%Y-%m-%dT%H:%i:%S','UTC'),'|',event_type,'|1'))))) event_id,
 facility_id,
 if((((number%20)+1)%6)=0 OR number%100>=90,CAST(NULL,'Nullable(String)'),CAST(concat('FACU-',leftPad(toString(1+(number%80000)),8,'0')),'Nullable(String)')),
 event_type,event_at,
 if(event_type='USAGE',if(number%50=0,'FAILED','COMPLETED'),if(event_type='INSPECTION',if(number%20=0,'FAILED','COMPLETED'),if(number%3=0,'OPEN','CLOSED'))),
 if(event_type='INCIDENT',CAST(arrayElement(['NORMAL','WARNING','CRITICAL'],1+(number%3)),'Nullable(LowCardinality(String))'),CAST(NULL,'Nullable(LowCardinality(String))')),
 toFloat32(if(event_type='USAGE',30+(number%150),if(event_type='INSPECTION',20+(number%100),5+(number%240)))),
 toDecimal64(if(event_type='USAGE',10000+(number%9)*5000,0),2),toUInt32(if(event_type='INCIDENT',5+(number%240),0)),
 if(toDate(event_at,'Asia/Seoul')<=toDate('2024-12-31'),'REFERENCE_CALIBRATED',if(toDate(event_at,'Asia/Seoul')<=toDate('2025-12-31'),'SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC')),
 toUInt8(0),toUInt8(1),least(generation_at,event_at+toIntervalMinute(5+(number%180)))
FROM base;
-- 미래 일정은 INSPECTION+SCHEDULED만 1,000건 생성한다.
INSERT INTO hotel_facility.facility_events
SELECT 'SYNTHETIC_HOTEL_001',concat('EVT-',lower(hex(MD5(concat('SYNTHETIC_HOTEL_001|',concat('FAC-',leftPad(toString(1+(number%20)),3,'0')),'|',formatDateTime(toDateTime64('2026-07-29 01:00:00',3,'UTC')+toIntervalHour(number%3700),'%Y-%m-%dT%H:%i:%S','UTC'),'|INSPECTION|1'))))) ,
 concat('FAC-',leftPad(toString(1+(number%20)),3,'0')),CAST(NULL,'Nullable(String)'),
 'INSPECTION',toDateTime64('2026-07-29 01:00:00',3,'UTC')+toIntervalHour(number%3700),
 'SCHEDULED',CAST(NULL,'Nullable(LowCardinality(String))'),toFloat32(60),toDecimal64(0,2),toUInt32(0),
 'FORECAST_SCENARIO',toUInt8(1),toUInt8(1),toDateTime64('2026-07-28 05:00:00',3,'UTC')
FROM numbers(1000);

-- Staffing 11,690건: 1,670일 x 7부서.
INSERT INTO hotel_facility.hotel_staffing_daily
WITH toDate('2022-01-01') start_date
SELECT 'SYNTHETIC_HOTEL_001',concat('STF-',lower(hex(MD5(concat(toString(start_date+toIntervalDay(d.number)),'|',dept))))),
 start_date+toIntervalDay(d.number),dept,toUInt32(15+dept_ord*4+(d.number%3)),
 toFloat32((15+dept_ord*4+(d.number%3))*8),toFloat32((15+dept_ord*4+(d.number%3))*8*(.90+(d.number%9)/100.0)),
 toDecimal64(((15+dept_ord*4+(d.number%3))*8*(.90+(d.number%9)/100.0))*(26000+dept_ord*1500),2),
 toFloat32((15+dept_ord*4+(d.number%3))*(.90+(d.number%9)/100.0)),toUInt32(d.number%3),toUInt32(if(d.number%120=0,1,0)),toUInt32(if(d.number%150=0,1,0)),
 if(start_date+toIntervalDay(d.number)<=toDate('2024-12-31'),'REFERENCE_CALIBRATED',if(start_date+toIntervalDay(d.number)<=toDate('2025-12-31'),'SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC')),
 toUInt8(0),toUInt8(1),least(toDateTime64('2026-07-28 05:00:00',3,'UTC'),toDateTime64(start_date+toIntervalDay(d.number),3,'UTC')+toIntervalHour(23))
FROM numbers(1670) d CROSS JOIN (
 SELECT arrayJoin(['ROOMS','FNB','FACILITY','ENGINEERING','BANQUET','SALES','ADMIN']) dept,
        indexOf(['ROOMS','FNB','FACILITY','ENGINEERING','BANQUET','SALES','ADMIN'],dept) dept_ord
);

-- Resource 6,680건: 1,670일 x 4 scope.
INSERT INTO hotel_facility.facility_resource_daily
WITH toDate('2022-01-01') start_date
SELECT 'SYNTHETIC_HOTEL_001',concat('RES-',lower(hex(MD5(concat(toString(start_date+toIntervalDay(d.number)),'|',scope))))),
 start_date+toIntervalDay(d.number),scope,
 1300+scope_ord*280+(d.number%365)*.7,120+scope_ord*35+(d.number%30)*.6,45+scope_ord*12+(d.number%14)*.5,
 toDecimal64((1300+scope_ord*280+(d.number%365)*.7)*145+(120+scope_ord*35+(d.number%30)*.6)*900,2),
 toFloat32(24),toFloat32((d.number+scope_ord)%8*.25),
 if(start_date+toIntervalDay(d.number)<=toDate('2024-12-31'),'REFERENCE_CALIBRATED',if(start_date+toIntervalDay(d.number)<=toDate('2025-12-31'),'SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC')),
 toUInt8(0),toUInt8(1),least(toDateTime64('2026-07-28 05:00:00',3,'UTC'),toDateTime64(start_date+toIntervalDay(d.number),3,'UTC')+toIntervalHour(23))
FROM numbers(1670) d CROSS JOIN (
 SELECT arrayJoin(['HOTEL','ROOMS','FNB','FACILITY']) scope,
        indexOf(['HOTEL','ROOMS','FNB','FACILITY'],scope) scope_ord
);

-- 필수 검증.
SELECT 'facility_orphan' check_name,count() violation_count FROM hotel_facility.facility_events e LEFT JOIN hotel_facility.facility_master f ON f.property_id=e.property_id AND f.facility_id=e.facility_id WHERE e.property_id='SYNTHETIC_HOTEL_001' AND isNull(f.facility_id)
UNION ALL SELECT 'negative_event_values',count() FROM hotel_facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001' AND (duration_minutes<0 OR amount<0 OR downtime_minutes<0)
UNION ALL SELECT 'future_usage',count() FROM hotel_facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001' AND event_at>toDateTime64('2026-07-28 05:00:00',3,'UTC') AND event_type='USAGE'
UNION ALL SELECT 'future_incident',count() FROM hotel_facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001' AND event_at>toDateTime64('2026-07-28 05:00:00',3,'UTC') AND event_type='INCIDENT'
UNION ALL SELECT 'invalid_future_event',count() FROM hotel_facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001' AND event_at>toDateTime64('2026-07-28 05:00:00',3,'UTC') AND NOT(event_type='INSPECTION' AND event_status='SCHEDULED')
UNION ALL SELECT 'source_update_before_event',count() FROM hotel_facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001' AND event_at<=toDateTime64('2026-07-28 05:00:00',3,'UTC') AND source_updated_at<event_at
UNION ALL SELECT 'future_staffing_actual',count() FROM hotel_facility.hotel_staffing_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND business_date>toDate('2026-07-28')
UNION ALL SELECT 'future_resource_actual',count() FROM hotel_facility.facility_resource_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND business_date>toDate('2026-07-28')
UNION ALL SELECT 'staffing_grain_duplicate',count() FROM (SELECT property_id,business_date,department FROM hotel_facility.hotel_staffing_daily WHERE property_id='SYNTHETIC_HOTEL_001' GROUP BY 1,2,3 HAVING count()>1)
UNION ALL SELECT 'resource_grain_duplicate',count() FROM (SELECT property_id,business_date,resource_scope FROM hotel_facility.facility_resource_daily WHERE property_id='SYNTHETIC_HOTEL_001' GROUP BY 1,2,3 HAVING count()>1)
UNION ALL SELECT 'downtime_over_scheduled',count() FROM hotel_facility.facility_resource_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND downtime_hours>scheduled_hours
UNION ALL SELECT 'vacancy_over_positions',count() FROM hotel_facility.hotel_staffing_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND vacancies>approved_positions
UNION ALL SELECT 'negative_staffing',count() FROM hotel_facility.hotel_staffing_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND (worked_hours<0 OR labor_cost<0)
UNION ALL SELECT 'negative_resource',count() FROM hotel_facility.facility_resource_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND (energy_kwh<0 OR water_m3<0 OR waste_kg<0 OR resource_cost<0)
UNION ALL SELECT 'back_of_house_customer_usage',count() FROM hotel_facility.facility_events e JOIN hotel_facility.facility_master f USING(property_id,facility_id) WHERE e.property_id='SYNTHETIC_HOTEL_001' AND f.facility_type='BACK_OF_HOUSE' AND e.facility_user_ref IS NOT NULL;

SELECT 'pending_delete_mutations' check_name,count() violation_count FROM system.mutations WHERE database='hotel_facility' AND table IN ('facility_master','facility_events','hotel_staffing_daily','facility_resource_daily') AND command LIKE '%SYNTHETIC_HOTEL_001%' AND is_done=0;

SELECT 'parent_child_property_mismatch' check_name,count() violation_count FROM hotel_facility.facility_events e INNER JOIN hotel_facility.facility_master f ON e.facility_id=f.facility_id WHERE e.property_id='SYNTHETIC_HOTEL_001' AND e.property_id<>f.property_id
UNION ALL SELECT 'customer_ref_format',count() FROM hotel_facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001' AND facility_user_ref IS NOT NULL AND NOT match(facility_user_ref,'^FACU-[0-9]{8}$')
UNION ALL SELECT 'forecast_actual_event',count() FROM hotel_facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001' AND is_forecast=1 AND NOT(event_type='INSPECTION' AND event_status='SCHEDULED')
UNION ALL SELECT 'pii_pattern_violation',count() FROM hotel_facility.facility_master WHERE property_id='SYNTHETIC_HOTEL_001' AND match(facility_name,'@|[0-9]{2,3}[- ][0-9]{3,4}[- ][0-9]{4}');

SELECT 'facility_master' table_name,count() row_count,max(source_updated_at) watermark,hex(groupBitXor(cityHash64(facility_id,facility_type,capacity))) checksum FROM hotel_facility.facility_master WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'facility_events',count(),max(source_updated_at),hex(groupBitXor(cityHash64(event_id,facility_id,event_type,event_at))) FROM hotel_facility.facility_events WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'hotel_staffing_daily',count(),max(source_updated_at),hex(groupBitXor(cityHash64(staffing_id,business_date,department))) FROM hotel_facility.hotel_staffing_daily WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'facility_resource_daily',count(),max(source_updated_at),hex(groupBitXor(cityHash64(resource_id,business_date,resource_scope))) FROM hotel_facility.facility_resource_daily WHERE property_id='SYNTHETIC_HOTEL_001';

SELECT 20260728 seed,'schema-v4.6-websql' schema_version,'scenario-v4.6' scenario_version,'source-fixture-v4.6' fixture_version,'DB_EXECUTION_RESULT_ABOVE' execution_status;
