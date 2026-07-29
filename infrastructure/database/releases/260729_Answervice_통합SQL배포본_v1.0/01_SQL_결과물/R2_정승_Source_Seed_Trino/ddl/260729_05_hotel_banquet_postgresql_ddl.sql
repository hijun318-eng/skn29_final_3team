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
-- output=260729_05_hotel_banquet_postgresql_ddl.sql

-- ============================================================================
-- 260729_05_hotel_banquet_postgresql_ddl.sql
-- Answervice schema contract v4.6
-- PostgreSQL 15+ / psql
-- schema_version=schema-v4.6-websql
-- 생성 범위: DDL, 제약조건, 인덱스, 주석, 구조 검증
-- 대량 운영 데이터와 실제 연결 자격정보는 포함하지 않는다.
-- 동일 객체의 컬럼 계약이 다르면 SCHEMA_CONTRACT_MISMATCH로 중단한다.
-- 실제 DB 실행 상태: 이 파일 자체에는 실행 성공을 주장하지 않는다.
-- ============================================================================
\set ON_ERROR_STOP on

-- source_id=banquet
-- engine=PostgreSQL
-- database/schema=hotel_banquet/public
-- ingestion_role=banquet_ingest
-- query_role=banquet_query
-- datahub_platform_instance=hotel_banquet
-- trino_catalog=banquet
-- schema_version=schema-v4.6-websql


SELECT 'CREATE DATABASE hotel_banquet'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'hotel_banquet')\gexec
\connect hotel_banquet
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

-- S16 public.banquet_bookings: 합성 연회 문의·견적·확정·행사 1건
SELECT pg_temp.assert_table_contract('public', 'banquet_bookings', ARRAY['property_id:character varying(64):true', 'banquet_event_id:character varying(36):true', 'customer_id:character varying(36):true', 'inquiry_at:timestamp with time zone:true', 'quoted_at:timestamp with time zone:false', 'confirmed_at:timestamp with time zone:false', 'cancelled_at:timestamp with time zone:false', 'event_date:date:true', 'product_code:character varying(32):true', 'product_category:character varying(32):true', 'expected_guests:integer:true', 'actual_attendees:integer:false', 'lead_source:character varying(24):true', 'sales_owner_team:character varying(32):true', 'booking_status:character varying(20):true', 'contracted_amount:numeric(14,2):true', 'pickup_room_count:integer:true', 'released_room_count:integer:true', 'group_checkout_date:date:false', 'group_checkin_date:date:false', 'expected_room_nights:integer:true', 'reserved_room_block_count:integer:true', 'cancellation_fee:numeric(14,2):true', 'data_period_status:character varying(32):true', 'is_forecast:boolean:true', 'is_synthetic:boolean:true', 'source_updated_at:timestamp with time zone:true']::text[]);
CREATE TABLE IF NOT EXISTS public."banquet_bookings" (
    "property_id" varchar(64) NOT NULL,
    "banquet_event_id" varchar(36) NOT NULL PRIMARY KEY,
    "customer_id" varchar(36) NOT NULL,
    "inquiry_at" timestamptz NOT NULL,
    "quoted_at" timestamptz,
    "confirmed_at" timestamptz,
    "cancelled_at" timestamptz,
    "event_date" date NOT NULL,
    "product_code" varchar(32) NOT NULL,
    "product_category" varchar(32) NOT NULL,
    "expected_guests" integer NOT NULL,
    "actual_attendees" integer,
    "lead_source" varchar(24) NOT NULL,
    "sales_owner_team" varchar(32) NOT NULL,
    "booking_status" varchar(20) NOT NULL,
    "contracted_amount" numeric(14,2) NOT NULL,
    "pickup_room_count" integer NOT NULL,
    "released_room_count" integer NOT NULL,
    "group_checkout_date" date,
    "group_checkin_date" date,
    "expected_room_nights" integer NOT NULL,
    "reserved_room_block_count" integer NOT NULL,
    "cancellation_fee" numeric(14,2) NOT NULL,
    "data_period_status" varchar(32) NOT NULL,
    "is_forecast" boolean NOT NULL,
    "is_synthetic" boolean NOT NULL,
    "source_updated_at" timestamptz NOT NULL,
    CONSTRAINT "uq_banquet_bookings_property_id_banquet_event_id" UNIQUE ("property_id", "banquet_event_id"),
    CONSTRAINT "ck_banquet_bookings_1" CHECK (expected_guests >= 0),
    CONSTRAINT "ck_banquet_bookings_2" CHECK (actual_attendees IS NULL OR actual_attendees >= 0),
    CONSTRAINT "ck_banquet_bookings_3" CHECK (booking_status IN ('INQUIRY','QUOTED','TENTATIVE','CONFIRMED','CANCELLED','COMPLETED')),
    CONSTRAINT "ck_banquet_bookings_4" CHECK (product_category IN ('WEDDING','CONFERENCE','MEETING','CORPORATE_EVENT','SOCIAL_EVENT')),
    CONSTRAINT "ck_banquet_bookings_5" CHECK (contracted_amount >= 0),
    CONSTRAINT "ck_banquet_bookings_6" CHECK (cancellation_fee >= 0),
    CONSTRAINT "ck_banquet_bookings_7" CHECK (cancellation_fee <= contracted_amount),
    CONSTRAINT "ck_banquet_bookings_8" CHECK (reserved_room_block_count >= 0),
    CONSTRAINT "ck_banquet_bookings_9" CHECK (expected_room_nights >= 0),
    CONSTRAINT "ck_banquet_bookings_10" CHECK (released_room_count >= 0),
    CONSTRAINT "ck_banquet_bookings_11" CHECK (pickup_room_count >= 0),
    CONSTRAINT "ck_banquet_bookings_12" CHECK (released_room_count <= reserved_room_block_count),
    CONSTRAINT "ck_banquet_bookings_13" CHECK (pickup_room_count <= reserved_room_block_count - released_room_count),
    CONSTRAINT "ck_banquet_bookings_14" CHECK ((group_checkin_date IS NULL AND group_checkout_date IS NULL) OR (group_checkin_date IS NOT NULL AND group_checkout_date IS NOT NULL AND group_checkout_date > group_checkin_date)),
    CONSTRAINT "ck_banquet_bookings_15" CHECK (quoted_at IS NULL OR quoted_at >= inquiry_at),
    CONSTRAINT "ck_banquet_bookings_16" CHECK (confirmed_at IS NULL OR (quoted_at IS NOT NULL AND confirmed_at >= quoted_at)),
    CONSTRAINT "ck_banquet_bookings_17" CHECK (cancelled_at IS NULL OR cancelled_at >= inquiry_at),
    CONSTRAINT "ck_banquet_bookings_18" CHECK (inquiry_at <= source_updated_at),
    CONSTRAINT "ck_banquet_bookings_19" CHECK (quoted_at IS NULL OR quoted_at <= source_updated_at),
    CONSTRAINT "ck_banquet_bookings_20" CHECK (confirmed_at IS NULL OR confirmed_at <= source_updated_at),
    CONSTRAINT "ck_banquet_bookings_21" CHECK (cancelled_at IS NULL OR cancelled_at <= source_updated_at),
    CONSTRAINT "ck_banquet_bookings_22" CHECK ((booking_status<>'CANCELLED') OR cancelled_at IS NOT NULL),
    CONSTRAINT "ck_banquet_bookings_23" CHECK ((booking_status='CANCELLED') OR cancellation_fee=0),
    CONSTRAINT "ck_banquet_bookings_24" CHECK (is_synthetic=true),
    CONSTRAINT "ck_banquet_bookings_25" CHECK (data_period_status IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
    CONSTRAINT "ck_banquet_bookings_26" CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO')),
    CONSTRAINT "ck_banquet_bookings_27" CHECK ((event_date BETWEEN DATE '2022-01-01' AND DATE '2024-12-31' AND data_period_status='REFERENCE_CALIBRATED') OR (event_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' AND data_period_status='SYNTHETIC_ACTUAL_LIKE') OR (event_date BETWEEN DATE '2026-01-01' AND DATE '2026-07-28' AND data_period_status='YTD_SYNTHETIC') OR (event_date BETWEEN DATE '2026-07-29' AND DATE '2026-12-31' AND data_period_status='FORECAST_SCENARIO'))
);
COMMENT ON TABLE public."banquet_bookings" IS '합성 연회 문의·견적·확정·행사 1건';
COMMENT ON COLUMN public."banquet_bookings"."property_id" IS '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]';
COMMENT ON COLUMN public."banquet_bookings"."banquet_event_id" IS '연회 이벤트 ID. PK [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."customer_id" IS '연회 고객 ID. BQC 합성 source key [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."inquiry_at" IS '문의 시각.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."quoted_at" IS '견적 시각.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."confirmed_at" IS '확정 시각.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."cancelled_at" IS '취소 시각.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."event_date" IS '행사일.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."product_code" IS '연회 상품 코드.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."product_category" IS '행사 분류. WEDDING/CONFERENCE/MEETING/CORPORATE_EVENT/SOCIAL_EVENT [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."expected_guests" IS '예상 인원.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."actual_attendees" IS '실제 참석자.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."lead_source" IS '문의 유입경로.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."sales_owner_team" IS '영업 담당팀.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."booking_status" IS '예약 상태. INQUIRY/QUOTED/TENTATIVE/CONFIRMED/CANCELLED/COMPLETED [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."contracted_amount" IS '계약 금액.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_bookings"."pickup_room_count" IS '픽업 객실 수. 0 이상 [classification=INTERNAL]';
COMMENT ON COLUMN public."banquet_bookings"."released_room_count" IS '반납 객실 수. 0 이상 [classification=INTERNAL]';
COMMENT ON COLUMN public."banquet_bookings"."group_checkout_date" IS '단체 체크아웃일.  [classification=INTERNAL]';
COMMENT ON COLUMN public."banquet_bookings"."group_checkin_date" IS '단체 체크인일.  [classification=INTERNAL]';
COMMENT ON COLUMN public."banquet_bookings"."expected_room_nights" IS '예상 객실박. 연회 연계 객실수요 [classification=INTERNAL]';
COMMENT ON COLUMN public."banquet_bookings"."reserved_room_block_count" IS '예약 객실 블록 수. 연회 연계 객실 블록 [classification=INTERNAL]';
COMMENT ON COLUMN public."banquet_bookings"."cancellation_fee" IS '취소 수수료. 취소 시 별도 금액 [classification=INTERNAL]';
COMMENT ON COLUMN public."banquet_bookings"."data_period_status" IS '기간 상태. 4개 고정 상태 [classification=POLICY]';
COMMENT ON COLUMN public."banquet_bookings"."is_forecast" IS '전망 여부. 2026-07 이후 true [classification=POLICY]';
COMMENT ON COLUMN public."banquet_bookings"."is_synthetic" IS '합성 여부. 항상 true [classification=POLICY]';
COMMENT ON COLUMN public."banquet_bookings"."source_updated_at" IS '원천 수정시각. watermark [classification=SYNTHETIC]';

-- S17 public.banquet_revenue: 합성 연회 상품별 예상·인식·환입 매출 1건
SELECT pg_temp.assert_table_contract('public', 'banquet_revenue', ARRAY['property_id:character varying(64):true', 'revenue_id:character varying(36):true', 'banquet_event_id:character varying(36):true', 'recognized_date:date:true', 'product_code:character varying(32):true', 'product_category:character varying(32):true', 'revenue_amount:numeric(14,2):true', 'reversal_amount:numeric(14,2):true', 'cost_amount:numeric(14,2):true', 'revenue_status:character varying(16):true', 'data_period_status:character varying(32):true', 'is_forecast:boolean:true', 'is_synthetic:boolean:true', 'source_updated_at:timestamp with time zone:true']::text[]);
CREATE TABLE IF NOT EXISTS public."banquet_revenue" (
    "property_id" varchar(64) NOT NULL,
    "revenue_id" varchar(36) NOT NULL PRIMARY KEY,
    "banquet_event_id" varchar(36) NOT NULL,
    "recognized_date" date NOT NULL,
    "product_code" varchar(32) NOT NULL,
    "product_category" varchar(32) NOT NULL,
    "revenue_amount" numeric(14,2) NOT NULL,
    "reversal_amount" numeric(14,2) NOT NULL,
    "cost_amount" numeric(14,2) NOT NULL,
    "revenue_status" varchar(16) NOT NULL,
    "data_period_status" varchar(32) NOT NULL,
    "is_forecast" boolean NOT NULL,
    "is_synthetic" boolean NOT NULL,
    "source_updated_at" timestamptz NOT NULL,
    CONSTRAINT "uq_banquet_revenue_property_id_revenue_id" UNIQUE ("property_id", "revenue_id"),
    CONSTRAINT "ck_banquet_revenue_1" CHECK (product_category IN ('VENUE','FOOD_BEVERAGE','EQUIPMENT','DECORATION','SERVICE','ACCOMMODATION_PACKAGE')),
    CONSTRAINT "ck_banquet_revenue_2" CHECK (revenue_status IN ('EXPECTED','RECOGNIZED','REVERSED')),
    CONSTRAINT "ck_banquet_revenue_3" CHECK (revenue_amount >= 0),
    CONSTRAINT "ck_banquet_revenue_4" CHECK (reversal_amount >= 0),
    CONSTRAINT "ck_banquet_revenue_5" CHECK (cost_amount >= 0),
    CONSTRAINT "ck_banquet_revenue_6" CHECK ((revenue_status='REVERSED' AND revenue_amount=0 AND reversal_amount>0) OR (revenue_status IN ('EXPECTED','RECOGNIZED') AND revenue_amount>0 AND reversal_amount=0)),
    CONSTRAINT "ck_banquet_revenue_7" CHECK (is_synthetic=true),
    CONSTRAINT "ck_banquet_revenue_8" CHECK (data_period_status IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
    CONSTRAINT "ck_banquet_revenue_9" CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO')),
    CONSTRAINT "ck_banquet_revenue_10" CHECK ((recognized_date BETWEEN DATE '2022-01-01' AND DATE '2024-12-31' AND data_period_status='REFERENCE_CALIBRATED') OR (recognized_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31' AND data_period_status='SYNTHETIC_ACTUAL_LIKE') OR (recognized_date BETWEEN DATE '2026-01-01' AND DATE '2026-07-28' AND data_period_status='YTD_SYNTHETIC') OR (recognized_date BETWEEN DATE '2026-07-29' AND DATE '2026-12-31' AND data_period_status='FORECAST_SCENARIO'))
);
COMMENT ON TABLE public."banquet_revenue" IS '합성 연회 상품별 예상·인식·환입 매출 1건';
COMMENT ON COLUMN public."banquet_revenue"."property_id" IS '호텔 속성 ID. SYNTHETIC_HOTEL_001 [classification=POLICY]';
COMMENT ON COLUMN public."banquet_revenue"."revenue_id" IS '매출 ID. PK [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_revenue"."banquet_event_id" IS '연회 이벤트 ID.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_revenue"."recognized_date" IS '매출 인식일.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_revenue"."product_code" IS '상품 코드.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_revenue"."product_category" IS '상품 분류. VENUE/FOOD_BEVERAGE/EQUIPMENT/DECORATION/SERVICE/ACCOMMODATION_PACKAGE [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_revenue"."revenue_amount" IS '매출액.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_revenue"."reversal_amount" IS '매출 환입액. REVERSED 별도 금액 [classification=INTERNAL]';
COMMENT ON COLUMN public."banquet_revenue"."cost_amount" IS '원가.  [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_revenue"."revenue_status" IS '상태. EXPECTED/RECOGNIZED/REVERSED [classification=SYNTHETIC]';
COMMENT ON COLUMN public."banquet_revenue"."data_period_status" IS '기간 상태. 4개 고정 상태 [classification=POLICY]';
COMMENT ON COLUMN public."banquet_revenue"."is_forecast" IS '전망 여부. 2026-07 이후 true [classification=POLICY]';
COMMENT ON COLUMN public."banquet_revenue"."is_synthetic" IS '합성 여부. 항상 true [classification=POLICY]';
COMMENT ON COLUMN public."banquet_revenue"."source_updated_at" IS '원천 수정시각. watermark [classification=SYNTHETIC]';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_banquet_revenue_booking') THEN
    ALTER TABLE public.banquet_revenue
      ADD CONSTRAINT fk_banquet_revenue_booking
      FOREIGN KEY (property_id, banquet_event_id)
      REFERENCES public.banquet_bookings(property_id, banquet_event_id);
  END IF;
END
$$;

CREATE OR REPLACE FUNCTION public.enforce_banquet_revenue_contract()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_status varchar(20);
  v_recognized numeric(14,2);
  v_reversed numeric(14,2);
BEGIN
  SELECT booking_status INTO v_status
  FROM public.banquet_bookings
  WHERE property_id=NEW.property_id AND banquet_event_id=NEW.banquet_event_id;

  IF NEW.revenue_status='RECOGNIZED' AND v_status<>'COMPLETED' THEN
    RAISE EXCEPTION 'BANQUET_REVENUE_STATE_MISMATCH: recognized revenue requires COMPLETED booking';
  END IF;

  IF NEW.revenue_status='REVERSED' THEN
    SELECT coalesce(sum(revenue_amount),0), coalesce(sum(reversal_amount),0)
      INTO v_recognized, v_reversed
    FROM public.banquet_revenue
    WHERE property_id=NEW.property_id
      AND banquet_event_id=NEW.banquet_event_id
      AND revenue_id<>NEW.revenue_id;
    IF v_reversed + NEW.reversal_amount > v_recognized THEN
      RAISE EXCEPTION 'BANQUET_REVERSAL_EXCEEDS_RECOGNIZED';
    END IF;
  END IF;
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_enforce_banquet_revenue_contract ON public.banquet_revenue;
CREATE CONSTRAINT TRIGGER trg_enforce_banquet_revenue_contract
AFTER INSERT OR UPDATE ON public.banquet_revenue
DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION public.enforce_banquet_revenue_contract();

CREATE OR REPLACE VIEW public.banquet_revenue_actual AS
SELECT *
FROM public.banquet_revenue
WHERE is_forecast=false
  AND data_period_status<>'FORECAST_SCENARIO'
  AND revenue_status IN ('RECOGNIZED','REVERSED');

CREATE INDEX IF NOT EXISTS "ix_banquet_bookings_event_date_booking_status" ON public."banquet_bookings" ("event_date", "booking_status");

CREATE INDEX IF NOT EXISTS "ix_banquet_bookings_customer_id_event_date" ON public."banquet_bookings" ("customer_id", "event_date");

CREATE INDEX IF NOT EXISTS "ix_banquet_revenue_banquet_event_id_recognized_date" ON public."banquet_revenue" ("banquet_event_id", "recognized_date");

CREATE INDEX IF NOT EXISTS ix_banquet_revenue_property_event ON public.banquet_revenue(property_id, banquet_event_id);

-- 최소권한 group role. 실제 접속 주체 연결은 별도 보안 구성에서 수행한다.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='banquet_ingest') THEN
    CREATE ROLE "banquet_ingest" NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='banquet_query') THEN
    CREATE ROLE "banquet_query" NOLOGIN;
  END IF;
END
$$;

REVOKE ALL ON DATABASE "hotel_banquet" FROM PUBLIC;
GRANT CONNECT ON DATABASE "hotel_banquet" TO "banquet_ingest", "banquet_query";
GRANT USAGE ON SCHEMA public TO "banquet_ingest", "banquet_query";
GRANT SELECT, INSERT, UPDATE, DELETE ON public."banquet_bookings", public."banquet_revenue" TO "banquet_ingest";
GRANT SELECT ON public."banquet_bookings", public."banquet_revenue" TO "banquet_query";
GRANT SELECT ON public."banquet_revenue_actual" TO "banquet_query";
REVOKE CREATE ON SCHEMA public FROM "banquet_ingest", "banquet_query";
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public."banquet_bookings", public."banquet_revenue" FROM "banquet_query";

-- Read-only negative tests. 관리자 세션에서 실행되며 예상 권한 오류만 PASS로 처리한다.
SET ROLE "banquet_query";
DO $negative$
BEGIN
  BEGIN
    EXECUTE 'INSERT INTO public.banquet_bookings DEFAULT VALUES';
    RAISE EXCEPTION 'READ_ONLY_NEGATIVE_TEST_FAILED: INSERT unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'PASS: banquet_query INSERT blocked';
  END;
  BEGIN
    EXECUTE 'UPDATE public.banquet_bookings SET property_id=property_id WHERE false';
    RAISE EXCEPTION 'READ_ONLY_NEGATIVE_TEST_FAILED: UPDATE unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'PASS: banquet_query UPDATE blocked';
  END;
  BEGIN
    EXECUTE 'DELETE FROM public.banquet_bookings WHERE false';
    RAISE EXCEPTION 'READ_ONLY_NEGATIVE_TEST_FAILED: DELETE unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'PASS: banquet_query DELETE blocked';
  END;
  BEGIN
    EXECUTE 'ALTER TABLE public.banquet_bookings ADD COLUMN __negative_test integer';
    RAISE EXCEPTION 'READ_ONLY_NEGATIVE_TEST_FAILED: DDL unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'PASS: banquet_query DDL blocked';
  END;
END
$negative$;
RESET ROLE;

SELECT count(*) AS source_table_count,
       CASE WHEN count(*)=2 THEN 'PASS' ELSE 'SCHEMA_CONTRACT_MISMATCH' END AS status
FROM information_schema.tables
WHERE table_schema='public' AND table_type='BASE TABLE'
  AND table_name IN ('banquet_bookings','banquet_revenue');

SELECT count(*) AS source_column_count,
       CASE WHEN count(*)=41 THEN 'PASS' ELSE 'SCHEMA_CONTRACT_MISMATCH' END AS status
FROM information_schema.columns
WHERE table_schema='public'
  AND table_name IN ('banquet_bookings','banquet_revenue');

SELECT r.property_id,r.banquet_event_id,
       sum(CASE WHEN revenue_status='RECOGNIZED' THEN revenue_amount ELSE 0 END) AS recognized_amount,
       sum(CASE WHEN revenue_status='REVERSED' THEN reversal_amount ELSE 0 END) AS reversed_amount
FROM public.banquet_revenue r
GROUP BY r.property_id,r.banquet_event_id
HAVING sum(CASE WHEN revenue_status='REVERSED' THEN reversal_amount ELSE 0 END)
     > sum(CASE WHEN revenue_status='RECOGNIZED' THEN revenue_amount ELSE 0 END);

SELECT 'banquet' AS source_id, 'PostgreSQL' AS engine, 'hotel_banquet/public' AS database_schema,
       'banquet_ingest' AS ingestion_role, 'banquet_query' AS query_role,
       'hotel_banquet' AS datahub_platform_instance, 'banquet' AS trino_catalog,
       'schema-v4.6-websql' AS schema_version;
