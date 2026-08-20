-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=banquet_db; target_schema=walkerhill_v4_3
-- domain=BANQUET; script_type=DDL; execution_order=10
-- dependencies=00_postgresql_banquet_preflight_readonly.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814; expected_rows=0
-- execution_default=NOT_RUN; destructive_operation=false
-- evidence=https://www.walkerhill.com/en/convention/Meeting
-- assumption=capacities, attendance, conversion and revenue are synthetic
-- next=20_postgresql_banquet_venue_seed.sql

CREATE SCHEMA walkerhill_v4_3;
CREATE FUNCTION walkerhill_v4_3.v43_u01(p_key text) RETURNS numeric LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
  SELECT ((('x'||substr(encode(sha256(convert_to('20260814|'||p_key,'UTF8')),'hex'),1,15))::bit(60)::bigint)::numeric/1152921504606846976::numeric)
$$;

CREATE TABLE walkerhill_v4_3.banquet_venues (
  venue_id varchar(40) NOT NULL,hotel_code varchar(32) NOT NULL,public_name varchar(160) NOT NULL,
  venue_category varchar(40) NOT NULL,synthetic_capacity integer NOT NULL,public_capacity_note text,
  source_url text NOT NULL,provenance_class varchar(48) NOT NULL,is_active boolean NOT NULL
);
CREATE TABLE walkerhill_v4_3.banquet_bookings (
  banquet_event_id varchar(64) NOT NULL,banquet_customer_id varchar(40) NOT NULL,venue_id varchar(40) NOT NULL,
  inquiry_at timestamptz NOT NULL,quoted_at timestamptz,confirmed_at timestamptz,cancelled_at timestamptz,
  event_date date NOT NULL,event_slot varchar(16) NOT NULL,starts_at timestamptz NOT NULL,ends_at timestamptz NOT NULL,
  event_type varchar(40) NOT NULL,booking_status varchar(24) NOT NULL,
  expected_guests integer NOT NULL,actual_attendees integer,quoted_amount numeric(18,2) NOT NULL,
  contracted_amount numeric(18,2) NOT NULL,deposit_amount numeric(18,2) NOT NULL,
  balance_amount numeric(18,2) NOT NULL,cancellation_fee_amount numeric(18,2) NOT NULL,
  currency_code char(3) NOT NULL,is_synthetic boolean NOT NULL
);
CREATE TABLE walkerhill_v4_3.banquet_status_history (
  status_history_id varchar(72) NOT NULL,banquet_event_id varchar(64) NOT NULL,status_code varchar(24) NOT NULL,
  status_at timestamptz NOT NULL,reason_code varchar(32),is_synthetic boolean NOT NULL
);
CREATE TABLE walkerhill_v4_3.banquet_revenue_lines (
  revenue_line_id varchar(72) NOT NULL,banquet_event_id varchar(64) NOT NULL,recognized_date date NOT NULL,
  revenue_category varchar(40) NOT NULL,gross_amount numeric(18,2) NOT NULL,discount_amount numeric(18,2) NOT NULL,
  reversal_amount numeric(18,2) NOT NULL,recognized_amount numeric(18,2) NOT NULL,cost_amount numeric(18,2) NOT NULL,
  revenue_status varchar(24) NOT NULL,is_synthetic boolean NOT NULL
);
CREATE TABLE walkerhill_v4_3.banquet_room_blocks (
  room_block_id varchar(72) NOT NULL,banquet_event_id varchar(64) NOT NULL,hotel_code varchar(32) NOT NULL,
  checkin_date date NOT NULL,checkout_date date NOT NULL,reserved_room_nights integer NOT NULL,
  pickup_room_nights integer NOT NULL,is_synthetic boolean NOT NULL
);

COMMENT ON TABLE walkerhill_v4_3.banquet_venues IS '공개 미팅·연회 공간명과 합성 수용인원을 관리하는 행사장 마스터';
COMMENT ON COLUMN walkerhill_v4_3.banquet_venues.venue_id IS '행사장의 합성 식별 코드';
COMMENT ON COLUMN walkerhill_v4_3.banquet_venues.hotel_code IS '행사장이 귀속되는 합성 호텔 코드';
COMMENT ON COLUMN walkerhill_v4_3.banquet_venues.public_name IS '공식 컨벤션 페이지에서 확인한 공개 행사장명';
COMMENT ON COLUMN walkerhill_v4_3.banquet_venues.venue_category IS 'GRAND_BALLROOM·MEETING_ROOM·OUTDOOR 등 공간 유형';
COMMENT ON COLUMN walkerhill_v4_3.banquet_venues.synthetic_capacity IS '생성 부하에 쓰는 합성 최대 인원. 공식 수용인원과 동일하다고 보장하지 않음';
COMMENT ON COLUMN walkerhill_v4_3.banquet_venues.public_capacity_note IS '공개 페이지의 수용인원 표현 또는 해석 주의사항';
COMMENT ON COLUMN walkerhill_v4_3.banquet_venues.source_url IS '행사장 명칭 근거 URL';
COMMENT ON COLUMN walkerhill_v4_3.banquet_venues.provenance_class IS '공개 명칭과 합성 수용인원의 출처 분류';
COMMENT ON COLUMN walkerhill_v4_3.banquet_venues.is_active IS '생성 기간 종료일 현재 예약 가능 여부';

COMMENT ON TABLE walkerhill_v4_3.banquet_bookings IS '문의·견적·확정·취소 시각과 행사일·참석자·계약액을 재현한 합성 연회 예약';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.banquet_event_id IS '연회 예약의 결정적 합성 식별자';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.banquet_customer_id IS '개인정보가 아닌 합성 연회 고객 식별자';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.venue_id IS '예약 행사장 식별 코드';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.inquiry_at IS '최초 연회 문의 시각';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.quoted_at IS '견적을 제시한 시각. 문의 종료는 NULL';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.confirmed_at IS '계약 확정 시각. 미확정은 NULL';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.cancelled_at IS '취소 시각. 취소되지 않았으면 NULL';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.event_date IS '행사가 실제 또는 예정된 영업일';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.event_slot IS 'MORNING·AFTERNOON·EVENING 중 행사장 중복 방지용 합성 시간대';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.starts_at IS '행사장 점유가 시작되는 Asia/Seoul 기준 합성 시각';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.ends_at IS '행사장 점유가 종료되는 Asia/Seoul 기준 합성 시각';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.event_type IS 'WEDDING·CORPORATE·SOCIAL·CONFERENCE 등 합성 행사 유형';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.booking_status IS 'COMPLETED·CANCELLED 중 2026-08-31 스냅샷 최종 상태. INQUIRY·QUOTED·CONFIRMED는 이력에 보존';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.expected_guests IS '견적 단계의 합성 예상 참석자 수';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.actual_attendees IS '행사 완료 후 합성 실제 참석자 수. 미완료는 NULL';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.quoted_amount IS '견적 단계에 제시한 합성 원화 금액';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.contracted_amount IS '확정 계약의 합성 원화 금액';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.deposit_amount IS '확정 시 수납한 합성 계약금. 현 모델은 계약액의 30%';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.balance_amount IS '행사 완료 시 수납한 합성 잔금. 취소 건은 0';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.cancellation_fee_amount IS '취소 계약에서 인식한 합성 위약금. 완료 건은 0';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.currency_code IS '계약 통화 ISO 코드이며 현재 KRW';
COMMENT ON COLUMN walkerhill_v4_3.banquet_bookings.is_synthetic IS '실제 고객 계약이 아닌 합성 행임을 나타내며 항상 true';

COMMENT ON TABLE walkerhill_v4_3.banquet_status_history IS '문의부터 견적·확정·취소·완료까지 연회 예약 상태 전이를 보존하는 합성 이력';
COMMENT ON COLUMN walkerhill_v4_3.banquet_status_history.status_history_id IS '연회 상태 이력의 결정적 합성 식별자';
COMMENT ON COLUMN walkerhill_v4_3.banquet_status_history.banquet_event_id IS '상태가 변경된 합성 연회 예약 식별자';
COMMENT ON COLUMN walkerhill_v4_3.banquet_status_history.status_code IS '해당 시각부터 적용되는 연회 예약 상태';
COMMENT ON COLUMN walkerhill_v4_3.banquet_status_history.status_at IS '연회 예약 상태 전이 시각';
COMMENT ON COLUMN walkerhill_v4_3.banquet_status_history.reason_code IS '취소·보류 등 상태 변경의 합성 사유';
COMMENT ON COLUMN walkerhill_v4_3.banquet_status_history.is_synthetic IS '실제 영업 이력이 아닌 합성 행임을 나타내며 항상 true';

COMMENT ON TABLE walkerhill_v4_3.banquet_revenue_lines IS '식음·대관·장비·서비스 매출과 할인·환입·원가를 분리한 합성 연회 매출 원장';
COMMENT ON COLUMN walkerhill_v4_3.banquet_revenue_lines.revenue_line_id IS '연회 매출 항목의 결정적 합성 식별자';
COMMENT ON COLUMN walkerhill_v4_3.banquet_revenue_lines.banquet_event_id IS '매출이 귀속되는 합성 연회 예약 식별자';
COMMENT ON COLUMN walkerhill_v4_3.banquet_revenue_lines.recognized_date IS '매출을 영업실적으로 인식한 날짜';
COMMENT ON COLUMN walkerhill_v4_3.banquet_revenue_lines.revenue_category IS 'FOOD·BEVERAGE·VENUE·EQUIPMENT·SERVICE 중 매출 범주';
COMMENT ON COLUMN walkerhill_v4_3.banquet_revenue_lines.gross_amount IS '할인·환입 전 합성 매출 총액';
COMMENT ON COLUMN walkerhill_v4_3.banquet_revenue_lines.discount_amount IS '계약·프로모션 합성 할인액';
COMMENT ON COLUMN walkerhill_v4_3.banquet_revenue_lines.reversal_amount IS '취소·정정으로 환입한 합성 금액';
COMMENT ON COLUMN walkerhill_v4_3.banquet_revenue_lines.recognized_amount IS 'gross-discount-reversal로 계산한 합성 인식매출';
COMMENT ON COLUMN walkerhill_v4_3.banquet_revenue_lines.cost_amount IS '품목별 합성 원가율로 계산한 분석용 원가';
COMMENT ON COLUMN walkerhill_v4_3.banquet_revenue_lines.revenue_status IS 'RECOGNIZED·REVERSED 등 매출 인식 상태';
COMMENT ON COLUMN walkerhill_v4_3.banquet_revenue_lines.is_synthetic IS '실제 회계자료가 아닌 합성 행임을 나타내며 항상 true';

COMMENT ON TABLE walkerhill_v4_3.banquet_room_blocks IS '연회·단체 행사와 PMS 객실 수요를 연결하는 호텔별 합성 객실 블록';
COMMENT ON COLUMN walkerhill_v4_3.banquet_room_blocks.room_block_id IS '객실 블록의 결정적 합성 식별자';
COMMENT ON COLUMN walkerhill_v4_3.banquet_room_blocks.banquet_event_id IS '객실 블록을 발생시킨 합성 연회 예약 식별자';
COMMENT ON COLUMN walkerhill_v4_3.banquet_room_blocks.hotel_code IS '객실을 제공하는 합성 호텔 코드';
COMMENT ON COLUMN walkerhill_v4_3.banquet_room_blocks.checkin_date IS '단체 객실 블록 체크인 날짜';
COMMENT ON COLUMN walkerhill_v4_3.banquet_room_blocks.checkout_date IS '단체 객실 블록 체크아웃 날짜';
COMMENT ON COLUMN walkerhill_v4_3.banquet_room_blocks.reserved_room_nights IS '계약상 확보된 합성 객실박 수';
COMMENT ON COLUMN walkerhill_v4_3.banquet_room_blocks.pickup_room_nights IS '실제 예약으로 전환된 합성 객실박 수';
COMMENT ON COLUMN walkerhill_v4_3.banquet_room_blocks.is_synthetic IS '실제 단체 계약이 아닌 합성 행임을 나타내며 항상 true';
