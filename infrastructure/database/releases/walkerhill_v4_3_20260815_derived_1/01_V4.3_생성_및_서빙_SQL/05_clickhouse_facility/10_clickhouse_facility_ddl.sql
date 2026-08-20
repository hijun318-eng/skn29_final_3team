-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=ClickHouse 24.8+; domain=FACILITY; script_type=DDL; execution_order=10
-- dependency=00_clickhouse_facility_preflight_readonly.sql; expected_rows=0
-- execution_default=NOT_RUN; destructive_operation=false

CREATE DATABASE walkerhill_v4_3 COMMENT '워커힐 공개 기준정보를 바탕으로 만든 비공식 교육용 V4.3 시설 합성 데이터 격리 영역';

CREATE TABLE walkerhill_v4_3.facility_master
(
 facility_id String COMMENT '시설을 유일하게 식별하는 합성 코드',
 facility_name String COMMENT '공개 명칭 또는 합성 모델에서 부여한 시설 표시명',
 facility_type LowCardinality(String) COMMENT 'GOLF·POOL·FITNESS·WELLNESS·GUEST_SERVICE·EVENT_SUPPORT 중 시설 유형',
 hotel_code LowCardinality(String) COMMENT 'GRAND·VISTA·DOUGLAS 또는 CAMPUS 공용 운영 범위',
 reporting_hotel_code LowCardinality(String) COMMENT '공용 시설을 일관된 호텔 KPI에 배분하는 GRAND·VISTA·DOUGLAS 보고 귀속 코드',
 effective_from Date COMMENT '시설이 합성 운영 모델에 포함되기 시작한 날짜',
 capacity UInt32 COMMENT '동시 이용 가능 인원에 대한 합성 상한값',
 open_minute UInt16 COMMENT '영업일 00:00부터 합성 시설 운영 시작까지의 분',
 close_minute UInt16 COMMENT '영업일 00:00부터 합성 시설 운영 종료까지의 분. 현 버전은 자정 넘김 없음',
 closed_iso_weekday UInt8 COMMENT '0은 정기 휴무 없음, 1~7은 ISO 요일 합성 정기 휴무일',
 source_url String COMMENT '명칭이나 개장일의 공개 근거 URL. 순수 가정은 대표 브랜드 URL',
 provenance_class LowCardinality(String) COMMENT 'OFFICIAL_FACT·OFFICIAL_NAME_SYNTHETIC_RULE·SYNTHETIC_ASSUMPTION 중 출처 등급',
 is_synthetic UInt8 COMMENT '실제 운영 레코드가 아닌 합성 데이터임을 나타내며 항상 1'
)
ENGINE=MergeTree ORDER BY facility_id
COMMENT '시설별 이용·사고·자원 지표의 기준이 되는 합성 시설 마스터';

CREATE TABLE walkerhill_v4_3.facility_usage_events
(
 usage_event_id String COMMENT '시설 이용 이벤트의 결정적 합성 식별자',
 facility_id String COMMENT '이용한 시설 코드. facility_master와 논리적으로 연결',
 event_time DateTime('Asia/Seoul') COMMENT '시설 이용이 시작된 한국 표준시 시각',
 usage_type LowCardinality(String) COMMENT 'ENTRY·SESSION·RENTAL·PROGRAM 중 이용 행위 유형',
 user_ref Nullable(String) COMMENT '개인정보가 아닌 교차 도메인용 합성 사용자 참조값',
 party_size UInt16 COMMENT '해당 이용 이벤트에 포함된 합성 인원 수',
 duration_minutes UInt16 COMMENT '시설 이용 지속 시간(분)',
 gross_amount Decimal(18,2) COMMENT '유료 이용인 경우의 부가세 포함 합성 총액. 무료 이용은 0',
 event_id Nullable(String) COMMENT '공개 행사 또는 대형 이벤트 영향권에 포함된 경우의 합성 이벤트 코드',
 is_synthetic UInt8 COMMENT '실제 이용 로그가 아닌 합성 행임을 나타내며 항상 1'
)
ENGINE=MergeTree PARTITION BY toYYYYMM(event_time) ORDER BY (facility_id,event_time,usage_event_id)
COMMENT '시설별 시간대·계절·이벤트 영향을 재현한 합성 이용 이벤트';

CREATE TABLE walkerhill_v4_3.facility_incidents
(
 incident_id String COMMENT '시설 사고·불편 접수 행의 결정적 합성 식별자',
 facility_id String COMMENT '사고가 발생한 시설 코드',
 opened_at DateTime('Asia/Seoul') COMMENT '사고 또는 불편이 최초 접수된 한국 표준시 시각',
 closed_at Nullable(DateTime('Asia/Seoul')) COMMENT '조치 완료 시각. 미해결 상태는 NULL',
 severity LowCardinality(String) COMMENT 'LOW·MEDIUM·HIGH 중 운영 영향 심각도',
 incident_type LowCardinality(String) COMMENT 'EQUIPMENT·SAFETY·CLEANLINESS·CAPACITY·WEATHER 중 원인 유형',
 impact_minutes UInt32 COMMENT '시설 운영 또는 고객 경험에 영향을 준 합성 시간(분)',
 guest_impact_count UInt32 COMMENT '해당 사고로 직접 영향을 받은 합성 고객 수',
 resolution_status LowCardinality(String) COMMENT 'RESOLVED·MONITORING·OPEN 중 종료 시점의 조치 상태',
 is_synthetic UInt8 COMMENT '실제 사고 기록이 아닌 합성 행임을 나타내며 항상 1'
)
ENGINE=MergeTree PARTITION BY toYYYYMM(opened_at) ORDER BY (facility_id,opened_at,incident_id)
COMMENT '시설 신뢰성과 운영 중단을 분석하기 위한 합성 사고·불편 이력';

CREATE TABLE walkerhill_v4_3.hotel_staffing_daily
(
 business_date Date COMMENT '인력 배치가 귀속되는 호텔 영업일',
 hotel_code LowCardinality(String) COMMENT 'GRAND·VISTA·DOUGLAS 중 인력이 배치된 호텔',
 department LowCardinality(String) COMMENT 'FRONT·HOUSEKEEPING·FNB·FACILITY·SECURITY 중 운영 부서',
 shift_code LowCardinality(String) COMMENT 'DAY·EVENING·NIGHT 중 근무조',
 planned_hours Decimal(12,2) COMMENT '점유·이벤트 수요를 반영한 합성 계획 근로시간',
 actual_hours Decimal(12,2) COMMENT '결근·초과근무 변동을 반영한 합성 실제 근로시간',
 guest_facing_fte Decimal(10,2) COMMENT '실제 근로시간을 8시간 기준으로 환산한 고객 접점 인력 수',
 overtime_hours Decimal(10,2) COMMENT '계획 근로시간을 초과한 합성 근로시간',
 event_load_index Decimal(8,4) COMMENT '해당 날짜의 대형 행사·성수기 인력 부하 지수. 평시 기준은 약 1',
 is_synthetic UInt8 COMMENT '실제 인사자료가 아닌 합성 집계 행임을 나타내며 항상 1'
)
ENGINE=MergeTree PARTITION BY toYYYYMM(business_date) ORDER BY (hotel_code,business_date,department,shift_code)
COMMENT '호텔·영업일·부서·근무조 단위의 합성 인력 계획 및 실적';

CREATE TABLE walkerhill_v4_3.facility_resource_daily
(
 business_date Date COMMENT '자원 사용량이 귀속되는 호텔 영업일',
 facility_id String COMMENT '자원을 소비한 시설 코드',
 energy_kwh Decimal(16,3) COMMENT '계절·이용량을 반영한 합성 전력 사용량(kWh)',
 water_m3 Decimal(16,3) COMMENT '시설 유형·이용량을 반영한 합성 용수 사용량(m³)',
 waste_kg Decimal(16,3) COMMENT '고객 활동량을 반영한 합성 폐기물 발생량(kg)',
 occupied_room_equivalent Decimal(12,3) COMMENT '자원 모델에 사용한 객실 점유 환산 수요. 실제 객실 점유값이 아님',
 weather_index Decimal(8,4) COMMENT '계절 온도·강수 효과를 압축한 합성 기상 부하 지수',
 is_synthetic UInt8 COMMENT '실제 계량기 자료가 아닌 합성 집계 행임을 나타내며 항상 1'
)
ENGINE=MergeTree PARTITION BY toYYYYMM(business_date) ORDER BY (facility_id,business_date)
COMMENT '시설·영업일 단위의 전력·용수·폐기물 합성 사용량';
