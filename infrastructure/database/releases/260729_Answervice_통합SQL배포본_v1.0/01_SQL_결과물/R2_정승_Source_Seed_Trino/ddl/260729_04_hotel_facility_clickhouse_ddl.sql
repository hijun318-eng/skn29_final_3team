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
-- work_card=R2-DB
-- output=260729_04_hotel_facility_clickhouse_ddl.sql

-- ============================================================================
-- 260729_04_hotel_facility_clickhouse_ddl.sql
-- Answervice Facility schema contract v4.6
-- ClickHouse 24+ / clickhouse-client
-- source_id=facility
-- engine=ClickHouse
-- database/schema=hotel_facility/hotel_facility
-- ingestion_role=facility_ingest
-- query_role=facility_query
-- datahub_platform_instance=hotel_facility
-- trino_catalog=facility
-- schema_version=schema-v4.6-websql
-- ============================================================================
SET session_timezone = 'UTC';
SET max_execution_time = 1800;

CREATE DATABASE IF NOT EXISTS hotel_facility;
USE hotel_facility;

SELECT throwIf(
  (SELECT count() FROM system.tables WHERE database='hotel_facility' AND name='facility_master')=1
  AND
  (SELECT groupArray((name,type))
     FROM (SELECT name,type FROM system.columns
           WHERE database='hotel_facility' AND table='facility_master'
           ORDER BY position)) != [('property_id','String'), ('facility_id','String'), ('facility_name','String'), ('facility_type','LowCardinality(String)'), ('owner_team','LowCardinality(String)'), ('capacity','UInt32'), ('open_hour','UInt8'), ('close_hour','UInt8'), ('is_active','UInt8'), ('is_synthetic','UInt8'), ('source_updated_at','DateTime64(3,'UTC')')],
  'SCHEMA_CONTRACT_MISMATCH: hotel_facility.facility_master'
);

CREATE TABLE IF NOT EXISTS hotel_facility.`facility_master` (
    `property_id` String COMMENT '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]',
    `facility_id` String COMMENT '시설 ID. 논리 PK [classification=SYNTHETIC]',
    `facility_name` String COMMENT '합성 시설명.  [classification=SYNTHETIC]',
    `facility_type` LowCardinality(String) COMMENT '시설 유형. SPA/POOL/FITNESS/ACTIVITY/MEETING_SUPPORT/BACK_OF_HOUSE [classification=SYNTHETIC]',
    `owner_team` LowCardinality(String) COMMENT '담당 조직.  [classification=SYNTHETIC]',
    `capacity` UInt32 COMMENT '수용 인원.  [classification=SYNTHETIC]',
    `open_hour` UInt8 COMMENT '운영 시작 시.  [classification=SYNTHETIC]',
    `close_hour` UInt8 COMMENT '운영 종료 시.  [classification=SYNTHETIC]',
    `is_active` UInt8 COMMENT '활성 여부.  [classification=SYNTHETIC]',
    `is_synthetic` UInt8 COMMENT '합성 여부. 항상 1 [classification=POLICY]',
    `source_updated_at` DateTime64(3,'UTC') COMMENT '원천 수정시각. watermark [classification=SYNTHETIC]',
    CONSTRAINT ck_facility_master_1 CHECK capacity >= 0,
    CONSTRAINT ck_facility_master_2 CHECK open_hour <= 23,
    CONSTRAINT ck_facility_master_3 CHECK close_hour <= 23,
    CONSTRAINT ck_facility_master_4 CHECK is_active IN (0,1),
    CONSTRAINT ck_facility_master_5 CHECK is_synthetic=1,
    CONSTRAINT ck_facility_master_6 CHECK facility_type IN ('SPA','POOL','FITNESS','ACTIVITY','MEETING_SUPPORT','BACK_OF_HOUSE')
)
ENGINE = MergeTree
PRIMARY KEY (property_id, facility_id)
ORDER BY (property_id, facility_id)
COMMENT '합성 시설 1건';

SELECT throwIf(
  (SELECT count() FROM system.tables WHERE database='hotel_facility' AND name='facility_events')=1
  AND
  (SELECT groupArray((name,type))
     FROM (SELECT name,type FROM system.columns
           WHERE database='hotel_facility' AND table='facility_events'
           ORDER BY position)) != [('property_id','String'), ('event_id','String'), ('facility_id','String'), ('facility_user_ref','Nullable(String)'), ('event_type','LowCardinality(String)'), ('event_at','DateTime64(3,'UTC')'), ('event_status','LowCardinality(String)'), ('severity','Nullable(LowCardinality(String))'), ('duration_minutes','Float32'), ('amount','Decimal(14,2)'), ('downtime_minutes','UInt32'), ('data_period_status','LowCardinality(String)'), ('is_forecast','UInt8'), ('is_synthetic','UInt8'), ('source_updated_at','DateTime64(3,'UTC')')],
  'SCHEMA_CONTRACT_MISMATCH: hotel_facility.facility_events'
);

CREATE TABLE IF NOT EXISTS hotel_facility.`facility_events` (
    `property_id` String COMMENT '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]',
    `event_id` String COMMENT '이벤트 ID. 논리 PK [classification=SYNTHETIC]',
    `facility_id` String COMMENT '시설 ID. ClickHouse 논리 참조 [classification=SYNTHETIC]',
    `facility_user_ref` Nullable(String) COMMENT '시설 고객 참조.  [classification=SYNTHETIC]',
    `event_type` LowCardinality(String) COMMENT '이벤트 유형. USAGE/INSPECTION/INCIDENT [classification=SYNTHETIC]',
    `event_at` DateTime64(3,'UTC') COMMENT '발생 시각.  [classification=SYNTHETIC]',
    `event_status` LowCardinality(String) COMMENT '상태. RESERVED/COMPLETED/FAILED/SCHEDULED/OPEN/CLOSED [classification=SYNTHETIC]',
    `severity` Nullable(LowCardinality(String)) COMMENT '심각도. NORMAL/WARNING/CRITICAL [classification=SYNTHETIC]',
    `duration_minutes` Float32 COMMENT '소요 시간. 0 이상 [classification=SYNTHETIC]',
    `amount` Decimal(14,2) COMMENT '시설 매출. USAGE 외 0 가능 [classification=SYNTHETIC]',
    `downtime_minutes` UInt32 COMMENT '운영 중단 분. INCIDENT 중심 [classification=SYNTHETIC]',
    `data_period_status` LowCardinality(String) COMMENT '기간 상태. 4개 고정 상태 [classification=POLICY]',
    `is_forecast` UInt8 COMMENT '전망 여부. 2026-07 이후 1 [classification=POLICY]',
    `is_synthetic` UInt8 COMMENT '합성 여부. 항상 1 [classification=POLICY]',
    `source_updated_at` DateTime64(3,'UTC') COMMENT '원천 수정시각. watermark [classification=SYNTHETIC]',
    CONSTRAINT ck_facility_events_1 CHECK event_type IN ('USAGE','INSPECTION','INCIDENT'),
    CONSTRAINT ck_facility_events_2 CHECK event_status IN ('RESERVED','COMPLETED','FAILED','SCHEDULED','OPEN','CLOSED'),
    CONSTRAINT ck_facility_events_3 CHECK severity IS NULL OR severity IN ('NORMAL','WARNING','CRITICAL'),
    CONSTRAINT ck_facility_events_4 CHECK duration_minutes >= 0,
    CONSTRAINT ck_facility_events_5 CHECK amount >= 0,
    CONSTRAINT ck_facility_events_6 CHECK is_forecast IN (0,1),
    CONSTRAINT ck_facility_events_7 CHECK is_synthetic=1,
    CONSTRAINT ck_facility_events_8 CHECK facility_user_ref IS NULL OR event_type='USAGE',
    CONSTRAINT ck_facility_events_9 CHECK (event_type='USAGE' AND event_status IN ('RESERVED','COMPLETED','FAILED')) OR (event_type='INSPECTION' AND event_status IN ('SCHEDULED','COMPLETED','FAILED')) OR (event_type='INCIDENT' AND event_status IN ('OPEN','CLOSED')),
    CONSTRAINT ck_facility_events_10 CHECK data_period_status IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO'),
    CONSTRAINT ck_facility_events_11 CHECK is_forecast = (data_period_status='FORECAST_SCENARIO'),
    CONSTRAINT ck_facility_events_12 CHECK (toDate(event_at,'Asia/Seoul') BETWEEN toDate('2022-01-01') AND toDate('2024-12-31') AND data_period_status='REFERENCE_CALIBRATED') OR (toDate(event_at,'Asia/Seoul') BETWEEN toDate('2025-01-01') AND toDate('2025-12-31') AND data_period_status='SYNTHETIC_ACTUAL_LIKE') OR (toDate(event_at,'Asia/Seoul') BETWEEN toDate('2026-01-01') AND toDate('2026-07-28') AND data_period_status='YTD_SYNTHETIC') OR (toDate(event_at,'Asia/Seoul') BETWEEN toDate('2026-07-29') AND toDate('2026-12-31') AND data_period_status='FORECAST_SCENARIO'),
    CONSTRAINT ck_facility_events_13 CHECK (event_at <= toDateTime64('2026-07-28 05:00:00',3,'UTC')) OR (event_type='INSPECTION' AND event_status='SCHEDULED' AND is_forecast=1),
    CONSTRAINT ck_facility_events_14 CHECK source_updated_at >= least(event_at,toDateTime64('2026-07-28 05:00:00',3,'UTC'))
)
ENGINE = MergeTree
PRIMARY KEY (property_id, facility_id, event_at, event_id)
ORDER BY (property_id, facility_id, event_at, event_id)
COMMENT '시설 이용·점검·장애 이벤트 1건';

SELECT throwIf(
  (SELECT count() FROM system.tables WHERE database='hotel_facility' AND name='hotel_staffing_daily')=1
  AND
  (SELECT groupArray((name,type))
     FROM (SELECT name,type FROM system.columns
           WHERE database='hotel_facility' AND table='hotel_staffing_daily'
           ORDER BY position)) != [('property_id','String'), ('staffing_id','String'), ('business_date','Date'), ('department','LowCardinality(String)'), ('approved_positions','UInt32'), ('scheduled_hours','Float32'), ('worked_hours','Float32'), ('labor_cost','Decimal(14,2)'), ('fte','Float32'), ('vacancies','UInt32'), ('new_hires','UInt32'), ('separations','UInt32'), ('data_period_status','LowCardinality(String)'), ('is_forecast','UInt8'), ('is_synthetic','UInt8'), ('source_updated_at','DateTime64(3,'UTC')')],
  'SCHEMA_CONTRACT_MISMATCH: hotel_facility.hotel_staffing_daily'
);

CREATE TABLE IF NOT EXISTS hotel_facility.`hotel_staffing_daily` (
    `property_id` String COMMENT '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]',
    `staffing_id` String COMMENT '인력 일별 ID. 논리 PK [classification=SYNTHETIC]',
    `business_date` Date COMMENT '영업일자.  [classification=SYNTHETIC]',
    `department` LowCardinality(String) COMMENT '부서. ROOMS/FNB/FACILITY/ENGINEERING/BANQUET/SALES/ADMIN [classification=SYNTHETIC]',
    `approved_positions` UInt32 COMMENT '승인 정원.  [classification=SYNTHETIC]',
    `scheduled_hours` Float32 COMMENT '계획 근무시간.  [classification=SYNTHETIC]',
    `worked_hours` Float32 COMMENT '실제 근무시간.  [classification=SYNTHETIC]',
    `labor_cost` Decimal(14,2) COMMENT '인건비. KRW 합성값 [classification=SYNTHETIC]',
    `fte` Float32 COMMENT 'FTE.  [classification=SYNTHETIC]',
    `vacancies` UInt32 COMMENT '공석 수.  [classification=SYNTHETIC]',
    `new_hires` UInt32 COMMENT '신규 입사.  [classification=SYNTHETIC]',
    `separations` UInt32 COMMENT '퇴사.  [classification=SYNTHETIC]',
    `data_period_status` LowCardinality(String) COMMENT '기간 상태. 4개 고정 상태 [classification=POLICY]',
    `is_forecast` UInt8 COMMENT '전망 여부. 2026-07 이후 1 [classification=POLICY]',
    `is_synthetic` UInt8 COMMENT '합성 여부. 항상 1 [classification=POLICY]',
    `source_updated_at` DateTime64(3,'UTC') COMMENT '원천 수정시각. watermark [classification=SYNTHETIC]',
    CONSTRAINT ck_hotel_staffing_daily_1 CHECK approved_positions >= 0,
    CONSTRAINT ck_hotel_staffing_daily_2 CHECK scheduled_hours >= 0,
    CONSTRAINT ck_hotel_staffing_daily_3 CHECK worked_hours >= 0,
    CONSTRAINT ck_hotel_staffing_daily_4 CHECK labor_cost >= 0,
    CONSTRAINT ck_hotel_staffing_daily_5 CHECK fte >= 0,
    CONSTRAINT ck_hotel_staffing_daily_6 CHECK vacancies <= approved_positions,
    CONSTRAINT ck_hotel_staffing_daily_7 CHECK is_forecast IN (0,1),
    CONSTRAINT ck_hotel_staffing_daily_8 CHECK is_synthetic=1,
    CONSTRAINT ck_hotel_staffing_daily_9 CHECK department IN ('ROOMS','FNB','FACILITY','ENGINEERING','BANQUET','SALES','ADMIN'),
    CONSTRAINT ck_hotel_staffing_daily_10 CHECK data_period_status IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO'),
    CONSTRAINT ck_hotel_staffing_daily_11 CHECK is_forecast = (data_period_status='FORECAST_SCENARIO'),
    CONSTRAINT ck_hotel_staffing_daily_12 CHECK (business_date <= toDate('2026-07-28')) OR (is_forecast=1)
)
ENGINE = MergeTree
PRIMARY KEY (property_id, business_date, department)
ORDER BY (property_id, business_date, department)
COMMENT '부서·영업일자별 근무·인건비·인력 상태 1건';

SELECT throwIf(
  (SELECT count() FROM system.tables WHERE database='hotel_facility' AND name='facility_resource_daily')=1
  AND
  (SELECT groupArray((name,type))
     FROM (SELECT name,type FROM system.columns
           WHERE database='hotel_facility' AND table='facility_resource_daily'
           ORDER BY position)) != [('property_id','String'), ('resource_id','String'), ('business_date','Date'), ('resource_scope','LowCardinality(String)'), ('energy_kwh','Float64'), ('water_m3','Float64'), ('waste_kg','Float64'), ('resource_cost','Decimal(14,2)'), ('scheduled_hours','Float32'), ('downtime_hours','Float32'), ('data_period_status','LowCardinality(String)'), ('is_forecast','UInt8'), ('is_synthetic','UInt8'), ('source_updated_at','DateTime64(3,'UTC')')],
  'SCHEMA_CONTRACT_MISMATCH: hotel_facility.facility_resource_daily'
);

CREATE TABLE IF NOT EXISTS hotel_facility.`facility_resource_daily` (
    `property_id` String COMMENT '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]',
    `resource_id` String COMMENT '자원 일별 ID. 논리 PK [classification=SYNTHETIC]',
    `business_date` Date COMMENT '영업일자.  [classification=SYNTHETIC]',
    `resource_scope` LowCardinality(String) COMMENT '자원 범위. HOTEL/ROOMS/FNB/FACILITY 등 [classification=SYNTHETIC]',
    `energy_kwh` Float64 COMMENT '에너지 사용량. 0 이상 [classification=SYNTHETIC]',
    `water_m3` Float64 COMMENT '수도 사용량. 0 이상 [classification=SYNTHETIC]',
    `waste_kg` Float64 COMMENT '폐기물. 0 이상 [classification=SYNTHETIC]',
    `resource_cost` Decimal(14,2) COMMENT '자원 비용. KRW 합성값 [classification=SYNTHETIC]',
    `scheduled_hours` Float32 COMMENT '계획 운영시간.  [classification=SYNTHETIC]',
    `downtime_hours` Float32 COMMENT '중단 시간.  [classification=SYNTHETIC]',
    `data_period_status` LowCardinality(String) COMMENT '기간 상태. 4개 고정 상태 [classification=POLICY]',
    `is_forecast` UInt8 COMMENT '전망 여부. 2026-07 이후 1 [classification=POLICY]',
    `is_synthetic` UInt8 COMMENT '합성 여부. 항상 1 [classification=POLICY]',
    `source_updated_at` DateTime64(3,'UTC') COMMENT '원천 수정시각. watermark [classification=SYNTHETIC]',
    CONSTRAINT ck_facility_resource_daily_1 CHECK energy_kwh >= 0,
    CONSTRAINT ck_facility_resource_daily_2 CHECK water_m3 >= 0,
    CONSTRAINT ck_facility_resource_daily_3 CHECK waste_kg >= 0,
    CONSTRAINT ck_facility_resource_daily_4 CHECK resource_cost >= 0,
    CONSTRAINT ck_facility_resource_daily_5 CHECK scheduled_hours >= 0,
    CONSTRAINT ck_facility_resource_daily_6 CHECK downtime_hours >= 0,
    CONSTRAINT ck_facility_resource_daily_7 CHECK downtime_hours <= scheduled_hours,
    CONSTRAINT ck_facility_resource_daily_8 CHECK is_forecast IN (0,1),
    CONSTRAINT ck_facility_resource_daily_9 CHECK is_synthetic=1,
    CONSTRAINT ck_facility_resource_daily_10 CHECK data_period_status IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO'),
    CONSTRAINT ck_facility_resource_daily_11 CHECK is_forecast = (data_period_status='FORECAST_SCENARIO'),
    CONSTRAINT ck_facility_resource_daily_12 CHECK (business_date <= toDate('2026-07-28')) OR (is_forecast=1)
)
ENGINE = MergeTree
PRIMARY KEY (property_id, business_date, resource_scope)
ORDER BY (property_id, business_date, resource_scope)
COMMENT '자원 범위·영업일자별 에너지·수도·폐기물 1건';

CREATE ROLE IF NOT EXISTS facility_ingest;
CREATE ROLE IF NOT EXISTS facility_query;
GRANT SELECT, INSERT, ALTER DELETE ON hotel_facility.* TO facility_ingest;
GRANT SELECT ON hotel_facility.* TO facility_query;

-- Read-only negative tests. facility_query만 활성화한 별도 시험 세션에서 실행한다.
-- SET ROLE facility_query;
-- INSERT INTO hotel_facility.facility_master VALUES (...);
-- ALTER TABLE hotel_facility.facility_master DELETE WHERE 0;
-- ALTER TABLE hotel_facility.facility_master ADD COLUMN __negative_test UInt8;
-- 예상 결과: INSERT 및 ALTER 계열 권한 거부.

-- 구조 검증
SELECT count() AS source_table_count,
       if(count()=4,'PASS','SCHEMA_CONTRACT_MISMATCH') AS status
FROM system.tables
WHERE database='hotel_facility'
  AND name IN ('facility_master','facility_events','hotel_staffing_daily','facility_resource_daily');

SELECT count() AS source_column_count,
       if(count()=56,'PASS','SCHEMA_CONTRACT_MISMATCH') AS status
FROM system.columns
WHERE database='hotel_facility'
  AND table IN ('facility_master','facility_events','hotel_staffing_daily','facility_resource_daily');

-- ClickHouse 논리 관계 검증
SELECT count() AS facility_event_orphan_count
FROM hotel_facility.facility_events e
LEFT JOIN hotel_facility.facility_master m
  ON m.property_id=e.property_id AND m.facility_id=e.facility_id
WHERE m.facility_id IS NULL;

SELECT property_id,event_id,count() AS duplicate_count
FROM hotel_facility.facility_events
GROUP BY property_id,event_id
HAVING count()>1;

SELECT property_id,business_date,department,count() AS duplicate_count
FROM hotel_facility.hotel_staffing_daily
GROUP BY property_id,business_date,department
HAVING count()>1;

SELECT property_id,business_date,resource_scope,count() AS duplicate_count
FROM hotel_facility.facility_resource_daily
GROUP BY property_id,business_date,resource_scope
HAVING count()>1;

SELECT count() AS invalid_future_actual_event_count
FROM hotel_facility.facility_events
WHERE event_at > toDateTime64('2026-07-28 05:00:00',3,'UTC')
  AND NOT (event_type='INSPECTION' AND event_status='SCHEDULED' AND is_forecast=1);

SELECT 'facility' AS source_id, 'ClickHouse' AS engine,
       'hotel_facility/hotel_facility' AS database_schema,
       'facility_ingest' AS ingestion_role, 'facility_query' AS query_role,
       'hotel_facility' AS datahub_platform_instance, 'facility' AS trino_catalog,
       'schema-v4.6-websql' AS schema_version;
