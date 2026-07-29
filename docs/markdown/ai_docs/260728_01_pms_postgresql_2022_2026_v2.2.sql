-- 호텔 데이터허브 합성 Source 데이터 적재 SQL
-- seed=20260728
-- schema_version=schema-v4.6-websql
-- scenario_version=scenario-v4.6
-- fixture_version=source-fixture-v4.6
-- property_id=SYNTHETIC_HOTEL_001
-- synthetic=true
-- generated_at=2026-07-28T05:00:00Z
-- simulation_as_of_date=2026-07-28
-- evaluation_as_of=2026-07-28T00:00:00+09:00
-- storage_timezone=UTC / business_timezone=Asia/Seoul
-- 주의: 이 파일은 DDL을 생성하지 않는다. v4.6 DDL이 먼저 적용되어 있어야 한다.
-- 검증 상태: STATIC_REVALIDATED_PASS / DB_EXECUTION_NOT_RUN. 실제 DB 실행 결과는 하단 검증 SELECT로 확인한다.

-- source_id=pms / engine=PostgreSQL / database=hotel_pms
-- ingestion_role=pms_ingest / query_role=pms_query
-- datahub_platform_instance=hotel_pms / trino_catalog=pms
-- output=260728_01_pms_postgresql_2022_2026_v2.2.sql

\connect hotel_pms

BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL DateStyle = 'ISO, YMD';
SET LOCAL statement_timeout = '30min';
SET LOCAL lock_timeout = '15s';
SET LOCAL idle_in_transaction_session_timeout = '5min';

-- 1. 스키마 계약 사전검증. 누락 컬럼이 있으면 임의 우회하지 않는다.
DO $contract$
DECLARE
  missing_count integer;
BEGIN
  SELECT count(*) INTO missing_count
  FROM (VALUES
    ('pms_guests','property_id'),('pms_guests','guest_id'),('pms_guests','guest_segment'),
    ('pms_guests','country_group'),('pms_guests','crm_mapping_eligible'),('pms_guests','created_at'),
    ('pms_guests','source_updated_at'),('pms_guests','is_synthetic'),
    ('pms_room_inventory_daily','property_id'),('pms_room_inventory_daily','inventory_id'),
    ('pms_room_inventory_daily','business_date'),('pms_room_inventory_daily','room_type_code'),
    ('pms_room_inventory_daily','physical_rooms'),('pms_room_inventory_daily','out_of_order_rooms'),
    ('pms_room_inventory_daily','house_use_rooms'),('pms_room_inventory_daily','available_room_nights'),
    ('pms_room_inventory_daily','data_period_status'),('pms_room_inventory_daily','is_forecast'),
    ('pms_room_inventory_daily','is_synthetic'),('pms_room_inventory_daily','source_updated_at'),
    ('pms_reservations','property_id'),('pms_reservations','reservation_id'),('pms_reservations','guest_id'),
    ('pms_reservations','booked_at'),('pms_reservations','checkin_date'),('pms_reservations','checkout_date'),
    ('pms_reservations','room_type_code'),('pms_reservations','rate_plan_code'),
    ('pms_reservations','market_segment'),('pms_reservations','booking_channel'),
    ('pms_reservations','reservation_status'),('pms_reservations','cancelled_at'),
    ('pms_reservations','cancellation_reason_code'),('pms_reservations','adult_count'),
    ('pms_reservations','child_count'),('pms_reservations','quoted_room_rate'),
    ('pms_reservations','gross_room_amount'),('pms_reservations','discount_amount'),
    ('pms_reservations','commission_amount'),('pms_reservations','booked_amount'),
    ('pms_reservations','refund_amount'),('pms_reservations','cancellation_fee'),
    ('pms_reservations','data_period_status'),('pms_reservations','is_forecast'),
    ('pms_reservations','is_synthetic'),('pms_reservations','source_updated_at'),
    ('pms_stays','property_id'),('pms_stays','stay_id'),('pms_stays','reservation_id'),
    ('pms_stays','guest_id'),('pms_stays','room_unit_code'),('pms_stays','actual_checkin_at'),
    ('pms_stays','actual_checkout_at'),('pms_stays','room_type_code'),
    ('pms_stays','occupied_room_nights'),('pms_stays','guest_count'),
    ('pms_stays','complimentary_flag'),('pms_stays','house_use_flag'),
    ('pms_stays','room_revenue'),('pms_stays','other_room_charges'),('pms_stays','stay_status'),
    ('pms_stays','data_period_status'),('pms_stays','is_forecast'),
    ('pms_stays','is_synthetic'),('pms_stays','source_updated_at')
  ) AS required(table_name,column_name)
  WHERE NOT EXISTS (
    SELECT 1 FROM information_schema.columns c
    WHERE c.table_schema='public' AND c.table_name=required.table_name AND c.column_name=required.column_name
  );
  IF missing_count > 0 THEN
    RAISE EXCEPTION 'SCHEMA_CONTRACT_MISMATCH: missing % required PMS columns', missing_count;
  END IF;
  IF to_regclass('public.pms_stays_actual') IS NULL THEN
    RAISE EXCEPTION 'SCHEMA_CONTRACT_MISMATCH: public.pms_stays_actual view missing';
  END IF;
END
$contract$;

-- 2. 비합성 행 보호 및 멱등 재실행 정리.
DO $safety$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pms_guests WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=false
    UNION ALL SELECT 1 FROM pms_room_inventory_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=false
    UNION ALL SELECT 1 FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=false
    UNION ALL SELECT 1 FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=false
  ) THEN
    RAISE EXCEPTION 'NON_SYNTHETIC_ROW_PRESENT';
  END IF;
END
$safety$;

DELETE FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=true;
DELETE FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=true;
DELETE FROM pms_room_inventory_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=true;
DELETE FROM pms_guests WHERE property_id='SYNTHETIC_HOTEL_001' AND is_synthetic=true;

-- 3. 고객 100,000건.
INSERT INTO pms_guests (
  property_id, guest_id, guest_segment, country_group, crm_mapping_eligible,
  created_at, source_updated_at, is_synthetic
)
SELECT
  'SYNTHETIC_HOTEL_001',
  'GST-' || lpad(gs::text,8,'0'),
  CASE WHEN gs % 10 < 6 THEN 'LEISURE' WHEN gs % 10 < 9 THEN 'BUSINESS' ELSE 'GROUP' END,
  CASE gs % 6 WHEN 0 THEN 'DOMESTIC' WHEN 1 THEN 'EAST_ASIA' WHEN 2 THEN 'SOUTHEAST_ASIA'
       WHEN 3 THEN 'NORTH_AMERICA' WHEN 4 THEN 'EUROPE' ELSE 'OTHER' END,
  (gs % 100) < 85,
  timestamptz '2020-01-01 00:00:00+00' + ((gs * 17) % 365) * interval '1 day',
  timestamptz '2020-01-01 00:00:00+00' + ((gs * 17) % 365) * interval '1 day' + interval '1 hour',
  true
FROM generate_series(1,100000) AS gs;

-- 4. 일별 객실 공급 7,304건. 2026-07-29 이후는 계획 공급이므로 forecast로 분리한다.
WITH room_types(room_type_code, physical_rooms, type_ord) AS (
  VALUES ('STANDARD',150,1),('DELUXE',90,2),('SUITE',40,3),('RESIDENCE',20,4)
), dates AS (
  SELECT d::date AS business_date
  FROM generate_series(date '2022-01-01',date '2026-12-31',interval '1 day') d
), base AS (
  SELECT d.business_date, r.*,
         CASE WHEN extract(month from d.business_date) IN (1,2) THEN ((extract(day from d.business_date)::int+r.type_ord)%4)
              ELSE ((extract(day from d.business_date)::int+r.type_ord)%3) END AS ooo,
         CASE WHEN (extract(dow from d.business_date)::int+r.type_ord)%11=0 THEN 1 ELSE 0 END AS house_use
  FROM dates d CROSS JOIN room_types r
)
INSERT INTO pms_room_inventory_daily (
 property_id, inventory_id, business_date, room_type_code, physical_rooms,
 out_of_order_rooms, house_use_rooms, available_room_nights,
 data_period_status, is_forecast, is_synthetic, source_updated_at
)
SELECT
 'SYNTHETIC_HOTEL_001',
 ((business_date-date '2022-01-01')::bigint*10 + type_ord)::bigint,
 business_date, room_type_code, physical_rooms, ooo, house_use,
 physical_rooms-ooo-house_use,
 CASE WHEN business_date<=date '2024-12-31' THEN 'REFERENCE_CALIBRATED'
      WHEN business_date<=date '2025-12-31' THEN 'SYNTHETIC_ACTUAL_LIKE'
      WHEN business_date<=date '2026-07-28' THEN 'YTD_SYNTHETIC'
      ELSE 'FORECAST_SCENARIO' END,
 business_date>date '2026-07-28', true,
 CASE WHEN business_date>date '2026-07-28'
      THEN timestamptz '2026-07-28 04:00:00+00'
      ELSE LEAST(timestamptz '2026-07-28 05:00:00+00', business_date::timestamptz + interval '1 day 2 hour') END
FROM base;

-- 5. 예약 215,000건. 첫 165,000건은 객실 unit별 3일 슬롯을 사용해 실제 투숙 후보를 만든다.
WITH raw0 AS (
 SELECT n,
        ((n-1)%100000)+1 AS guest_n,
        ((n-1)%300) AS unit_idx,
        ((n-1)/300) AS unit_cycle,
        CASE WHEN n<=165000
             THEN date '2022-01-01' + floor(((n-1)/300)*3.04)::int
             ELSE date '2022-01-01' + ((n*43)%1819)::int END AS checkin_date
 FROM generate_series(1,215000) n
), raw AS (
 SELECT *,
        CASE WHEN n<=165000 THEN
          CASE WHEN extract(year from checkin_date)=2022 THEN CASE WHEN n%100<25 THEN 1 WHEN n%100<65 THEN 2 ELSE 3 END
               WHEN extract(year from checkin_date)=2023 THEN CASE WHEN n%100<22 THEN 1 WHEN n%100<63 THEN 2 ELSE 3 END
               ELSE CASE WHEN n%100<20 THEN 1 WHEN n%100<60 THEN 2 ELSE 3 END END
        ELSE CASE WHEN n%100<55 THEN 1 WHEN n%100<80 THEN 2 WHEN n%100<90 THEN 3
                  WHEN n%100<95 THEN 4 ELSE 5+(n%3) END END AS los
 FROM raw0
), typed AS (
 SELECT *,
   CASE WHEN unit_idx<150 THEN 'STANDARD' WHEN unit_idx<240 THEN 'DELUXE'
        WHEN unit_idx<280 THEN 'SUITE' ELSE 'RESIDENCE' END AS room_type_code,
   CASE WHEN n<=165000 AND extract(year from checkin_date)=2022 AND ((n*37+13)%1000)<100 THEN 'CANCELLED'
        WHEN n<=165000 AND extract(year from checkin_date)=2022 AND ((n*37+13)%1000)<140 THEN 'NO_SHOW'
        WHEN n<=165000 AND extract(year from checkin_date)=2023 AND ((n*37+13)%1000)<30 THEN 'CANCELLED'
        WHEN n<=165000 AND extract(year from checkin_date)=2023 AND ((n*37+13)%1000)<40 THEN 'NO_SHOW'
        WHEN n<=165000 AND extract(year from checkin_date)>=2024 AND ((n*37+13)%1000)<10 THEN 'CANCELLED'
        WHEN n<=165000 AND extract(year from checkin_date)>=2024 AND ((n*37+13)%1000)<15 THEN 'NO_SHOW'
        WHEN n<=165000 AND checkin_date<=date '2026-07-28' AND checkin_date+los>date '2026-07-28' THEN 'CHECKED_IN'
        WHEN n<=165000 THEN 'CHECKED_OUT'
        WHEN checkin_date>date '2026-07-28' AND n%10<>0 THEN 'BOOKED'
        WHEN n%2=0 THEN 'CANCELLED' ELSE 'NO_SHOW' END AS reservation_status
 FROM raw
), priced AS (
 SELECT *,
   round((CASE room_type_code WHEN 'STANDARD' THEN 110000 WHEN 'DELUXE' THEN 150000
          WHEN 'SUITE' THEN 235000 ELSE 290000 END
          * CASE extract(year from checkin_date)::int WHEN 2022 THEN 0.9435 WHEN 2023 THEN 1.0090
                 WHEN 2024 THEN 1.1520 WHEN 2025 THEN 1.2329 ELSE 1.3215 END
          * CASE extract(month from checkin_date)::int WHEN 1 THEN .86 WHEN 2 THEN .90 WHEN 3 THEN 1.02
                 WHEN 4 THEN 1.07 WHEN 5 THEN 1.10 WHEN 6 THEN 1.05 WHEN 7 THEN 1.08
                 WHEN 8 THEN 1.12 WHEN 9 THEN 1.02 WHEN 10 THEN 1.10 WHEN 11 THEN .99 ELSE 1.06 END
          * (0.96 + ((n*17)%9)/100.0))::numeric,2) AS quoted_rate,
   greatest(1,10+((n*29)%170)) AS lead_days
 FROM typed
), amounts AS (
 SELECT *,
   round(quoted_rate*los,2) AS gross_amount,
   round(quoted_rate*los*CASE WHEN n%5=0 THEN .08 WHEN n%7=0 THEN .05 ELSE 0 END,2) AS discount,
   CASE WHEN reservation_status='CANCELLED' THEN round((quoted_rate*los)*CASE WHEN n%4=0 THEN .10 ELSE 0 END,2) ELSE 0::numeric END AS cancel_fee
 FROM priced
), timed AS (
 SELECT *,
   LEAST((checkin_date::timestamp - lead_days*interval '1 day') AT TIME ZONE 'Asia/Seoul',
         timestamptz '2026-07-28 03:00:00+00') AS booked_at_calc
 FROM amounts
), finalized AS (
 SELECT *,
   CASE WHEN reservation_status='CANCELLED' THEN
     LEAST(
       booked_at_calc + ((n%30)+1)*interval '1 day',
       (checkin_date::timestamp - interval '1 hour') AT TIME ZONE 'Asia/Seoul',
       timestamptz '2026-07-28 04:00:00+00'
     )
   END AS cancelled_at_calc
 FROM timed
)
INSERT INTO pms_reservations (
 property_id,reservation_id,guest_id,booked_at,checkin_date,checkout_date,room_type_code,
 rate_plan_code,market_segment,booking_channel,reservation_status,cancelled_at,
 cancellation_reason_code,adult_count,child_count,quoted_room_rate,gross_room_amount,
 discount_amount,commission_amount,booked_amount,refund_amount,cancellation_fee,
 data_period_status,is_forecast,is_synthetic,source_updated_at
)
SELECT
 'SYNTHETIC_HOTEL_001',
 'RSV-'||md5(
   'SYNTHETIC_HOTEL_001|'||to_char(checkin_date,'YYYY-MM-DD')||'|'||room_type_code||'|'||
   lpad(guest_n::text,8,'0')||'|'||to_char(booked_at_calc AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS')||'|'||los::text
 ),
 'GST-'||lpad(guest_n::text,8,'0'),
 booked_at_calc, checkin_date, checkin_date+los, room_type_code,
 CASE n%4 WHEN 0 THEN 'FLEX' WHEN 1 THEN 'ADVANCE' WHEN 2 THEN 'CORPORATE' ELSE 'PACKAGE' END,
 CASE WHEN n%10<5 THEN 'LEISURE' WHEN n%10<8 THEN 'CORPORATE' WHEN n%10=8 THEN 'GROUP' ELSE 'PACKAGE' END,
 CASE WHEN n%10<4 THEN 'DIRECT' WHEN n%10<8 THEN 'OTA' ELSE 'CORPORATE' END,
 reservation_status,
 cancelled_at_calc,
 CASE WHEN reservation_status='CANCELLED' THEN CASE n%3 WHEN 0 THEN 'PLAN_CHANGE' WHEN 1 THEN 'PRICE' ELSE 'OTHER' END END,
 1+(n%3), CASE WHEN n%5=0 THEN 1 ELSE 0 END,
 quoted_rate,gross_amount,discount,
 round((gross_amount-discount)*CASE WHEN n%10<4 THEN 0 WHEN n%10<8 THEN .15 ELSE .05 END,2),
 gross_amount-discount,
 CASE WHEN reservation_status='CANCELLED' THEN gross_amount-discount-cancel_fee ELSE 0 END,
 cancel_fee,
 CASE WHEN checkin_date<=date '2024-12-31' THEN 'REFERENCE_CALIBRATED'
      WHEN checkin_date<=date '2025-12-31' THEN 'SYNTHETIC_ACTUAL_LIKE'
      WHEN checkin_date<=date '2026-07-28' THEN 'YTD_SYNTHETIC' ELSE 'FORECAST_SCENARIO' END,
 checkin_date>date '2026-07-28', true,
 GREATEST(booked_at_calc,
   COALESCE(cancelled_at_calc,booked_at_calc)
 ) + interval '5 minute'
FROM finalized;

-- 6. 실제 투숙. 미래 forecast 예약은 투숙 fact로 만들지 않는다.
-- 객실 코드는 OOO 수량과 무관한 객실유형별 고정 unit 순번을 사용한다.
WITH candidates AS (
 SELECT r.*,
        row_number() OVER (
          PARTITION BY r.checkin_date,r.room_type_code
          ORDER BY r.reservation_id
        ) AS unit_seq,
        (mod(hashtextextended(r.reservation_id,20260728),100)=0) AS complimentary_calc
 FROM pms_reservations r
 WHERE r.property_id='SYNTHETIC_HOTEL_001'
   AND r.reservation_status IN ('CHECKED_OUT','CHECKED_IN')
   AND r.checkin_date<=date '2026-07-28'
), flags AS (
 SELECT c.*,
        (NOT complimentary_calc AND mod(hashtextextended(reservation_id,20260728),137)=0) AS house_use_calc
 FROM candidates c
)
INSERT INTO pms_stays (
 property_id,stay_id,reservation_id,guest_id,room_unit_code,actual_checkin_at,actual_checkout_at,
 room_type_code,occupied_room_nights,guest_count,complimentary_flag,house_use_flag,
 room_revenue,other_room_charges,stay_status,data_period_status,is_forecast,is_synthetic,source_updated_at
)
SELECT
 property_id,'STY-'||md5(property_id||'|stay|'||reservation_id),reservation_id,guest_id,
 room_type_code||'-'||lpad(unit_seq::text,3,'0'),
 (checkin_date::timestamp + interval '6 hour') AT TIME ZONE 'Asia/Seoul',
 CASE WHEN reservation_status='CHECKED_OUT' THEN (checkout_date::timestamp + interval '2 hour') AT TIME ZONE 'Asia/Seoul' END,
 room_type_code,
 CASE WHEN reservation_status='CHECKED_OUT' THEN checkout_date-checkin_date ELSE 0 END,
 adult_count+child_count,
 complimentary_calc,house_use_calc,
 CASE WHEN reservation_status='CHECKED_OUT' AND NOT complimentary_calc AND NOT house_use_calc THEN booked_amount ELSE 0 END,
 CASE WHEN reservation_status='CHECKED_OUT' THEN round((adult_count+child_count)*25000*(checkout_date-checkin_date),2) ELSE 0 END,
 CASE WHEN reservation_status='CHECKED_OUT' THEN 'COMPLETED' ELSE 'IN_HOUSE' END,
 data_period_status,false,true,
 CASE WHEN reservation_status='CHECKED_OUT'
      THEN LEAST(timestamptz '2026-07-28 05:00:00+00',(checkout_date::timestamp+interval '3 hour') AT TIME ZONE 'Asia/Seoul')
      ELSE timestamptz '2026-07-28 04:30:00+00' END
FROM flags;
COMMIT;

-- 7. 실효 품질 검증. 모든 violation_count는 0이어야 한다.
SELECT 'inventory_duplicate' AS check_name, count(*) AS violation_count FROM (
 SELECT property_id,business_date,room_type_code FROM pms_room_inventory_daily
 WHERE property_id='SYNTHETIC_HOTEL_001' GROUP BY 1,2,3 HAVING count(*)>1) x
UNION ALL SELECT 'inventory_formula_mismatch',count(*) FROM pms_room_inventory_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND available_room_nights<>physical_rooms-out_of_order_rooms-house_use_rooms
UNION ALL SELECT 'checkout_not_after_checkin',count(*) FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND checkout_date<=checkin_date
UNION ALL SELECT 'booked_at_not_before_checkin',count(*) FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND booked_at>=checkin_date::timestamptz
UNION ALL SELECT 'booked_after_source_update',count(*) FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND booked_at>source_updated_at
UNION ALL SELECT 'guest_created_after_booking',count(*) FROM pms_reservations r JOIN pms_guests g USING(guest_id) WHERE r.property_id='SYNTHETIC_HOTEL_001' AND g.created_at>r.booked_at
UNION ALL SELECT 'cancelled_with_stay_REGRESSION_GUARD',count(*) FROM pms_reservations r JOIN pms_stays s USING(reservation_id) WHERE r.property_id='SYNTHETIC_HOTEL_001' AND r.reservation_status='CANCELLED'
UNION ALL SELECT 'no_show_revenue_REGRESSION_GUARD',count(*) FROM pms_reservations r JOIN pms_stays s USING(reservation_id) WHERE r.property_id='SYNTHETIC_HOTEL_001' AND r.reservation_status='NO_SHOW' AND s.room_revenue>0
UNION ALL SELECT 'future_booked_with_stay',count(*) FROM pms_reservations r JOIN pms_stays s USING(reservation_id) WHERE r.property_id='SYNTHETIC_HOTEL_001' AND r.checkin_date>date '2026-07-28'
UNION ALL SELECT 'negative_room_revenue',count(*) FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001' AND room_revenue<0
UNION ALL SELECT 'gross_formula_mismatch',count(*) FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND gross_room_amount<>quoted_room_rate*(checkout_date-checkin_date)
UNION ALL SELECT 'booked_formula_mismatch',count(*) FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND booked_amount<>gross_room_amount-discount_amount
UNION ALL SELECT 'cancel_refund_fee_mismatch',count(*) FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND reservation_status='CANCELLED' AND refund_amount+cancellation_fee<>booked_amount
UNION ALL SELECT 'noncancel_refund_or_fee',count(*) FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND reservation_status<>'CANCELLED' AND (refund_amount>0 OR cancellation_fee>0)
UNION ALL SELECT 'future_not_forecast',count(*) FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND checkin_date>=date '2026-07-29' AND is_forecast=false
UNION ALL SELECT 'forecast_stay',count(*) FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001' AND is_forecast=true
UNION ALL SELECT 'checkout_after_data_end',count(*) FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND checkout_date>date '2026-12-31'
UNION ALL SELECT 'stay_guest_mismatch',count(*) FROM pms_stays s JOIN pms_reservations r USING(reservation_id) WHERE s.property_id='SYNTHETIC_HOTEL_001' AND s.guest_id<>r.guest_id
UNION ALL SELECT 'completed_nights_mismatch',count(*) FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001' AND stay_status='COMPLETED' AND occupied_room_nights<>actual_checkout_at::date-actual_checkin_at::date
UNION ALL SELECT 'free_or_house_revenue',count(*) FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001' AND (complimentary_flag OR house_use_flag) AND room_revenue>0
UNION ALL SELECT 'completed_revenue_contract',count(*) FROM pms_stays s JOIN pms_reservations r USING(reservation_id) WHERE s.property_id='SYNTHETIC_HOTEL_001' AND s.stay_status='COMPLETED' AND NOT s.complimentary_flag AND NOT s.house_use_flag AND s.room_revenue<>r.booked_amount;

-- 추가 계약 검증.
SELECT 'cancelled_at_not_before_checkin' AS check_name,count(*) AS violation_count
FROM pms_reservations
WHERE property_id='SYNTHETIC_HOTEL_001' AND cancelled_at IS NOT NULL
  AND cancelled_at >= (checkin_date::timestamp AT TIME ZONE 'Asia/Seoul')
UNION ALL
SELECT 'stay_flag_mutual_exclusion',count(*)
FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001' AND complimentary_flag AND house_use_flag
UNION ALL
SELECT 'room_unit_capacity_overflow',count(*)
FROM pms_stays s
WHERE s.property_id='SYNTHETIC_HOTEL_001' AND
  split_part(s.room_unit_code,'-',2)::int > CASE s.room_type_code WHEN 'STANDARD' THEN 150 WHEN 'DELUXE' THEN 90 WHEN 'SUITE' THEN 40 ELSE 20 END
UNION ALL
SELECT 'pii_pattern_violation',count(*)
FROM pms_guests
WHERE property_id='SYNTHETIC_HOTEL_001'
  AND (guest_id !~ '^GST-[0-9]{8}$' OR guest_segment ~* '@|\\+?[0-9]{2,3}[- ]?[0-9]{3,4}[- ]?[0-9]{4}');

-- 동일 객실 실제 투숙기간 중첩 검증.
SELECT 'room_unit_overlap' AS check_name,count(*) AS violation_count
FROM pms_stays a JOIN pms_stays b
 ON a.property_id=b.property_id AND a.room_unit_code=b.room_unit_code AND a.stay_id<b.stay_id
 AND a.stay_status='COMPLETED' AND b.stay_status='COMPLETED'
 AND tstzrange(a.actual_checkin_at,a.actual_checkout_at,'[)') && tstzrange(b.actual_checkin_at,b.actual_checkout_at,'[)')
WHERE a.property_id='SYNTHETIC_HOTEL_001';

-- 일별 판매 객실박 > 가용 객실박 검증.
WITH sold AS (
 SELECT s.property_id,d::date business_date,s.room_type_code,count(*) rooms_sold
 FROM pms_stays s CROSS JOIN LATERAL generate_series(s.actual_checkin_at::date,s.actual_checkout_at::date-1,interval '1 day') d
 WHERE s.property_id='SYNTHETIC_HOTEL_001' AND s.stay_status='COMPLETED'
 GROUP BY 1,2,3
)
SELECT 'rooms_sold_over_inventory' AS check_name,count(*) AS violation_count
FROM sold s JOIN pms_room_inventory_daily i USING(property_id,business_date,room_type_code)
WHERE s.rooms_sold>i.available_room_nights;

-- 숙박일별 매출 배부 보존 검증.
WITH allocated AS (
 SELECT stay_id,sum(CASE WHEN d::date=actual_checkout_at::date-1
                    THEN room_revenue-round(room_revenue/occupied_room_nights,2)*(occupied_room_nights-1)
                    ELSE round(room_revenue/occupied_room_nights,2) END) allocated_revenue
 FROM pms_stays CROSS JOIN LATERAL generate_series(actual_checkin_at::date,actual_checkout_at::date-1,interval '1 day') d
 WHERE property_id='SYNTHETIC_HOTEL_001' AND stay_status='COMPLETED' AND occupied_room_nights>0
 GROUP BY stay_id
)
SELECT 'daily_revenue_allocation_mismatch' AS check_name,count(*) AS violation_count
FROM allocated a JOIN pms_stays s USING(stay_id) WHERE a.allocated_revenue<>s.room_revenue;

-- 비회귀 품질 지표.
SELECT
  (SELECT count(*) FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND reservation_status='CHECKED_IN') AS checked_in_count,
  round(100.0*count(*) FILTER (WHERE checkout_date-checkin_date>=5)/nullif(count(*),0),2) AS long_stay_pct,
  (corr((market_segment='LEISURE')::int,(g.guest_segment='LEISURE')::int) < .999) AS segment_not_identical
FROM pms_reservations r JOIN pms_guests g USING(guest_id)
WHERE r.property_id='SYNTHETIC_HOTEL_001';

-- 연도·기간·forecast별 KPI. 2026 actual과 forecast를 합치지 않는다.
WITH sold AS (
 SELECT s.property_id,d::date business_date,s.room_type_code,
        count(*) rooms_sold,sum(s.room_revenue/s.occupied_room_nights) room_revenue
 FROM pms_stays s CROSS JOIN LATERAL generate_series(s.actual_checkin_at::date,s.actual_checkout_at::date-1,interval '1 day') d
 WHERE s.property_id='SYNTHETIC_HOTEL_001' AND s.stay_status='COMPLETED' AND s.occupied_room_nights>0
 GROUP BY 1,2,3
), inv AS (
 SELECT extract(year from business_date)::int yr,data_period_status,is_forecast,
        sum(available_room_nights) available_room_nights
 FROM pms_room_inventory_daily WHERE property_id='SYNTHETIC_HOTEL_001' GROUP BY 1,2,3
), agg AS (
 SELECT extract(year from s.business_date)::int yr,i.data_period_status,i.is_forecast,
        sum(s.rooms_sold) rooms_sold,sum(s.room_revenue) room_revenue
 FROM sold s JOIN pms_room_inventory_daily i USING(property_id,business_date,room_type_code)
 GROUP BY 1,2,3
)
SELECT i.yr,i.data_period_status,i.is_forecast,i.available_room_nights,
       coalesce(a.rooms_sold,0) rooms_sold,
       round(coalesce(a.rooms_sold,0)/nullif(i.available_room_nights,0),6) occ,
       round(a.room_revenue/nullif(a.rooms_sold,0),2) adr,
       round(a.room_revenue/nullif(i.available_room_nights,0),2) revpar
FROM inv i LEFT JOIN agg a USING(yr,data_period_status,is_forecast)
ORDER BY yr,is_forecast;

WITH yearly AS (
 SELECT extract(year from actual_checkin_at)::int yr,
        sum(room_revenue)/nullif(sum(occupied_room_nights),0) generated_adr
 FROM pms_stays
 WHERE property_id='SYNTHETIC_HOTEL_001' AND stay_status='COMPLETED'
   AND NOT complimentary_flag AND NOT house_use_flag
 GROUP BY 1
), targets(yr,target_adr) AS (
 VALUES (2022,149983.92::numeric),(2023,160430.76::numeric),(2024,182704.68::numeric),
        (2025,195494.01::numeric),(2026,205268.71::numeric)
)
SELECT 'annual_adr_outside_5pct' AS check_name,count(*) AS violation_count
FROM yearly y JOIN targets t USING(yr)
WHERE y.generated_adr NOT BETWEEN t.target_adr*.95 AND t.target_adr*1.05;

SELECT extract(year from checkin_date)::int yr,data_period_status,is_forecast,
       count(*) reservation_count,
       round(avg(checkout_date-checkin_date),3) alos,
       round(avg((reservation_status='CANCELLED')::int),6) cancellation_rate,
       round(avg((reservation_status='NO_SHOW')::int),6) no_show_rate,
       count(*) FILTER (WHERE reservation_status='CHECKED_IN') checked_in_count,
       count(*) FILTER (WHERE reservation_status='BOOKED' AND checkin_date>date '2026-07-28') on_the_books_future
FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001'
GROUP BY 1,2,3 ORDER BY 1,3;

-- 실행 증거: row count, watermark, 안정 checksum.
SELECT 'pms_guests' table_name,count(*) row_count,max(source_updated_at) watermark,
       md5(count(*)||'|'||min(guest_id)||'|'||max(guest_id)||'|'||sum(hashtext(guest_id))::text) checksum
FROM pms_guests WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'pms_room_inventory_daily',count(*),max(source_updated_at),md5(count(*)||'|'||min(inventory_id)||'|'||max(inventory_id)||'|'||sum(inventory_id)::text) FROM pms_room_inventory_daily WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'pms_reservations',count(*),max(source_updated_at),md5(count(*)||'|'||min(reservation_id)||'|'||max(reservation_id)||'|'||sum(hashtext(reservation_id))::text) FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL SELECT 'pms_stays',count(*),max(source_updated_at),md5(count(*)||'|'||min(stay_id)||'|'||max(stay_id)||'|'||sum(hashtext(stay_id))::text) FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001';

SELECT 'seed=20260728' seed,'schema-v4.6-websql' schema_version,'scenario-v4.6' scenario_version,
       'source-fixture-v4.6' fixture_version,'DB_EXECUTION_RESULT_ABOVE' execution_status;
