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
-- output=260729_05_banquet_postgresql_2022_2026_v2.3.sql

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
-- 검증 상태: STATIC_REVALIDATED_PASS / DB_EXECUTION_NOT_RUN. 실제 DB 실행 결과는 하단 검증 SELECT로 확인한다.

-- source_id=banquet / engine=PostgreSQL / database=hotel_banquet
-- ingestion_role=banquet_ingest / query_role=banquet_query
-- datahub_platform_instance=hotel_banquet / trino_catalog=banquet
-- output=260728_05_banquet_postgresql_2022_2026_v2.3.sql

\connect hotel_banquet
BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL DateStyle = 'ISO, YMD';
SET LOCAL statement_timeout = '30min';
SET LOCAL lock_timeout = '15s';
SET LOCAL idle_in_transaction_session_timeout = '5min';

DO $contract$
DECLARE missing_count integer;
BEGIN
 SELECT count(*) INTO missing_count FROM (VALUES
 ('banquet_bookings','property_id'),
 ('banquet_bookings','banquet_event_id'),
 ('banquet_bookings','customer_id'),
 ('banquet_bookings','inquiry_at'),
 ('banquet_bookings','quoted_at'),
 ('banquet_bookings','confirmed_at'),
 ('banquet_bookings','cancelled_at'),
 ('banquet_bookings','event_date'),
 ('banquet_bookings','product_code'),
 ('banquet_bookings','product_category'),
 ('banquet_bookings','expected_guests'),
 ('banquet_bookings','actual_attendees'),
 ('banquet_bookings','lead_source'),
 ('banquet_bookings','sales_owner_team'),
 ('banquet_bookings','booking_status'),
 ('banquet_bookings','contracted_amount'),
 ('banquet_bookings','pickup_room_count'),
 ('banquet_bookings','released_room_count'),
 ('banquet_bookings','group_checkout_date'),
 ('banquet_bookings','group_checkin_date'),
 ('banquet_bookings','expected_room_nights'),
 ('banquet_bookings','reserved_room_block_count'),
 ('banquet_bookings','cancellation_fee'),
 ('banquet_bookings','data_period_status'),
 ('banquet_bookings','is_forecast'),
 ('banquet_bookings','is_synthetic'),
 ('banquet_bookings','source_updated_at'),
 ('banquet_revenue','property_id'),
 ('banquet_revenue','revenue_id'),
 ('banquet_revenue','banquet_event_id'),
 ('banquet_revenue','recognized_date'),
 ('banquet_revenue','product_code'),
 ('banquet_revenue','product_category'),
 ('banquet_revenue','revenue_amount'),
 ('banquet_revenue','reversal_amount'),
 ('banquet_revenue','cost_amount'),
 ('banquet_revenue','revenue_status'),
 ('banquet_revenue','data_period_status'),
 ('banquet_revenue','is_forecast'),
 ('banquet_revenue','is_synthetic'),
 ('banquet_revenue','source_updated_at')
 ) r(t,c) WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns x WHERE x.table_schema='public' AND x.table_name=r.t AND x.column_name=r.c);
 IF missing_count>0 THEN RAISE EXCEPTION 'SCHEMA_CONTRACT_MISMATCH: %',missing_count; END IF;
END $contract$;

DO $safety$ BEGIN
 IF EXISTS (SELECT 1 FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=false UNION ALL SELECT 1 FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=false)
 THEN RAISE EXCEPTION 'NON_SYNTHETIC_ROW_PRESENT'; END IF;
END $safety$;

DELETE FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=true;
DELETE FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=true;

-- 6,000 행사 예약.
WITH b AS (
 SELECT n,date '2022-01-01'+((n*53)%1826)::int event_date,
        30+((n*17)%330) lead_days,
        CASE n%5 WHEN 0 THEN 'WEDDING' WHEN 1 THEN 'CONFERENCE' WHEN 2 THEN 'MEETING' WHEN 3 THEN 'CORPORATE_EVENT' ELSE 'SOCIAL_EVENT' END product_category
 FROM generate_series(1,6000)n
), s AS (
 SELECT *,
   CASE WHEN event_date>=date '2026-07-28' THEN CASE WHEN n%10<6 THEN 'CONFIRMED' WHEN n%10<8 THEN 'TENTATIVE' WHEN n%10=8 THEN 'QUOTED' ELSE 'CANCELLED' END
        WHEN n%100<68 THEN 'COMPLETED' WHEN n%100<78 THEN 'CANCELLED' WHEN n%100<88 THEN 'CONFIRMED' WHEN n%100<95 THEN 'QUOTED' ELSE 'TENTATIVE' END booking_status,
   CASE WHEN event_date>date '2026-07-28'
             THEN LEAST((event_date::timestamp - (30+((n*17)%330))*interval '1 day') AT TIME ZONE 'Asia/Seoul',timestamptz '2026-06-01 00:00:00+00')
             ELSE ((event_date::timestamp - (30+((n*17)%330))*interval '1 day') AT TIME ZONE 'Asia/Seoul') END inquiry_at
 FROM b
), t0 AS (
 SELECT *,inquiry_at+interval '2 day' quoted_at,
        CASE WHEN booking_status IN('CONFIRMED','COMPLETED','CANCELLED') THEN inquiry_at+interval '5 day' END confirmed_at,
        CASE WHEN booking_status='CANCELLED' THEN inquiry_at+interval '12 day' END cancelled_at,
        40+(n%460) expected_guests,
        round((6000000+(n%30)*750000)::numeric,2) contracted_amount,
        CASE WHEN n%4=0 THEN 5+(n%25) ELSE 0 END reserved_rooms,
        CASE WHEN n%4=0 THEN n%least((5+(n%25))+1,6) ELSE 0 END released_rooms
 FROM s
), t AS (
 SELECT t0.*,row_number() OVER(PARTITION BY event_date,product_category ORDER BY n) event_sequence_for_day_category
 FROM t0
)
INSERT INTO banquet_bookings(property_id,banquet_event_id,customer_id,inquiry_at,quoted_at,confirmed_at,cancelled_at,event_date,product_code,product_category,expected_guests,actual_attendees,lead_source,sales_owner_team,booking_status,contracted_amount,pickup_room_count,released_room_count,group_checkout_date,group_checkin_date,expected_room_nights,reserved_room_block_count,cancellation_fee,data_period_status,is_forecast,is_synthetic,source_updated_at)
SELECT 'SYNTHETIC_HOTEL_001','BQE-'||md5('SYNTHETIC_HOTEL_001|'||to_char(event_date,'YYYY-MM-DD')||'|'||product_category||'|'||event_sequence_for_day_category::text),'BQC-'||lpad((1+((n-1)%80000))::text,8,'0'),
       inquiry_at,CASE WHEN booking_status<>'INQUIRY' THEN quoted_at END,confirmed_at,cancelled_at,event_date,
       'BQP-'||lpad((1+(n%40))::text,3,'0'),product_category,expected_guests,
       CASE WHEN booking_status='COMPLETED' THEN greatest(1,expected_guests-(n%25)) END,
       CASE n%4 WHEN 0 THEN 'DIRECT' WHEN 1 THEN 'AGENCY' WHEN 2 THEN 'CORPORATE' ELSE 'REFERRAL' END,
       CASE n%3 WHEN 0 THEN 'BANQUET_SALES_A' WHEN 1 THEN 'BANQUET_SALES_B' ELSE 'BANQUET_SALES_C' END,
       booking_status,contracted_amount,
       CASE WHEN booking_status='COMPLETED' THEN greatest(0,reserved_rooms-released_rooms-(n%3)) ELSE 0 END,
       released_rooms,
       CASE WHEN reserved_rooms>0 THEN event_date+2 END,CASE WHEN reserved_rooms>0 THEN event_date-1 END,
       CASE WHEN reserved_rooms>0 THEN reserved_rooms*3 ELSE 0 END,reserved_rooms,
       CASE WHEN booking_status='CANCELLED' THEN round(contracted_amount*CASE WHEN n%3=0 THEN .10 ELSE .05 END,2) ELSE 0 END,
       CASE WHEN event_date<=date '2024-12-31' THEN 'REFERENCE_CALIBRATED' WHEN event_date<=date '2025-12-31' THEN 'SYNTHETIC_ACTUAL_LIKE' WHEN event_date<=date '2026-07-28' THEN 'YTD_SYNTHETIC' ELSE 'FORECAST_SCENARIO' END,
       event_date>date '2026-07-28',true,
       CASE WHEN booking_status='COMPLETED'
            THEN LEAST(timestamptz '2026-07-28 05:00:00+00',(event_date::timestamp+interval '1 day') AT TIME ZONE 'Asia/Seoul')
            ELSE LEAST(timestamptz '2026-07-28 05:00:00+00',GREATEST(inquiry_at,COALESCE(cancelled_at,confirmed_at,quoted_at,inquiry_at))+interval '1 hour') END
FROM t;

-- 완료 행사는 2개 RECOGNIZED line, 미래 확정·잠정은 EXPECTED, 일부 완료 매출은 REVERSED.
WITH completed AS (
 SELECT b.*,x.line_no FROM banquet_bookings b CROSS JOIN (VALUES(1),(2))x(line_no)
 WHERE b.property_id='SYNTHETIC_HOTEL_001' AND b.booking_status='COMPLETED'
), expected AS (
 SELECT b.*,1 line_no FROM banquet_bookings b WHERE b.property_id='SYNTHETIC_HOTEL_001' AND b.event_date>date '2026-07-28' AND b.booking_status IN('CONFIRMED','TENTATIVE')
), lines AS (
 SELECT *, 'RECOGNIZED' revenue_status, event_date recognized_date,
   CASE line_no WHEN 1 THEN 'VENUE' ELSE 'FOOD_BEVERAGE' END revenue_category,
   round(contracted_amount*CASE line_no WHEN 1 THEN .35 ELSE .65 END,2) amount
 FROM completed
 UNION ALL
 SELECT *,'EXPECTED',event_date, 'ACCOMMODATION_PACKAGE',round(contracted_amount*.25,2) FROM expected
)
INSERT INTO banquet_revenue(property_id,revenue_id,banquet_event_id,recognized_date,product_code,product_category,revenue_amount,reversal_amount,cost_amount,revenue_status,data_period_status,is_forecast,is_synthetic,source_updated_at)
SELECT property_id,'REV-'||md5(banquet_event_id||'|'||revenue_status||'|'||line_no),banquet_event_id,recognized_date,
       'REV-'||lpad(line_no::text,2,'0'),revenue_category,amount,0,round(amount*.42,2),revenue_status,data_period_status,is_forecast,true,
       CASE WHEN revenue_status='EXPECTED' THEN timestamptz '2026-07-28 04:30:00+00' ELSE LEAST(timestamptz '2026-07-28 05:00:00+00',(recognized_date::timestamp+interval '23 hour') AT TIME ZONE 'Asia/Seoul') END
FROM lines;

INSERT INTO banquet_revenue(property_id,revenue_id,banquet_event_id,recognized_date,product_code,product_category,revenue_amount,reversal_amount,cost_amount,revenue_status,data_period_status,is_forecast,is_synthetic,source_updated_at)
SELECT b.property_id,'REV-'||md5(b.banquet_event_id||'|REVERSED'),b.banquet_event_id,b.event_date+7,'REV-99','SERVICE',0,round(b.contracted_amount*.10,2),0,'REVERSED',
       CASE WHEN b.event_date+7<=date '2024-12-31' THEN 'REFERENCE_CALIBRATED' WHEN b.event_date+7<=date '2025-12-31' THEN 'SYNTHETIC_ACTUAL_LIKE' ELSE 'YTD_SYNTHETIC' END,false,true,
       LEAST(timestamptz '2026-07-28 05:00:00+00',((b.event_date+7)::timestamp+interval '23 hour') AT TIME ZONE 'Asia/Seoul')
FROM banquet_bookings b WHERE b.property_id='SYNTHETIC_HOTEL_001' AND b.booking_status='COMPLETED' AND b.event_date<=date '2026-07-20' AND mod((hashtextextended(b.banquet_event_id,20260728) & 9223372036854775807),10)<2;
COMMIT;

-- 필수 검증.
SELECT 'inquiry_after_update' check_name,count(*) violation_count FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND inquiry_at>source_updated_at
UNION ALL SELECT 'quoted_after_update',count(*) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND quoted_at>source_updated_at
UNION ALL SELECT 'confirmed_after_update',count(*) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND confirmed_at>source_updated_at
UNION ALL SELECT 'cancelled_after_update',count(*) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND cancelled_at>source_updated_at
UNION ALL SELECT 'future_completed',count(*) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND event_date>date '2026-07-28' AND booking_status='COMPLETED'
UNION ALL SELECT 'future_attendees',count(*) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND event_date>date '2026-07-28' AND actual_attendees IS NOT NULL
UNION ALL SELECT 'future_recognized',count(*) FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001' AND recognized_date>date '2026-07-28' AND revenue_status='RECOGNIZED'
UNION ALL SELECT 'incomplete_recognized',count(*) FROM banquet_revenue r JOIN banquet_bookings b USING(banquet_event_id) WHERE r.property_id='SYNTHETIC_HOTEL_001' AND r.revenue_status='RECOGNIZED' AND b.booking_status<>'COMPLETED'
UNION ALL SELECT 'reversed_with_revenue',count(*) FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001' AND revenue_status='REVERSED' AND revenue_amount>0
UNION ALL SELECT 'reversed_nonpositive',count(*) FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001' AND revenue_status='REVERSED' AND reversal_amount<=0
UNION ALL SELECT 'cancellation_fee_range',count(*) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND (cancellation_fee<0 OR cancellation_fee>contracted_amount)
UNION ALL SELECT 'negative_revenue_values',count(*) FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001' AND (revenue_amount<0 OR reversal_amount<0 OR cost_amount<0)
UNION ALL SELECT 'orphan_revenue',count(*) FROM banquet_revenue r LEFT JOIN banquet_bookings b ON b.property_id=r.property_id AND b.banquet_event_id=r.banquet_event_id WHERE r.property_id='SYNTHETIC_HOTEL_001' AND b.banquet_event_id IS NULL
UNION ALL SELECT 'room_block_violation',count(*) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND (released_room_count>reserved_room_block_count OR pickup_room_count>reserved_room_block_count-released_room_count)
UNION ALL SELECT 'group_date_reverse',count(*) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND group_checkout_date<=group_checkin_date
UNION ALL SELECT 'future_known_not_forecast',count(*) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND event_date>=date '2026-07-29' AND is_forecast=false
UNION ALL SELECT 'expected_room_nights_under_pickup',count(*) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND expected_room_nights<pickup_room_count
UNION ALL SELECT 'parent_child_property_mismatch',count(*) FROM banquet_revenue r JOIN banquet_bookings b ON b.banquet_event_id=r.banquet_event_id WHERE r.property_id='SYNTHETIC_HOTEL_001' AND r.property_id<>b.property_id
UNION ALL SELECT 'noncompleted_actual_revenue',count(*) FROM banquet_revenue r JOIN banquet_bookings b USING(banquet_event_id) WHERE r.property_id='SYNTHETIC_HOTEL_001' AND r.revenue_status IN('RECOGNIZED','REVERSED') AND b.booking_status<>'COMPLETED'
UNION ALL SELECT 'customer_ref_format',count(*) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND customer_id !~ '^BQC-[0-9]{8}$'
UNION ALL SELECT 'pii_pattern_violation',count(*) FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND (sales_owner_team ~* '@|\+?[0-9]{2,3}[- ]?[0-9]{3,4}[- ]?[0-9]{4}');

WITH a AS (
 SELECT banquet_event_id,sum(revenue_amount) FILTER(WHERE revenue_status='RECOGNIZED') recognized,sum(reversal_amount) FILTER(WHERE revenue_status='REVERSED') reversed
 FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001' GROUP BY banquet_event_id
)
SELECT 'reversal_over_recognized' check_name,count(*) violation_count FROM a WHERE reversed>recognized;

SELECT extract(year from event_date)::int yr,data_period_status,is_forecast,booking_status,
       count(*) booking_rows,sum(contracted_amount) contracted_amount,
       sum(reserved_room_block_count) reserved_rooms,sum(pickup_room_count) pickup_rooms
FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001'
GROUP BY 1,2,3,4 ORDER BY 1,3,4;

SELECT extract(year from recognized_date)::int yr,data_period_status,is_forecast,revenue_status,
       count(*) revenue_rows,sum(revenue_amount) gross_amount,sum(reversal_amount) reversal_amount,
       sum(revenue_amount-reversal_amount) net_amount,sum(cost_amount) cost_amount
FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001'
GROUP BY 1,2,3,4 ORDER BY 1,3,4;

SELECT 'banquet_bookings' table_name,count(*) row_count,max(source_updated_at) watermark,
       md5(count(*)||'|'||min(banquet_event_id)||'|'||max(banquet_event_id)||'|'||sum(hashtext(banquet_event_id))::text) checksum
FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'banquet_revenue',count(*),max(source_updated_at),md5(count(*)||'|'||min(revenue_id)||'|'||max(revenue_id)||'|'||sum(hashtext(revenue_id))::text) FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001';

SELECT 'seed=20260728' seed,'schema-v4.6-websql' schema_version,'scenario-v4.6' scenario_version,'source-fixture-v4.6' fixture_version,'DB_EXECUTION_RESULT_ABOVE' execution_status;
