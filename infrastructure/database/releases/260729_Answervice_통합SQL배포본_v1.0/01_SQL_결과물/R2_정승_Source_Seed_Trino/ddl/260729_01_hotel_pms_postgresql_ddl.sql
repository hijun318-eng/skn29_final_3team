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
-- output=260729_01_hotel_pms_postgresql_ddl.sql

-- ============================================================================
-- 260729_01_hotel_pms_postgresql_ddl.sql
-- Answervice schema contract v4.6
-- PostgreSQL 15+ / psql
-- schema_version=schema-v4.6-websql
-- 생성 범위: DDL, 제약조건, 인덱스, 주석, 구조 검증
-- 대량 운영 데이터와 실제 연결 자격정보는 포함하지 않는다.
-- 동일 객체의 컬럼 계약이 다르면 SCHEMA_CONTRACT_MISMATCH로 중단한다.
-- 실제 DB 실행 상태: 이 파일 자체에는 실행 성공을 주장하지 않는다.
-- ============================================================================
\set ON_ERROR_STOP on

-- source_id=pms
-- engine=PostgreSQL
-- database/schema=hotel_pms/public
-- ingestion_role=pms_ingest
-- query_role=pms_query
-- datahub_platform_instance=hotel_pms
-- trino_catalog=pms
-- schema_version=schema-v4.6-websql


SELECT 'CREATE DATABASE hotel_pms'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'hotel_pms')\gexec
\connect hotel_pms
CREATE SCHEMA IF NOT EXISTS public;

CREATE OR REPLACE FUNCTION pg_temp.assert_table_contract(
    p_schema text,
    p_table text,
    p_expected text[]
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_actual text[];
    v_reg regclass;
BEGIN
    v_reg := to_regclass(format('%I.%I', p_schema, p_table));
    IF v_reg IS NULL THEN
        RETURN;
    END IF;

    SELECT array_agg(
               a.attname || ':' || format_type(a.atttypid, a.atttypmod) || ':' || a.attnotnull::text
               ORDER BY a.attnum
           )
      INTO v_actual
      FROM pg_attribute a
     WHERE a.attrelid = v_reg
       AND a.attnum > 0
       AND NOT a.attisdropped;

    IF v_actual IS DISTINCT FROM p_expected THEN
        RAISE EXCEPTION 'SCHEMA_CONTRACT_MISMATCH %.% expected %, actual %',
            p_schema, p_table, p_expected, v_actual;
    END IF;
END
$$;

-- S01 public.pms_guests: 합성 PMS 고객 1건
SELECT pg_temp.assert_table_contract('public', 'pms_guests', ARRAY['property_id:character varying(64):true', 'guest_id:character varying(36):true', 'guest_segment:character varying(24):true', 'country_group:character varying(24):true', 'crm_mapping_eligible:boolean:true', 'created_at:timestamp with time zone:true', 'source_updated_at:timestamp with time zone:true', 'is_synthetic:boolean:true']::text[]);
CREATE TABLE IF NOT EXISTS public."pms_guests" (
    "property_id" varchar(64) NOT NULL,
    "guest_id" varchar(36) NOT NULL PRIMARY KEY,
    "guest_segment" varchar(24) NOT NULL,
    "country_group" varchar(24) NOT NULL,
    "crm_mapping_eligible" boolean NOT NULL,
    "created_at" timestamptz NOT NULL,
    "source_updated_at" timestamptz NOT NULL,
    "is_synthetic" boolean NOT NULL,
    CONSTRAINT "uq_pms_guests_property_id_guest_id" UNIQUE ("property_id", "guest_id"),
    CONSTRAINT "ck_pms_guests_1" CHECK (btrim(property_id) <> ''),
    CONSTRAINT "ck_pms_guests_2" CHECK (guest_segment IN ('LEISURE','BUSINESS','GROUP')),
    CONSTRAINT "ck_pms_guests_3" CHECK (created_at <= source_updated_at),
    CONSTRAINT "ck_pms_guests_4" CHECK (is_synthetic = true)
);
COMMENT ON TABLE public."pms_guests" IS '합성 PMS 고객 1건';
COMMENT ON COLUMN public."pms_guests"."property_id" IS '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]';
COMMENT ON COLUMN public."pms_guests"."guest_id" IS 'PMS 고객 ID. GST-8자리 합성 로컬 키 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_guests"."guest_segment" IS '고객군. LEISURE/BUSINESS/GROUP [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_guests"."country_group" IS '국가 그룹. 직접 국적·주소 아님 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_guests"."crm_mapping_eligible" IS 'CRM 매핑 대상 여부. 합성 교차 Source 연결 대상 [classification=POLICY]';
COMMENT ON COLUMN public."pms_guests"."created_at" IS '생성 시각.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_guests"."source_updated_at" IS '원천 수정시각. watermark [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_guests"."is_synthetic" IS '합성 여부. 항상 true [classification=POLICY]';

-- S02 public.pms_room_inventory_daily: 영업일자·객실유형별 물리·판매가능 객실 공급 1건
SELECT pg_temp.assert_table_contract('public', 'pms_room_inventory_daily', ARRAY['property_id:character varying(64):true', 'inventory_id:bigint:true', 'business_date:date:true', 'room_type_code:character varying(32):true', 'physical_rooms:integer:true', 'out_of_order_rooms:integer:true', 'house_use_rooms:integer:true', 'available_room_nights:integer:true', 'data_period_status:character varying(32):true', 'is_forecast:boolean:true', 'is_synthetic:boolean:true', 'source_updated_at:timestamp with time zone:true']::text[]);
CREATE TABLE IF NOT EXISTS public."pms_room_inventory_daily" (
    "property_id" varchar(64) NOT NULL,
    "inventory_id" bigint NOT NULL PRIMARY KEY,
    "business_date" date NOT NULL,
    "room_type_code" varchar(32) NOT NULL,
    "physical_rooms" integer NOT NULL,
    "out_of_order_rooms" integer NOT NULL,
    "house_use_rooms" integer NOT NULL,
    "available_room_nights" integer NOT NULL,
    "data_period_status" varchar(32) NOT NULL,
    "is_forecast" boolean NOT NULL,
    "is_synthetic" boolean NOT NULL,
    "source_updated_at" timestamptz NOT NULL,
    CONSTRAINT "uq_pms_room_inventory_daily_property_id_busine_b7601eb6" UNIQUE ("property_id", "business_date", "room_type_code"),
    CONSTRAINT "ck_pms_room_inventory_daily_1" CHECK (physical_rooms >= 0),
    CONSTRAINT "ck_pms_room_inventory_daily_2" CHECK (out_of_order_rooms >= 0),
    CONSTRAINT "ck_pms_room_inventory_daily_3" CHECK (house_use_rooms >= 0),
    CONSTRAINT "ck_pms_room_inventory_daily_4" CHECK (available_room_nights >= 0),
    CONSTRAINT "ck_pms_room_inventory_daily_5" CHECK (available_room_nights = physical_rooms - out_of_order_rooms - house_use_rooms),
    CONSTRAINT "ck_pms_room_inventory_daily_6" CHECK (out_of_order_rooms + house_use_rooms <= physical_rooms),
    CONSTRAINT "ck_pms_room_inventory_daily_7" CHECK (is_synthetic = true),
    CONSTRAINT "ck_pms_room_inventory_daily_8" CHECK (data_period_status IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
    CONSTRAINT "ck_pms_room_inventory_daily_9" CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO')),
    CONSTRAINT "ck_pms_room_inventory_daily_10" CHECK ((business_date BETWEEN DATE '2022-01-01' AND DATE '2024-12-31' AND data_period_status='REFERENCE_CALIBRATED') OR (business_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' AND data_period_status='SYNTHETIC_ACTUAL_LIKE') OR (business_date BETWEEN DATE '2026-01-01' AND DATE '2026-07-28' AND data_period_status='YTD_SYNTHETIC') OR (business_date BETWEEN DATE '2026-07-29' AND DATE '2026-12-31' AND data_period_status='FORECAST_SCENARIO'))
);
COMMENT ON TABLE public."pms_room_inventory_daily" IS '영업일자·객실유형별 물리·판매가능 객실 공급 1건';
COMMENT ON COLUMN public."pms_room_inventory_daily"."property_id" IS '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]';
COMMENT ON COLUMN public."pms_room_inventory_daily"."inventory_id" IS '객실공급 ID. PK [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_room_inventory_daily"."business_date" IS '영업일자.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_room_inventory_daily"."room_type_code" IS '객실 유형.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_room_inventory_daily"."physical_rooms" IS '물리 객실 수. 0 이상 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_room_inventory_daily"."out_of_order_rooms" IS '판매불가 객실 수. 0 이상 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_room_inventory_daily"."house_use_rooms" IS '내부사용 객실 수. 0 이상 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_room_inventory_daily"."available_room_nights" IS '판매가능 객실박. physical-OOO-house use [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_room_inventory_daily"."data_period_status" IS '기간 상태. 4개 고정 상태 [classification=POLICY]';
COMMENT ON COLUMN public."pms_room_inventory_daily"."is_forecast" IS '전망 여부. 2026-07 이후 true [classification=POLICY]';
COMMENT ON COLUMN public."pms_room_inventory_daily"."is_synthetic" IS '합성 여부. 항상 true [classification=POLICY]';
COMMENT ON COLUMN public."pms_room_inventory_daily"."source_updated_at" IS '원천 수정시각. watermark [classification=SYNTHETIC]';

-- S03 public.pms_reservations: 합성 예약 1건
SELECT pg_temp.assert_table_contract('public', 'pms_reservations', ARRAY['property_id:character varying(64):true', 'reservation_id:character varying(36):true', 'guest_id:character varying(36):true', 'booked_at:timestamp with time zone:true', 'checkin_date:date:true', 'checkout_date:date:true', 'room_type_code:character varying(32):true', 'rate_plan_code:character varying(32):true', 'market_segment:character varying(24):true', 'booking_channel:character varying(24):true', 'reservation_status:character varying(20):true', 'cancelled_at:timestamp with time zone:false', 'cancellation_reason_code:character varying(32):false', 'adult_count:integer:true', 'child_count:integer:true', 'quoted_room_rate:numeric(14,2):true', 'gross_room_amount:numeric(14,2):true', 'discount_amount:numeric(14,2):true', 'commission_amount:numeric(14,2):true', 'booked_amount:numeric(14,2):true', 'refund_amount:numeric(14,2):true', 'cancellation_fee:numeric(14,2):true', 'data_period_status:character varying(32):true', 'is_forecast:boolean:true', 'is_synthetic:boolean:true', 'source_updated_at:timestamp with time zone:true']::text[]);
CREATE TABLE IF NOT EXISTS public."pms_reservations" (
    "property_id" varchar(64) NOT NULL,
    "reservation_id" varchar(36) NOT NULL PRIMARY KEY,
    "guest_id" varchar(36) NOT NULL,
    "booked_at" timestamptz NOT NULL,
    "checkin_date" date NOT NULL,
    "checkout_date" date NOT NULL,
    "room_type_code" varchar(32) NOT NULL,
    "rate_plan_code" varchar(32) NOT NULL,
    "market_segment" varchar(24) NOT NULL,
    "booking_channel" varchar(24) NOT NULL,
    "reservation_status" varchar(20) NOT NULL,
    "cancelled_at" timestamptz,
    "cancellation_reason_code" varchar(32),
    "adult_count" integer NOT NULL,
    "child_count" integer NOT NULL,
    "quoted_room_rate" numeric(14,2) NOT NULL,
    "gross_room_amount" numeric(14,2) NOT NULL,
    "discount_amount" numeric(14,2) NOT NULL,
    "commission_amount" numeric(14,2) NOT NULL,
    "booked_amount" numeric(14,2) NOT NULL,
    "refund_amount" numeric(14,2) NOT NULL,
    "cancellation_fee" numeric(14,2) NOT NULL,
    "data_period_status" varchar(32) NOT NULL,
    "is_forecast" boolean NOT NULL,
    "is_synthetic" boolean NOT NULL,
    "source_updated_at" timestamptz NOT NULL,
    CONSTRAINT "uq_pms_reservations_property_id_reservation_id" UNIQUE ("property_id", "reservation_id"),
    CONSTRAINT "ck_pms_reservations_1" CHECK (checkout_date > checkin_date),
    CONSTRAINT "ck_pms_reservations_2" CHECK (reservation_status IN ('BOOKED','CANCELLED','CHECKED_IN','CHECKED_OUT','NO_SHOW')),
    CONSTRAINT "ck_pms_reservations_3" CHECK (booking_channel IN ('DIRECT','OTA','CORPORATE')),
    CONSTRAINT "ck_pms_reservations_4" CHECK (adult_count >= 0),
    CONSTRAINT "ck_pms_reservations_5" CHECK (child_count >= 0),
    CONSTRAINT "ck_pms_reservations_6" CHECK (adult_count + child_count >= 1),
    CONSTRAINT "ck_pms_reservations_7" CHECK (quoted_room_rate >= 0),
    CONSTRAINT "ck_pms_reservations_8" CHECK (gross_room_amount >= 0),
    CONSTRAINT "ck_pms_reservations_9" CHECK (discount_amount >= 0),
    CONSTRAINT "ck_pms_reservations_10" CHECK (commission_amount >= 0),
    CONSTRAINT "ck_pms_reservations_11" CHECK (booked_amount >= 0),
    CONSTRAINT "ck_pms_reservations_12" CHECK (refund_amount >= 0),
    CONSTRAINT "ck_pms_reservations_13" CHECK (cancellation_fee >= 0),
    CONSTRAINT "ck_pms_reservations_14" CHECK (gross_room_amount = quoted_room_rate * (checkout_date - checkin_date)),
    CONSTRAINT "ck_pms_reservations_15" CHECK (booked_amount = gross_room_amount - discount_amount),
    CONSTRAINT "ck_pms_reservations_16" CHECK (discount_amount <= gross_room_amount),
    CONSTRAINT "ck_pms_reservations_17" CHECK (commission_amount <= booked_amount),
    CONSTRAINT "ck_pms_reservations_18" CHECK ((reservation_status='CANCELLED' AND cancelled_at IS NOT NULL AND refund_amount + cancellation_fee = booked_amount) OR (reservation_status<>'CANCELLED' AND refund_amount=0 AND cancellation_fee=0)),
    CONSTRAINT "ck_pms_reservations_19" CHECK (cancelled_at IS NULL OR cancelled_at >= booked_at),
    CONSTRAINT "ck_pms_reservations_20" CHECK (booked_at <= source_updated_at),
    CONSTRAINT "ck_pms_reservations_21" CHECK (is_synthetic=true),
    CONSTRAINT "ck_pms_reservations_22" CHECK (data_period_status IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
    CONSTRAINT "ck_pms_reservations_23" CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO')),
    CONSTRAINT "ck_pms_reservations_24" CHECK ((checkin_date BETWEEN DATE '2022-01-01' AND DATE '2024-12-31' AND data_period_status='REFERENCE_CALIBRATED') OR (checkin_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' AND data_period_status='SYNTHETIC_ACTUAL_LIKE') OR (checkin_date BETWEEN DATE '2026-01-01' AND DATE '2026-07-28' AND data_period_status='YTD_SYNTHETIC') OR (checkin_date BETWEEN DATE '2026-07-29' AND DATE '2026-12-31' AND data_period_status='FORECAST_SCENARIO'))
);
COMMENT ON TABLE public."pms_reservations" IS '합성 예약 1건';
COMMENT ON COLUMN public."pms_reservations"."property_id" IS '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]';
COMMENT ON COLUMN public."pms_reservations"."reservation_id" IS '예약 ID. PK [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."guest_id" IS 'PMS 고객 ID.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."booked_at" IS '예약 시각.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."checkin_date" IS '체크인 예정일.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."checkout_date" IS '체크아웃 예정일. checkin 이후 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."room_type_code" IS '객실 유형.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."rate_plan_code" IS '요금제.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."market_segment" IS '시장 세그먼트. LEISURE/BUSINESS/GROUP 등 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."booking_channel" IS '예약 채널. DIRECT/OTA/CORPORATE [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."reservation_status" IS '예약 상태. BOOKED/CANCELLED/CHECKED_IN/CHECKED_OUT/NO_SHOW [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."cancelled_at" IS '취소 시각.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."cancellation_reason_code" IS '취소 사유 코드.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."adult_count" IS '성인 수. 0 이상 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."child_count" IS '아동 수. 0 이상 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."quoted_room_rate" IS '제시 객실가. KRW [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."gross_room_amount" IS '총 객실 계약액. 1박 요금×숙박일수 [classification=INTERNAL]';
COMMENT ON COLUMN public."pms_reservations"."discount_amount" IS '할인 금액. 0 이상 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."commission_amount" IS '채널 수수료. 0 이상 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."booked_amount" IS '예약 금액. KRW 합성값 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_reservations"."refund_amount" IS '예약 환불액. 취소·환불 별도 금액 [classification=INTERNAL]';
COMMENT ON COLUMN public."pms_reservations"."cancellation_fee" IS '취소 수수료. 취소 시 retained 금액 [classification=INTERNAL]';
COMMENT ON COLUMN public."pms_reservations"."data_period_status" IS '기간 상태. 4개 고정 상태 [classification=POLICY]';
COMMENT ON COLUMN public."pms_reservations"."is_forecast" IS '전망 여부. 2026-07 이후 true [classification=POLICY]';
COMMENT ON COLUMN public."pms_reservations"."is_synthetic" IS '합성 여부. 항상 true [classification=POLICY]';
COMMENT ON COLUMN public."pms_reservations"."source_updated_at" IS '원천 수정시각. watermark [classification=SYNTHETIC]';

-- S04 public.pms_stays: 합성 투숙 1건
SELECT pg_temp.assert_table_contract('public', 'pms_stays', ARRAY['property_id:character varying(64):true', 'stay_id:character varying(36):true', 'reservation_id:character varying(36):true', 'guest_id:character varying(36):true', 'room_unit_code:character varying(32):true', 'actual_checkin_at:timestamp with time zone:false', 'actual_checkout_at:timestamp with time zone:false', 'room_type_code:character varying(32):true', 'occupied_room_nights:integer:true', 'guest_count:integer:true', 'complimentary_flag:boolean:true', 'house_use_flag:boolean:true', 'room_revenue:numeric(14,2):true', 'other_room_charges:numeric(14,2):true', 'stay_status:character varying(20):true', 'data_period_status:character varying(32):true', 'is_forecast:boolean:true', 'is_synthetic:boolean:true', 'source_updated_at:timestamp with time zone:true']::text[]);
CREATE TABLE IF NOT EXISTS public."pms_stays" (
    "property_id" varchar(64) NOT NULL,
    "stay_id" varchar(36) NOT NULL PRIMARY KEY,
    "reservation_id" varchar(36) NOT NULL,
    "guest_id" varchar(36) NOT NULL,
    "room_unit_code" varchar(32) NOT NULL,
    "actual_checkin_at" timestamptz,
    "actual_checkout_at" timestamptz,
    "room_type_code" varchar(32) NOT NULL,
    "occupied_room_nights" integer NOT NULL,
    "guest_count" integer NOT NULL,
    "complimentary_flag" boolean NOT NULL,
    "house_use_flag" boolean NOT NULL,
    "room_revenue" numeric(14,2) NOT NULL,
    "other_room_charges" numeric(14,2) NOT NULL,
    "stay_status" varchar(20) NOT NULL,
    "data_period_status" varchar(32) NOT NULL,
    "is_forecast" boolean NOT NULL,
    "is_synthetic" boolean NOT NULL,
    "source_updated_at" timestamptz NOT NULL,
    CONSTRAINT "uq_pms_stays_property_id_stay_id" UNIQUE ("property_id", "stay_id"),
    CONSTRAINT "uq_pms_stays_reservation_id" UNIQUE ("reservation_id"),
    CONSTRAINT "ck_pms_stays_1" CHECK (stay_status IN ('EXPECTED','IN_HOUSE','COMPLETED','CANCELLED','NO_SHOW')),
    CONSTRAINT "ck_pms_stays_2" CHECK (occupied_room_nights >= 0),
    CONSTRAINT "ck_pms_stays_3" CHECK (guest_count >= 1),
    CONSTRAINT "ck_pms_stays_4" CHECK (room_revenue >= 0),
    CONSTRAINT "ck_pms_stays_5" CHECK (other_room_charges >= 0),
    CONSTRAINT "ck_pms_stays_6" CHECK (actual_checkout_at IS NULL OR actual_checkin_at IS NOT NULL),
    CONSTRAINT "ck_pms_stays_7" CHECK (actual_checkout_at IS NULL OR actual_checkout_at > actual_checkin_at),
    CONSTRAINT "ck_pms_stays_8" CHECK ((stay_status='COMPLETED' AND actual_checkin_at IS NOT NULL AND actual_checkout_at IS NOT NULL AND occupied_room_nights = (actual_checkout_at::date - actual_checkin_at::date)) OR (stay_status<>'COMPLETED')),
    CONSTRAINT "ck_pms_stays_9" CHECK (NOT (complimentary_flag AND house_use_flag)),
    CONSTRAINT "ck_pms_stays_10" CHECK ((NOT complimentary_flag AND NOT house_use_flag) OR room_revenue=0),
    CONSTRAINT "ck_pms_stays_11" CHECK (is_synthetic=true),
    CONSTRAINT "ck_pms_stays_12" CHECK (data_period_status IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
    CONSTRAINT "ck_pms_stays_13" CHECK (is_forecast = (data_period_status='FORECAST_SCENARIO'))
);
COMMENT ON TABLE public."pms_stays" IS '합성 투숙 1건';
COMMENT ON COLUMN public."pms_stays"."property_id" IS '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]';
COMMENT ON COLUMN public."pms_stays"."stay_id" IS '투숙 ID. PK [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."reservation_id" IS '예약 ID.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."guest_id" IS 'PMS 고객 ID.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."room_unit_code" IS '안정 객실 단위 코드. 객실유형+고정 unit sequence [classification=INTERNAL]';
COMMENT ON COLUMN public."pms_stays"."actual_checkin_at" IS '실제 체크인.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."actual_checkout_at" IS '실제 체크아웃.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."room_type_code" IS '객실 유형.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."occupied_room_nights" IS '점유 객실박. 0 이상 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."guest_count" IS '투숙 인원. 1 이상 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."complimentary_flag" IS '무료 투숙 여부.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."house_use_flag" IS '내부 사용 여부.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."room_revenue" IS '객실 매출. 핵심 metric 원자값 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."other_room_charges" IS '기타 객실 부과액. 0 이상 [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."stay_status" IS '투숙 상태. EXPECTED/IN_HOUSE/COMPLETED/CANCELLED/NO_SHOW [classification=SYNTHETIC]';
COMMENT ON COLUMN public."pms_stays"."data_period_status" IS '기간 상태. 4개 고정 상태 [classification=POLICY]';
COMMENT ON COLUMN public."pms_stays"."is_forecast" IS '전망 여부. 2026-07 이후 true [classification=POLICY]';
COMMENT ON COLUMN public."pms_stays"."is_synthetic" IS '합성 여부. 항상 true [classification=POLICY]';
COMMENT ON COLUMN public."pms_stays"."source_updated_at" IS '원천 수정시각. watermark [classification=SYNTHETIC]';

-- Source 내부 물리 FK. property_id 일치까지 함께 강제한다.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_pms_reservation_guest') THEN
    ALTER TABLE public.pms_reservations
      ADD CONSTRAINT fk_pms_reservation_guest
      FOREIGN KEY (property_id, guest_id)
      REFERENCES public.pms_guests(property_id, guest_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_pms_stay_reservation') THEN
    ALTER TABLE public.pms_stays
      ADD CONSTRAINT fk_pms_stay_reservation
      FOREIGN KEY (property_id, reservation_id)
      REFERENCES public.pms_reservations(property_id, reservation_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_pms_stay_guest') THEN
    ALTER TABLE public.pms_stays
      ADD CONSTRAINT fk_pms_stay_guest
      FOREIGN KEY (property_id, guest_id)
      REFERENCES public.pms_guests(property_id, guest_id);
  END IF;
END
$$;

CREATE OR REPLACE FUNCTION public.enforce_pms_stay_contract()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_guest_id varchar(36);
BEGIN
  SELECT guest_id INTO v_guest_id
  FROM public.pms_reservations
  WHERE property_id=NEW.property_id AND reservation_id=NEW.reservation_id;

  IF v_guest_id IS DISTINCT FROM NEW.guest_id THEN
    RAISE EXCEPTION 'SCHEMA_CONTRACT_MISMATCH: stay guest differs from reservation guest';
  END IF;

  IF NEW.is_forecast=false
     AND NEW.actual_checkin_at IS NOT NULL
     AND NEW.actual_checkout_at IS NOT NULL
     AND EXISTS (
       SELECT 1
       FROM public.pms_stays s
       WHERE s.property_id=NEW.property_id
         AND s.room_unit_code=NEW.room_unit_code
         AND s.stay_id<>NEW.stay_id
         AND s.is_forecast=false
         AND s.actual_checkin_at IS NOT NULL
         AND s.actual_checkout_at IS NOT NULL
         AND tstzrange(s.actual_checkin_at,s.actual_checkout_at,'[)') &&
             tstzrange(NEW.actual_checkin_at,NEW.actual_checkout_at,'[)')
     ) THEN
    RAISE EXCEPTION 'PMS_ROOM_STAY_OVERLAP: room_unit_code=%', NEW.room_unit_code;
  END IF;
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_enforce_pms_stay_contract ON public.pms_stays;
CREATE CONSTRAINT TRIGGER trg_enforce_pms_stay_contract
AFTER INSERT OR UPDATE ON public.pms_stays
DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION public.enforce_pms_stay_contract();

CREATE OR REPLACE VIEW public.pms_stays_actual AS
SELECT *
FROM public.pms_stays
WHERE is_forecast=false
  AND data_period_status<>'FORECAST_SCENARIO';

COMMENT ON VIEW public.pms_stays_actual IS
  '실제/YTD 투숙 기본 조회 경로. forecast scenario를 제외한다.';

CREATE INDEX IF NOT EXISTS "ix_pms_reservations_checkin_date_reservation_status" ON public."pms_reservations" ("checkin_date", "reservation_status");

CREATE INDEX IF NOT EXISTS "ix_pms_reservations_guest_id_checkin_date" ON public."pms_reservations" ("guest_id", "checkin_date");

CREATE INDEX IF NOT EXISTS "ix_pms_stays_guest_id_actual_checkin_at" ON public."pms_stays" ("guest_id", "actual_checkin_at");

CREATE INDEX IF NOT EXISTS "ix_pms_stays_room_unit_code_actual_checkin_at__a449a87d" ON public."pms_stays" ("room_unit_code", "actual_checkin_at", "actual_checkout_at");

CREATE INDEX IF NOT EXISTS "ix_pms_reservations_property_id_guest_id" ON public."pms_reservations" ("property_id", "guest_id");

CREATE INDEX IF NOT EXISTS "ix_pms_stays_property_id_reservation_id" ON public."pms_stays" ("property_id", "reservation_id");

CREATE INDEX IF NOT EXISTS "ix_pms_stays_property_id_guest_id" ON public."pms_stays" ("property_id", "guest_id");

-- 최소권한 group role. 실제 접속 주체 연결은 별도 보안 구성에서 수행한다.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='pms_ingest') THEN
    CREATE ROLE "pms_ingest" NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='pms_query') THEN
    CREATE ROLE "pms_query" NOLOGIN;
  END IF;
END
$$;

REVOKE ALL ON DATABASE "hotel_pms" FROM PUBLIC;
GRANT CONNECT ON DATABASE "hotel_pms" TO "pms_ingest", "pms_query";
GRANT USAGE ON SCHEMA public TO "pms_ingest", "pms_query";
GRANT SELECT, INSERT, UPDATE, DELETE ON public."pms_guests", public."pms_room_inventory_daily", public."pms_reservations", public."pms_stays" TO "pms_ingest";
GRANT SELECT ON public."pms_guests", public."pms_room_inventory_daily", public."pms_reservations", public."pms_stays" TO "pms_query";
GRANT SELECT ON public."pms_stays_actual" TO "pms_query";
REVOKE CREATE ON SCHEMA public FROM "pms_ingest", "pms_query";
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public."pms_guests", public."pms_room_inventory_daily", public."pms_reservations", public."pms_stays" FROM "pms_query";

-- Read-only negative tests. 관리자 세션에서 실행되며 예상 권한 오류만 PASS로 처리한다.
SET ROLE "pms_query";
DO $negative$
BEGIN
  BEGIN
    EXECUTE 'INSERT INTO public.pms_guests DEFAULT VALUES';
    RAISE EXCEPTION 'READ_ONLY_NEGATIVE_TEST_FAILED: INSERT unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'PASS: pms_query INSERT blocked';
  END;
  BEGIN
    EXECUTE 'UPDATE public.pms_guests SET property_id=property_id WHERE false';
    RAISE EXCEPTION 'READ_ONLY_NEGATIVE_TEST_FAILED: UPDATE unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'PASS: pms_query UPDATE blocked';
  END;
  BEGIN
    EXECUTE 'DELETE FROM public.pms_guests WHERE false';
    RAISE EXCEPTION 'READ_ONLY_NEGATIVE_TEST_FAILED: DELETE unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'PASS: pms_query DELETE blocked';
  END;
  BEGIN
    EXECUTE 'ALTER TABLE public.pms_guests ADD COLUMN __negative_test integer';
    RAISE EXCEPTION 'READ_ONLY_NEGATIVE_TEST_FAILED: DDL unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'PASS: pms_query DDL blocked';
  END;
END
$negative$;
RESET ROLE;

-- 구조 및 논리 검증
SELECT count(*) AS source_table_count,
       CASE WHEN count(*)=4 THEN 'PASS' ELSE 'SCHEMA_CONTRACT_MISMATCH' END AS status
FROM information_schema.tables
WHERE table_schema='public' AND table_type='BASE TABLE'
  AND table_name IN ('pms_guests','pms_room_inventory_daily','pms_reservations','pms_stays');

SELECT count(*) AS source_column_count,
       CASE WHEN count(*)=65 THEN 'PASS' ELSE 'SCHEMA_CONTRACT_MISMATCH' END AS status
FROM information_schema.columns
WHERE table_schema='public'
  AND table_name IN ('pms_guests','pms_room_inventory_daily','pms_reservations','pms_stays');

SELECT count(*) AS guest_contract_mismatch_count
FROM public.pms_stays s
JOIN public.pms_reservations r
  ON r.property_id=s.property_id AND r.reservation_id=s.reservation_id
WHERE s.guest_id<>r.guest_id;

SELECT count(*) AS room_overlap_count
FROM public.pms_stays a
JOIN public.pms_stays b
  ON a.property_id=b.property_id
 AND a.room_unit_code=b.room_unit_code
 AND a.stay_id<b.stay_id
 AND a.is_forecast=false AND b.is_forecast=false
 AND tstzrange(a.actual_checkin_at,a.actual_checkout_at,'[)') &&
     tstzrange(b.actual_checkin_at,b.actual_checkout_at,'[)')
WHERE a.actual_checkin_at IS NOT NULL AND a.actual_checkout_at IS NOT NULL
  AND b.actual_checkin_at IS NOT NULL AND b.actual_checkout_at IS NOT NULL;

SELECT 'pms' AS source_id, 'PostgreSQL' AS engine, 'hotel_pms/public' AS database_schema,
       'pms_ingest' AS ingestion_role, 'pms_query' AS query_role,
       'hotel_pms' AS datahub_platform_instance, 'pms' AS trino_catalog,
       'schema-v4.6-websql' AS schema_version;
