-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=pms_db; target_schema=walkerhill_v4_3
-- domain=REFERENCE; script_type=DDL; execution_order=10
-- dependencies=00_postgresql_pms_preflight_readonly.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814; expected_rows=0
-- execution_default=NOT_RUN; destructive_operation=false
-- evidence=https://www.walkerhill.com/kr/ ; https://www.sknetworks.co.kr/business/hotel-and-resort
-- assumption=all capacities and effect sizes are synthetic, never official operating facts
-- next=11_postgresql_pms_operation_ddl.sql

CREATE SCHEMA walkerhill_v4_3;

CREATE FUNCTION walkerhill_v4_3.v43_u01(p_key text)
RETURNS numeric
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
  SELECT ((('x' || substr(encode(sha256(convert_to('20260814|' || p_key, 'UTF8')), 'hex'), 1, 15))::bit(60)::bigint)::numeric
          / 1152921504606846976::numeric)
$$;

CREATE FUNCTION walkerhill_v4_3.v43_journey_pos_amount(p_journey_seq integer,p_meal_no integer)
RETURNS numeric
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
  WITH plan AS (
    SELECT CASE mod(p_journey_seq-1,3)
             WHEN 0 THEN CASE p_meal_no WHEN 1 THEN 2 WHEN 2 THEN 6 ELSE 3 END
             WHEN 1 THEN CASE p_meal_no WHEN 1 THEN 7 WHEN 2 THEN 10 ELSE 8 END
             ELSE CASE p_meal_no WHEN 1 THEN 11 WHEN 2 THEN 12 ELSE 11 END
           END AS outlet_seq,
           DATE '2024-01-01' + floor((p_journey_seq-1)/3.0)::int*3
             + CASE WHEN p_meal_no=1 THEN 0 ELSE 1 END AS business_date
  ), priced AS (
    SELECT p.*,
           'MI_'||lpad(p.outlet_seq::text,2,'0')||'_01' AS item_code,
           CASE WHEN p.outlet_seq IN (2,3,7,8) THEN 68000::numeric
                WHEN p.outlet_seq=11 THEN 26000::numeric ELSE 42000::numeric END AS base_price
    FROM plan p
  ), gross AS (
    SELECT round((base_price*(0.88+0.12*walkerhill_v4_3.v43_u01('menu-price|'||item_code))
             *CASE WHEN business_date>=DATE '2025-01-01'
                    THEN 1.03+0.04*walkerhill_v4_3.v43_u01('menu-reprice|'||item_code) ELSE 1 END
             *CASE WHEN business_date>=DATE '2026-01-01'
                    THEN 1.025+0.035*walkerhill_v4_3.v43_u01('menu-reprice-2026|'||item_code) ELSE 1 END)/1000,0)*1000 AS amount
    FROM priced
  ), charged AS (
    SELECT amount,round(amount*0.10,0) AS service_amount FROM gross
  )
  SELECT amount+service_amount+round((amount+service_amount)*0.10,0) FROM charged
$$;

CREATE TABLE walkerhill_v4_3.hotel_entities (
  resort_id varchar(32) NOT NULL,
  hotel_code varchar(32) NOT NULL,
  parent_hotel_code varchar(32),
  public_name varchar(160) NOT NULL,
  entity_type varchar(32) NOT NULL,
  source_url text NOT NULL,
  source_as_of date NOT NULL,
  synthetic_room_capacity integer NOT NULL,
  inventory_scope varchar(48) NOT NULL,
  reporting_scope varchar(48) NOT NULL,
  effective_from date NOT NULL,
  effective_to date,
  provenance_class varchar(48) NOT NULL,
  is_active boolean NOT NULL
);

CREATE TABLE walkerhill_v4_3.calendar_daily (
  business_date date NOT NULL,
  day_of_week smallint NOT NULL,
  is_weekend boolean NOT NULL,
  room_rate_day_type varchar(16) NOT NULL,
  is_holiday boolean NOT NULL,
  holiday_name varchar(100),
  season_code varchar(16) NOT NULL,
  synthetic_weather_score numeric(6,4) NOT NULL,
  synthetic_demand_index numeric(8,4) NOT NULL,
  promotion_code varchar(64),
  provenance_class varchar(48) NOT NULL
);

CREATE TABLE walkerhill_v4_3.evidence_registry (
  evidence_id varchar(40) NOT NULL,
  evidence_grade char(1) NOT NULL,
  publisher varchar(160) NOT NULL,
  title varchar(300) NOT NULL,
  source_url text NOT NULL,
  published_date date,
  accessed_at timestamptz NOT NULL,
  supported_fact text NOT NULL,
  affected_table varchar(160) NOT NULL,
  affected_column varchar(160) NOT NULL,
  modeling_rule text NOT NULL,
  confidence numeric(5,4) NOT NULL,
  notes text
);

CREATE TABLE walkerhill_v4_3.event_master (
  event_id varchar(48) NOT NULL,
  event_name varchar(200) NOT NULL,
  event_type varchar(48) NOT NULL,
  start_date date NOT NULL,
  end_date date NOT NULL,
  location varchar(200) NOT NULL,
  estimated_attendance integer,
  evidence_id varchar(40) NOT NULL,
  fact_or_assumption varchar(16) NOT NULL,
  confidence numeric(5,4) NOT NULL
);

CREATE TABLE walkerhill_v4_3.hotel_event_effect (
  event_id varchar(48) NOT NULL,
  hotel_code varchar(32) NOT NULL,
  domain varchar(32) NOT NULL,
  metric_name varchar(64) NOT NULL,
  lead_days smallint NOT NULL,
  lag_days smallint NOT NULL,
  effect_curve varchar(24) NOT NULL,
  uplift_min numeric(8,4) NOT NULL,
  uplift_mode numeric(8,4) NOT NULL,
  uplift_max numeric(8,4) NOT NULL,
  capacity_limit numeric(8,4) NOT NULL,
  confidence numeric(5,4) NOT NULL,
  evidence_id varchar(40) NOT NULL
);

COMMENT ON TABLE walkerhill_v4_3.hotel_entities IS '워커힐 리조트와 Grand·Vista·Douglas의 보고 범위 및 합성 객실 공급을 분리한 호텔 계층 마스터';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.resort_id IS '모든 호텔 엔터티를 묶는 합성 리조트 식별자';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.hotel_code IS 'GRAND·VISTA·DOUGLAS 등 호텔 엔터티 코드';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.parent_hotel_code IS '브랜드 중첩을 표현하는 상위 호텔 코드. 독립 최상위는 NULL';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.public_name IS '워커힐 공식 채널에서 확인한 공개 브랜드명';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.entity_type IS 'RESORT·HOTEL·SUB_BRAND 등 계층 유형';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.source_url IS '브랜드명과 운영 범위의 공개 근거 URL';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.source_as_of IS '공개 근거를 확인한 기준일';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.synthetic_room_capacity IS '생성 부하와 점유율 모델에 쓰는 합성 객실 수. 공식 객실 수가 아님';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.inventory_scope IS '객실 재고를 중복 계산하지 않기 위한 합성 재고 소유 범위';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.reporting_scope IS '매출·KPI 보고 시 포함되는 엔터티 범위';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.effective_from IS '해당 계층 관계가 유효해지는 시작일';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.effective_to IS '계층 관계 종료일. 현재 유효하면 NULL';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.provenance_class IS 'OFFICIAL_NAME_SYNTHETIC_CAPACITY 등 사실과 가정을 구분하는 출처 등급';
COMMENT ON COLUMN walkerhill_v4_3.hotel_entities.is_active IS '생성 기간 종료일 현재 분석 대상 여부';

COMMENT ON TABLE walkerhill_v4_3.calendar_daily IS '2024~2025 영업일별 주말·공휴일·계절과 합성 기상·수요·프로모션 공통 드라이버';
COMMENT ON COLUMN walkerhill_v4_3.calendar_daily.business_date IS '모든 도메인의 한국 영업일 결합 키';
COMMENT ON COLUMN walkerhill_v4_3.calendar_daily.day_of_week IS 'ISO 기준 요일 번호. 월요일 1, 일요일 7';
COMMENT ON COLUMN walkerhill_v4_3.calendar_daily.is_weekend IS '시설 운영·일반 달력 기준의 토요일 또는 일요일 여부';
COMMENT ON COLUMN walkerhill_v4_3.calendar_daily.room_rate_day_type IS '객실 판매 요일 구분. 워커힐 공개 요금표의 일~목·금·토 구분을 반영한 SUN_THU·FRIDAY·SATURDAY';
COMMENT ON COLUMN walkerhill_v4_3.calendar_daily.is_holiday IS '대한민국 공휴일 캘린더에 포함된 날짜 여부';
COMMENT ON COLUMN walkerhill_v4_3.calendar_daily.holiday_name IS '공휴일인 경우의 한국어 휴일명';
COMMENT ON COLUMN walkerhill_v4_3.calendar_daily.season_code IS 'SPRING·SUMMER·AUTUMN·WINTER 계절 코드';
COMMENT ON COLUMN walkerhill_v4_3.calendar_daily.synthetic_weather_score IS '0~1 범위의 합성 야외활동 적합도. 실제 관측 기상이 아님';
COMMENT ON COLUMN walkerhill_v4_3.calendar_daily.synthetic_demand_index IS '평시 1을 기준으로 계절·주말·행사 수요를 결합한 합성 지수';
COMMENT ON COLUMN walkerhill_v4_3.calendar_daily.promotion_code IS '해당 영업일에 적용한 합성 프로모션 코드';
COMMENT ON COLUMN walkerhill_v4_3.calendar_daily.provenance_class IS '캘린더 사실과 모델 가정의 출처 분류';

COMMENT ON TABLE walkerhill_v4_3.evidence_registry IS '공개 자료가 어떤 테이블·컬럼과 모델링 규칙을 뒷받침하는지 추적하는 근거 레지스트리';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.evidence_id IS '공개 근거 자료의 내부 식별 코드';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.evidence_grade IS 'A 공식 1차 자료, B 공공·공식 보조자료, C 모델 참고자료';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.publisher IS '근거를 공개한 기관 또는 회사명';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.title IS '공개 페이지·보도자료·통계의 제목';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.source_url IS '검증자가 재확인할 수 있는 원문 URL';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.published_date IS '근거 자료의 공개일. 확인되지 않으면 NULL';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.accessed_at IS '근거 페이지를 확인한 한국 표준시 시각';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.supported_fact IS '자료가 직접 뒷받침하는 사실의 제한된 범위';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.affected_table IS '근거를 사용하는 V4.3 대상 테이블';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.affected_column IS '근거 또는 규칙의 직접 영향 컬럼';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.modeling_rule IS '공개 사실을 합성 데이터 파라미터로 변환한 규칙';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.confidence IS '0~1 범위의 근거·모델 신뢰도';
COMMENT ON COLUMN walkerhill_v4_3.evidence_registry.notes IS '충돌·한계·해석 주의사항';

COMMENT ON TABLE walkerhill_v4_3.event_master IS '공개 행사·상품 출시와 명시적 합성 외부 이벤트의 기간 및 근거를 관리하는 마스터';
COMMENT ON COLUMN walkerhill_v4_3.event_master.event_id IS '이벤트의 안정적 시나리오 코드';
COMMENT ON COLUMN walkerhill_v4_3.event_master.event_name IS '공개 행사명 또는 합성 시나리오 표시명';
COMMENT ON COLUMN walkerhill_v4_3.event_master.event_type IS 'MEGA_CONTENT·SEASONAL_PACKAGE·FACILITY_OPENING 등 이벤트 유형';
COMMENT ON COLUMN walkerhill_v4_3.event_master.start_date IS '수요 효과 적용 시작일';
COMMENT ON COLUMN walkerhill_v4_3.event_master.end_date IS '수요 효과 적용 종료일';
COMMENT ON COLUMN walkerhill_v4_3.event_master.location IS '행사 또는 상품 효과가 발생하는 합성 공간 범위';
COMMENT ON COLUMN walkerhill_v4_3.event_master.estimated_attendance IS '공개 근거가 없으면 NULL인 예상 참석자 수';
COMMENT ON COLUMN walkerhill_v4_3.event_master.evidence_id IS '이벤트 존재·시점 근거 레지스트리 식별자';
COMMENT ON COLUMN walkerhill_v4_3.event_master.fact_or_assumption IS 'FACT·MIXED·ASSUMPTION 중 사실/가정 구분';
COMMENT ON COLUMN walkerhill_v4_3.event_master.confidence IS '이벤트 시점과 범위에 대한 0~1 신뢰도';

COMMENT ON TABLE walkerhill_v4_3.hotel_event_effect IS '동일 이벤트가 호텔과 영업 도메인마다 서로 다른 상승폭·선행·후행 효과를 갖도록 한 시나리오 계약';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.event_id IS 'event_master의 이벤트 코드';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.hotel_code IS '효과를 적용받는 합성 호텔 코드';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.domain IS 'ROOMS·FNB·BANQUET·FACILITY 중 영향 도메인';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.metric_name IS 'OCCUPANCY_RATE·ADR·ORDER_COUNT·BOOKING_COUNT·USAGE_COUNT 중 대상 지표';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.lead_days IS '이벤트 시작 전에 수요가 반응하는 합성 일수';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.lag_days IS '이벤트 종료 후 효과가 남는 합성 일수';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.effect_curve IS 'TRIANGULAR·DECAY 등 기간 내 효과 곡선';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.uplift_min IS '삼각 시나리오의 최소 상대 상승률';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.uplift_mode IS '삼각 시나리오의 최빈 상대 상승률';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.uplift_max IS '삼각 시나리오의 최대 상대 상승률';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.capacity_limit IS '점유·이용량이 초과하지 못하는 합성 포화 상한';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.confidence IS '효과 크기 가정의 0~1 신뢰도';
COMMENT ON COLUMN walkerhill_v4_3.hotel_event_effect.evidence_id IS '이벤트 존재를 뒷받침하는 근거 코드. 상승폭 자체의 실측 근거는 아님';
