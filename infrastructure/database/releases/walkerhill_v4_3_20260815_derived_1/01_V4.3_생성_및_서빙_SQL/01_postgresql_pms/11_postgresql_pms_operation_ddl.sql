-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=pms_db; target_schema=walkerhill_v4_3
-- domain=PMS; script_type=DDL; execution_order=11
-- dependencies=10_postgresql_pms_reference_ddl.sql
-- period=2024-01-01..2026-08-31; base_seed=20260814; expected_rows=0
-- execution_default=NOT_RUN; destructive_operation=false
-- assumption=room counts, rates, occupancy, guest behavior and revenue are synthetic
-- next=20_postgresql_pms_reference_seed.sql

CREATE TABLE walkerhill_v4_3.pms_room_types (
  hotel_code varchar(32) NOT NULL,
  room_type_code varchar(40) NOT NULL,
  public_name varchar(160) NOT NULL,
  synthetic_room_count integer NOT NULL,
  synthetic_max_occupancy smallint NOT NULL,
  synthetic_base_rate_krw numeric(18,2) NOT NULL,
  source_url text NOT NULL,
  provenance_class varchar(48) NOT NULL,
  is_active boolean NOT NULL
);

CREATE TABLE walkerhill_v4_3.pms_rooms (
  hotel_code varchar(32) NOT NULL,
  room_id varchar(64) NOT NULL,
  room_type_code varchar(40) NOT NULL,
  floor_no smallint NOT NULL,
  is_active boolean NOT NULL,
  provenance_class varchar(48) NOT NULL
);

CREATE TABLE walkerhill_v4_3.pms_guests (
  guest_id varchar(40) NOT NULL,
  guest_segment varchar(24) NOT NULL,
  country_group varchar(24) NOT NULL,
  created_at timestamptz NOT NULL,
  is_synthetic boolean NOT NULL
);

CREATE TABLE walkerhill_v4_3.pms_room_out_of_order_periods (
  out_of_order_id varchar(64) NOT NULL,
  room_id varchar(64) NOT NULL,
  started_at timestamptz NOT NULL,
  ended_at timestamptz NOT NULL,
  reason_code varchar(32) NOT NULL,
  work_order_ref varchar(64) NOT NULL,
  is_synthetic boolean NOT NULL
);

CREATE TABLE walkerhill_v4_3.pms_room_inventory_daily (
  hotel_code varchar(32) NOT NULL,
  business_date date NOT NULL,
  room_type_code varchar(40) NOT NULL,
  physical_rooms integer NOT NULL,
  out_of_order_rooms integer NOT NULL,
  house_use_rooms integer NOT NULL,
  available_room_nights integer NOT NULL,
  is_forecast boolean NOT NULL,
  provenance_class varchar(48) NOT NULL
);

CREATE TABLE walkerhill_v4_3.pms_reservations (
  reservation_id varchar(64) NOT NULL,
  guest_id varchar(40) NOT NULL,
  hotel_code varchar(32) NOT NULL,
  room_type_code varchar(40) NOT NULL,
  assigned_room_id varchar(64),
  booked_at timestamptz NOT NULL,
  checkin_date date NOT NULL,
  checkout_date date NOT NULL,
  booking_channel varchar(24) NOT NULL,
  market_segment varchar(24) NOT NULL,
  reservation_status varchar(24) NOT NULL,
  cancelled_at timestamptz,
  cancellation_reason_code varchar(32),
  banquet_event_id varchar(64),
  quoted_room_rate numeric(18,2) NOT NULL,
  discount_amount numeric(18,2) NOT NULL,
  booked_amount numeric(18,2) NOT NULL,
  currency_code char(3) NOT NULL,
  is_forecast boolean NOT NULL,
  is_synthetic boolean NOT NULL
);

CREATE TABLE walkerhill_v4_3.pms_reservation_status_history (
  status_history_id varchar(72) NOT NULL,
  reservation_id varchar(64) NOT NULL,
  status_code varchar(24) NOT NULL,
  status_at timestamptz NOT NULL,
  reason_code varchar(32),
  source_process varchar(32) NOT NULL,
  is_synthetic boolean NOT NULL
);

CREATE TABLE walkerhill_v4_3.pms_stays (
  stay_id varchar(64) NOT NULL,
  reservation_id varchar(64) NOT NULL,
  guest_id varchar(40) NOT NULL,
  hotel_code varchar(32) NOT NULL,
  room_id varchar(64) NOT NULL,
  room_type_code varchar(40) NOT NULL,
  actual_checkin_at timestamptz NOT NULL,
  actual_checkout_at timestamptz NOT NULL,
  occupied_room_nights integer NOT NULL,
  guest_count smallint NOT NULL,
  room_revenue numeric(18,2) NOT NULL,
  other_room_charges numeric(18,2) NOT NULL,
  stay_status varchar(24) NOT NULL,
  complimentary_flag boolean NOT NULL,
  house_use_flag boolean NOT NULL,
  is_forecast boolean NOT NULL,
  is_synthetic boolean NOT NULL
);

CREATE TABLE walkerhill_v4_3.pms_stay_nights (
  stay_id varchar(64) NOT NULL,
  reservation_id varchar(64) NOT NULL,
  business_date date NOT NULL,
  room_rate_day_type varchar(16) NOT NULL,
  gross_room_rate numeric(18,2) NOT NULL,
  discount_amount numeric(18,2) NOT NULL,
  net_room_revenue numeric(18,2) NOT NULL,
  event_id varchar(48),
  is_synthetic boolean NOT NULL
);

CREATE TABLE walkerhill_v4_3.pms_folio_postings (
  folio_posting_id varchar(72) NOT NULL,
  stay_id varchar(64) NOT NULL,
  reservation_id varchar(64) NOT NULL,
  posted_at timestamptz NOT NULL,
  posting_type varchar(32) NOT NULL,
  source_system varchar(24),
  source_transaction_id varchar(64),
  gross_amount numeric(18,2) NOT NULL,
  discount_amount numeric(18,2) NOT NULL,
  service_charge_amount numeric(18,2) NOT NULL,
  tax_amount numeric(18,2) NOT NULL,
  refund_amount numeric(18,2) NOT NULL,
  net_amount numeric(18,2) NOT NULL,
  currency_code char(3) NOT NULL,
  posting_status varchar(20) NOT NULL,
  is_synthetic boolean NOT NULL
);

COMMENT ON TABLE walkerhill_v4_3.pms_room_types IS '호텔별 공개 객실 유형명에 합성 객실 수와 기준요금을 연결한 객실 유형 마스터';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_types.hotel_code IS '객실 유형을 운영하는 합성 호텔 코드';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_types.room_type_code IS '호텔 내부에서 유일한 합성 객실 유형 코드';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_types.public_name IS '공식 객실 페이지에서 확인한 공개 객실 유형명';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_types.synthetic_room_count IS '생성용 객실 수 가정. 공식 보유 객실 수가 아님';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_types.synthetic_max_occupancy IS '객실 유형별 합성 최대 투숙 인원. 공식 정원이 아니며 생성·검증용 가정';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_types.synthetic_base_rate_krw IS '가격 분포 중심값으로 쓰는 합성 원화 기준요금';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_types.source_url IS '객실 유형명 공개 근거 URL';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_types.provenance_class IS '공개 명칭과 합성 수량·가격의 출처 분류';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_types.is_active IS '생성 기간 종료일 현재 판매 대상 여부';

COMMENT ON TABLE walkerhill_v4_3.pms_rooms IS '중복 없는 객실 배정과 고장 기간 검증을 위한 개별 합성 객실 마스터';
COMMENT ON COLUMN walkerhill_v4_3.pms_rooms.hotel_code IS '객실이 속한 합성 호텔 코드';
COMMENT ON COLUMN walkerhill_v4_3.pms_rooms.room_id IS '실제 객실번호와 무관한 합성 객실 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_rooms.room_type_code IS '같은 hotel_code 안에서 참조하는 객실 유형 코드';
COMMENT ON COLUMN walkerhill_v4_3.pms_rooms.floor_no IS '동선·배정 분산을 위한 합성 층 번호';
COMMENT ON COLUMN walkerhill_v4_3.pms_rooms.is_active IS '생성 기간 종료일 현재 운용 객실 여부';
COMMENT ON COLUMN walkerhill_v4_3.pms_rooms.provenance_class IS '객실 행이 전적으로 합성임을 나타내는 출처 분류';

COMMENT ON TABLE walkerhill_v4_3.pms_guests IS '이름·연락처·주소 없이 세그먼트만 보유하는 비식별 합성 투숙객 마스터';
COMMENT ON COLUMN walkerhill_v4_3.pms_guests.guest_id IS '실제 고객과 연결되지 않는 합성 투숙객 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_guests.guest_segment IS 'LEISURE·BUSINESS·FAMILY·MEMBER 등 합성 수요 세그먼트';
COMMENT ON COLUMN walkerhill_v4_3.pms_guests.country_group IS 'DOMESTIC·ASIA·AMERICAS_EUROPE 등 비식별 지역 그룹';
COMMENT ON COLUMN walkerhill_v4_3.pms_guests.created_at IS '합성 고객 레코드 최초 생성 시각';
COMMENT ON COLUMN walkerhill_v4_3.pms_guests.is_synthetic IS '실제 고객자료가 아닌 합성 행임을 나타내며 항상 true';

COMMENT ON TABLE walkerhill_v4_3.pms_room_out_of_order_periods IS '정비·안전·객실 상태로 판매 중지된 합성 객실 기간 이력';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_out_of_order_periods.out_of_order_id IS '판매중지 기간의 결정적 합성 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_out_of_order_periods.room_id IS '판매 중지된 합성 객실 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_out_of_order_periods.started_at IS '객실 판매중지 시작 시각';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_out_of_order_periods.ended_at IS '객실 판매중지 종료 시각';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_out_of_order_periods.reason_code IS 'MAINTENANCE·SAFETY·DEEP_CLEAN 등 합성 중지 사유';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_out_of_order_periods.work_order_ref IS '향후 시설 작업지시와 연결할 합성 참조 코드';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_out_of_order_periods.is_synthetic IS '실제 작업지시가 아닌 합성 이력임을 나타내며 항상 true';

COMMENT ON TABLE walkerhill_v4_3.pms_room_inventory_daily IS '호텔·영업일·객실유형 단위 물리 객실, 고장, 하우스유즈 및 판매 가능 객실박 스냅샷';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_inventory_daily.hotel_code IS '재고가 속한 합성 호텔 코드';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_inventory_daily.business_date IS '객실 재고가 적용되는 영업일';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_inventory_daily.room_type_code IS '재고를 집계한 호텔 내 객실 유형 코드';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_inventory_daily.physical_rooms IS '합성 객실 마스터의 물리 객실 수';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_inventory_daily.out_of_order_rooms IS '해당 날짜 판매중지 기간과 겹치는 객실 수';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_inventory_daily.house_use_rooms IS '직원·운영 목적으로 판매하지 않는 합성 객실 수';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_inventory_daily.available_room_nights IS 'physical-out_of_order-house_use로 계산한 판매 가능 객실박';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_inventory_daily.is_forecast IS '2026-08-31 종료 합성 시나리오에 포함된 행은 false. 패키지 생성일 현재 실제 관측 실적이라는 뜻이 아니며 향후 별도 예측 확장만 true';
COMMENT ON COLUMN walkerhill_v4_3.pms_room_inventory_daily.provenance_class IS '객실 공급이 합성 가정임을 나타내는 출처 분류';

COMMENT ON TABLE walkerhill_v4_3.pms_reservations IS '예약 시점부터 취소·확정 상태, 채널, 투숙일, 견적요금까지 재현한 합성 예약 원장';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.reservation_id IS '예약의 결정적 합성 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.guest_id IS '예약 대표 합성 투숙객 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.hotel_code IS '예약 대상 합성 호텔 코드';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.room_type_code IS '예약한 호텔 내 객실 유형 코드';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.assigned_room_id IS '체크인 또는 사전배정된 합성 객실. 미배정·취소는 NULL';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.booked_at IS '한국 표준시 오프셋을 포함한 예약 생성 시각';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.checkin_date IS '예약 체크인 영업일';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.checkout_date IS '예약 체크아웃 영업일. 숙박일 계산에서 제외되는 끝 경계';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.booking_channel IS 'DIRECT_WEB·OTA·CORPORATE·PHONE 등 합성 유입 채널';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.market_segment IS 'LEISURE·BUSINESS·GROUP 등 합성 시장 세그먼트';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.reservation_status IS 'BOOKED·CONFIRMED·CANCELLED·NO_SHOW·CHECKED_OUT 중 최종 상태';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.cancelled_at IS '취소된 경우의 취소 시각';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.cancellation_reason_code IS '고객·가격·일정 등 합성 취소 사유 코드';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.banquet_event_id IS '연회 객실 블록에서 파생된 경우의 교차 엔진 논리 키';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.quoted_room_rate IS '1박 기준 합성 제시 객실요금';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.discount_amount IS '전체 예약에 적용한 합성 객실 할인액';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.booked_amount IS '숙박일수와 할인을 반영한 합성 예약 객실금액';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.currency_code IS '금액 통화 ISO 코드이며 현재 KRW';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.is_forecast IS '2026-08-31 종료 합성 시나리오 행과 향후 별도 예측 예약을 구분하는 플래그. false는 실제 워커힐 실적을 뜻하지 않음';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservations.is_synthetic IS '실제 예약이 아닌 합성 행임을 나타내며 항상 true';

COMMENT ON TABLE walkerhill_v4_3.pms_reservation_status_history IS '예약 생성·확정·취소·체크인·체크아웃 전이를 시간순으로 보존하는 합성 상태 이력';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservation_status_history.status_history_id IS '예약 상태 이력의 결정적 합성 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservation_status_history.reservation_id IS '상태가 변경된 합성 예약 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservation_status_history.status_code IS '해당 시각 이후 적용되는 예약 상태';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservation_status_history.status_at IS '상태 전이가 발생한 한국 표준시 시각';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservation_status_history.reason_code IS '취소·노쇼 등 상태 변경의 합성 사유';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservation_status_history.source_process IS 'BOOKING·FRONT_DESK·NIGHT_AUDIT 등 상태를 만든 합성 업무 프로세스';
COMMENT ON COLUMN walkerhill_v4_3.pms_reservation_status_history.is_synthetic IS '실제 예약 로그가 아닌 합성 이력임을 나타내며 항상 true';

COMMENT ON TABLE walkerhill_v4_3.pms_stays IS '실제 체크인·체크아웃과 객실 배정, 투숙객 수, 객실매출을 담는 합성 투숙 팩트';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.stay_id IS '투숙 건의 결정적 합성 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.reservation_id IS '투숙을 발생시킨 합성 예약 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.guest_id IS '대표 합성 투숙객 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.hotel_code IS '실제 투숙한 합성 호텔 코드';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.room_id IS '배정된 합성 객실 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.room_type_code IS '투숙한 호텔 내 객실 유형 코드';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.actual_checkin_at IS '실제 합성 체크인 시각';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.actual_checkout_at IS '실제 합성 체크아웃 시각';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.occupied_room_nights IS '체크인일부터 체크아웃 전일까지의 점유 객실박 수';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.guest_count IS '객실에 등록된 합성 투숙 인원 수';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.room_revenue IS '할인 후 합성 객실 매출 총액';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.other_room_charges IS '미니바·세탁과 POS 객실청구를 포함한 객실 부대 합성 청구액';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.stay_status IS 'CHECKED_IN·CHECKED_OUT 등 투숙 종료 상태';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.complimentary_flag IS '무료 투숙 여부';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.house_use_flag IS '호텔 내부 운영 목적 투숙 여부';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.is_forecast IS '2026-08-31 종료 합성 시나리오 투숙과 향후 별도 예측 행을 구분하는 플래그. false는 실제 워커힐 실적을 뜻하지 않음';
COMMENT ON COLUMN walkerhill_v4_3.pms_stays.is_synthetic IS '실제 투숙자료가 아닌 합성 행임을 나타내며 항상 true';

COMMENT ON TABLE walkerhill_v4_3.pms_stay_nights IS '투숙일별 금·토·일~목, 계절·공휴일·이벤트 요금과 할인을 보존하는 합성 객실박 원장';
COMMENT ON COLUMN walkerhill_v4_3.pms_stay_nights.stay_id IS '객실박이 속한 합성 투숙 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_stay_nights.reservation_id IS '객실박의 원 합성 예약 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_stay_nights.business_date IS '요금과 객실 매출이 귀속되는 Asia/Seoul 숙박일';
COMMENT ON COLUMN walkerhill_v4_3.pms_stay_nights.room_rate_day_type IS 'SUN_THU·FRIDAY·SATURDAY 중 해당 숙박일의 판매 요일 구분';
COMMENT ON COLUMN walkerhill_v4_3.pms_stay_nights.gross_room_rate IS '할인 전 숙박일별 합성 객실요금(원)';
COMMENT ON COLUMN walkerhill_v4_3.pms_stay_nights.discount_amount IS '해당 숙박일에 배분된 합성 할인액(원)';
COMMENT ON COLUMN walkerhill_v4_3.pms_stay_nights.net_room_revenue IS '예약 총액과 일치하도록 원단위 잔액을 보정한 숙박일별 합성 객실매출(원)';
COMMENT ON COLUMN walkerhill_v4_3.pms_stay_nights.event_id IS '해당 숙박일 요금에 가장 큰 ADR 효과를 적용한 이벤트 코드. 미적용은 NULL';
COMMENT ON COLUMN walkerhill_v4_3.pms_stay_nights.is_synthetic IS '실제 요금 원장이 아닌 합성 행임을 나타내며 항상 true';

COMMENT ON TABLE walkerhill_v4_3.pms_folio_postings IS '객실료·부대료·세금·봉사료·환불을 분리해 투숙별 금액을 재조정할 수 있는 합성 폴리오 원장';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.folio_posting_id IS '폴리오 전표의 결정적 합성 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.stay_id IS '전표가 귀속되는 합성 투숙 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.reservation_id IS '전표와 연결된 합성 예약 식별자';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.posted_at IS '전표가 원장에 기록된 한국 표준시 시각';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.posting_type IS 'ROOM_CHARGE·OTHER_ROOM_CHARGE·POS_ROOM_CHARGE·REFUND 등 전표 유형';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.source_system IS '외부 원천 전표이면 POS 등 원천 시스템 코드, PMS 자체 전표이면 NULL';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.source_transaction_id IS '외부 원천 전표 식별자. POS 객실청구는 pos_orders.order_id와 논리적으로 연결';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.gross_amount IS '할인 전 합성 공급가액';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.discount_amount IS '전표 단위 합성 할인액';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.service_charge_amount IS '별도로 계산한 합성 봉사료';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.tax_amount IS '별도로 계산한 합성 세액';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.refund_amount IS '환불·취소 전표의 양수 표시 금액';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.net_amount IS '할인·봉사료·세금·환불을 반영한 부호 있는 최종 전표액';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.currency_code IS '전표 통화 ISO 코드이며 현재 KRW';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.posting_status IS 'POSTED·REVERSED 중 원장 상태';
COMMENT ON COLUMN walkerhill_v4_3.pms_folio_postings.is_synthetic IS '실제 회계 전표가 아닌 합성 행임을 나타내며 항상 true';
