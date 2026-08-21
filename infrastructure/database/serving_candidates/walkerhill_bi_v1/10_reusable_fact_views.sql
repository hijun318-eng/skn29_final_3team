-- release_id=walkerhill-bi-serving-v1.20260820.1
-- source_release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 483; target_schema=serving.analytics_v4_3
-- state=REVIEW_REQUIRED; script_type=VIEW; execution_order=10; execution_default=NOT_RUN
-- purpose=질문별 뷰가 아니라 재사용 가능한 업무 grain과 저카디널리티 차원을 보존한다.

CREATE OR REPLACE VIEW serving.analytics_v4_3.room_stay_night_fact AS
SELECT
    n.business_date,
    n.stay_id,
    n.reservation_id,
    s.hotel_code,
    s.room_type_code,
    t.public_name AS room_type_name,
    r.booking_channel,
    r.market_segment,
    n.room_rate_day_type,
    1 AS occupied_room_nights,
    CAST(s.guest_count AS integer) AS guest_nights,
    n.gross_room_rate AS gross_room_revenue_krw,
    n.discount_amount AS room_discount_krw,
    n.net_room_revenue AS room_revenue_krw
FROM pms.walkerhill_v4_3.pms_stay_nights n
JOIN pms.walkerhill_v4_3.pms_stays s
  ON s.stay_id = n.stay_id
JOIN pms.walkerhill_v4_3.pms_reservations r
  ON r.reservation_id = n.reservation_id
JOIN pms.walkerhill_v4_3.pms_room_types t
  ON t.hotel_code = s.hotel_code
 AND t.room_type_code = s.room_type_code
WHERE s.stay_status = 'CHECKED_OUT'
  AND NOT s.complimentary_flag
  AND NOT s.house_use_flag;

COMMENT ON VIEW serving.analytics_v4_3.room_stay_night_fact IS '실제 투숙 1박을 한 행으로 보존해 객실유형·예약채널·시장세그먼트별 객실매출과 점유 객실박을 분석하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.business_date IS '투숙 1박과 객실매출이 귀속되는 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.stay_id IS '합성 투숙 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.reservation_id IS '합성 예약 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.hotel_code IS 'GRAND·VISTA·DOUGLAS 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.room_type_code IS '호텔 내 합성 객실유형 코드';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.room_type_name IS '공개 객실유형 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.booking_channel IS 'DIRECT_WEB·OTA·CORPORATE 등 합성 예약채널';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.market_segment IS 'LEISURE·BUSINESS·GROUP 등 합성 시장세그먼트';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.room_rate_day_type IS 'WEEKDAY·WEEKEND·HOLIDAY 등 요금 적용일 유형';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.occupied_room_nights IS '한 행이 나타내는 점유 객실박 수로 항상 1';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.guest_nights IS '해당 객실박에 투숙한 합성 고객 인원';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.gross_room_revenue_krw IS '할인 전 합성 객실요금';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.room_discount_krw IS '객실박에 배분된 합성 할인액';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_night_fact.room_revenue_krw IS '할인 후 인식된 합성 객실매출';

CREATE OR REPLACE VIEW serving.analytics_v4_3.room_kpi_daily_by_type AS
WITH inventory AS (
    SELECT business_date, hotel_code, room_type_code,
           SUM(available_room_nights) AS available_room_nights
    FROM pms.walkerhill_v4_3.pms_room_inventory_daily
    GROUP BY 1, 2, 3
), actual AS (
    SELECT business_date, hotel_code, room_type_code,
           SUM(occupied_room_nights) AS occupied_room_nights,
           SUM(guest_nights) AS guest_nights,
           SUM(room_revenue_krw) AS room_revenue_krw
    FROM serving.analytics_v4_3.room_stay_night_fact
    GROUP BY 1, 2, 3
)
SELECT
    i.business_date,
    i.hotel_code,
    i.room_type_code,
    t.public_name AS room_type_name,
    i.available_room_nights,
    COALESCE(a.occupied_room_nights, 0) AS occupied_room_nights,
    COALESCE(a.guest_nights, 0) AS guest_nights,
    COALESCE(a.room_revenue_krw, DECIMAL '0') AS room_revenue_krw
FROM inventory i
JOIN pms.walkerhill_v4_3.pms_room_types t
  ON t.hotel_code = i.hotel_code
 AND t.room_type_code = i.room_type_code
LEFT JOIN actual a
  ON a.business_date = i.business_date
 AND a.hotel_code = i.hotel_code
 AND a.room_type_code = i.room_type_code;

COMMENT ON VIEW serving.analytics_v4_3.room_kpi_daily_by_type IS '호텔·영업일·객실유형 grain에서 OCC·ADR·RevPAR의 가산 가능한 분자와 분모를 함께 제공하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.room_kpi_daily_by_type.business_date IS '객실 KPI 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.room_kpi_daily_by_type.hotel_code IS '합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.room_kpi_daily_by_type.room_type_code IS '호텔 내 합성 객실유형 코드';
COMMENT ON COLUMN serving.analytics_v4_3.room_kpi_daily_by_type.room_type_name IS '공개 객실유형 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.room_kpi_daily_by_type.available_room_nights IS '판매 가능 객실박 합계';
COMMENT ON COLUMN serving.analytics_v4_3.room_kpi_daily_by_type.occupied_room_nights IS '무료·하우스유즈를 제외한 점유 객실박 합계';
COMMENT ON COLUMN serving.analytics_v4_3.room_kpi_daily_by_type.guest_nights IS '투숙 인원 기준 합성 고객박 합계';
COMMENT ON COLUMN serving.analytics_v4_3.room_kpi_daily_by_type.room_revenue_krw IS '인식된 합성 객실매출 합계';

CREATE OR REPLACE VIEW serving.analytics_v4_3.room_reservation_fact AS
SELECT
    CAST(r.booked_at AT TIME ZONE 'Asia/Seoul' AS date) AS booked_date,
    r.checkin_date,
    r.checkout_date,
    r.reservation_id,
    r.hotel_code,
    r.room_type_code,
    t.public_name AS room_type_name,
    r.booking_channel,
    r.market_segment,
    r.reservation_status,
    1 AS reservation_count,
    DATE_DIFF('day', r.checkin_date, r.checkout_date) AS booked_room_nights,
    r.booked_amount AS booked_amount_krw,
    r.discount_amount AS booked_discount_krw
FROM pms.walkerhill_v4_3.pms_reservations r
JOIN pms.walkerhill_v4_3.pms_room_types t
  ON t.hotel_code = r.hotel_code
 AND t.room_type_code = r.room_type_code;

COMMENT ON VIEW serving.analytics_v4_3.room_reservation_fact IS '한 예약을 한 행으로 보존해 예약 생성일·투숙 예정일·상태·채널·객실유형별 예약 수요를 분석하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.booked_date IS '예약이 생성된 한국 표준시 날짜';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.checkin_date IS '예약된 체크인 날짜';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.checkout_date IS '예약된 체크아웃 미포함 경계 날짜';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.reservation_id IS '합성 예약 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.hotel_code IS '합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.room_type_code IS '호텔 내 합성 객실유형 코드';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.room_type_name IS '공개 객실유형 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.booking_channel IS '합성 예약채널';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.market_segment IS '합성 시장세그먼트';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.reservation_status IS '예약의 최종 상태';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.reservation_count IS '한 행이 나타내는 예약 수로 항상 1';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.booked_room_nights IS '체크인 이상 체크아웃 미만의 예약 객실박 수';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.booked_amount_krw IS '예약 시점 합성 예약금액';
COMMENT ON COLUMN serving.analytics_v4_3.room_reservation_fact.booked_discount_krw IS '예약에 적용된 합성 할인액';

CREATE OR REPLACE VIEW serving.analytics_v4_3.fnb_order_fact AS
SELECT
    o.business_date,
    o.order_id,
    x.hotel_code,
    o.outlet_id,
    x.public_name AS outlet_name,
    x.outlet_category,
    o.service_period,
    o.order_status,
    1 AS order_count,
    CASE WHEN o.order_status IN ('PAID', 'PARTIAL_REFUND') THEN 1 ELSE 0 END AS completed_order_count,
    CASE WHEN o.order_status IN ('VOID', 'REFUNDED') THEN 1 ELSE 0 END AS reversed_order_count,
    CASE WHEN o.order_status <> 'VOID' THEN o.guest_count ELSE 0 END AS covers,
    o.item_gross_amount AS item_gross_amount_krw,
    o.discount_amount AS discount_amount_krw,
    o.service_charge_amount AS service_charge_amount_krw,
    o.tax_amount AS tax_amount_krw,
    o.refund_amount + o.void_amount AS reversal_amount_krw,
    o.net_amount AS fnb_revenue_krw
FROM pos.walkerhill_v4_3.pos_orders o
JOIN pos.walkerhill_v4_3.pos_outlets x
  ON x.outlet_id = o.outlet_id;

COMMENT ON VIEW serving.analytics_v4_3.fnb_order_fact IS '한 POS 주문을 한 행으로 보존해 업장·업장유형·서비스시간대·상태별 식음 매출과 고객 수를 분석하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.business_date IS '주문이 귀속되는 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.order_id IS '합성 POS 주문 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.hotel_code IS '업장이 귀속되는 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.outlet_id IS '합성 식음 업장 코드';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.outlet_name IS '공개 식음 업장 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.outlet_category IS 'BUFFET·KOREAN·BAR 등 업장 유형';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.service_period IS 'BREAKFAST·LUNCH·DINNER 등 서비스 시간대';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.order_status IS '주문의 종료 상태';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.order_count IS '한 행이 나타내는 주문 수로 항상 1';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.completed_order_count IS '완료 주문이면 1, 아니면 0';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.reversed_order_count IS '취소·환불 주문이면 1, 아니면 0';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.covers IS '취소를 제외한 합성 고객 커버 수';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.item_gross_amount_krw IS '할인 전 메뉴 품목 총액';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.discount_amount_krw IS '주문 할인액';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.service_charge_amount_krw IS '주문 봉사료';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.tax_amount_krw IS '주문 세액';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.reversal_amount_krw IS '환불액과 취소액 합계';
COMMENT ON COLUMN serving.analytics_v4_3.fnb_order_fact.fnb_revenue_krw IS '할인·환불·취소를 반영한 합성 식음 순매출';

CREATE OR REPLACE VIEW serving.analytics_v4_3.banquet_event_fact AS
SELECT
    b.event_date,
    CAST(b.inquiry_at AT TIME ZONE 'Asia/Seoul' AS date) AS inquiry_date,
    b.banquet_event_id,
    v.hotel_code,
    b.venue_id,
    v.public_name AS venue_name,
    v.venue_category,
    b.event_slot,
    b.event_type,
    b.booking_status,
    1 AS event_count,
    CASE WHEN b.booking_status = 'COMPLETED' THEN 1 ELSE 0 END AS completed_event_count,
    CASE WHEN b.booking_status = 'CONFIRMED' THEN 1 ELSE 0 END AS confirmed_event_count,
    CASE WHEN b.booking_status = 'CANCELLED' THEN 1 ELSE 0 END AS cancelled_event_count,
    b.expected_guests,
    COALESCE(b.actual_attendees, 0) AS actual_attendees,
    b.quoted_amount AS quoted_amount_krw,
    b.contracted_amount AS contracted_amount_krw,
    b.cancellation_fee_amount AS cancellation_fee_amount_krw
FROM banquet.walkerhill_v4_3.banquet_bookings b
JOIN banquet.walkerhill_v4_3.banquet_venues v
  ON v.venue_id = b.venue_id;

COMMENT ON VIEW serving.analytics_v4_3.banquet_event_fact IS '한 연회 예약·행사를 한 행으로 보존해 행사일·문의일·행사장·유형·상태별 건수와 참석자를 분석하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.event_date IS '연회가 예정되거나 완료된 행사일';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.inquiry_date IS '최초 연회 문의의 한국 표준시 날짜';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.banquet_event_id IS '합성 연회 예약 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.hotel_code IS '행사장이 귀속되는 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.venue_id IS '합성 행사장 코드';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.venue_name IS '공개 행사장 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.venue_category IS '행사장 유형';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.event_slot IS 'MORNING·AFTERNOON·EVENING 행사 시간대';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.event_type IS 'WEDDING·CORPORATE·CONFERENCE 등 행사 유형';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.booking_status IS '연회 예약의 최종 상태';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.event_count IS '한 행이 나타내는 연회 예약·행사 수로 항상 1';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.completed_event_count IS '완료 행사이면 1, 아니면 0';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.confirmed_event_count IS '확정 행사이면 1, 아니면 0';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.cancelled_event_count IS '취소 행사이면 1, 아니면 0';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.expected_guests IS '예상 참석자 수';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.actual_attendees IS '완료 행사의 실제 참석자 수';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.quoted_amount_krw IS '견적 단계 합성 금액';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.contracted_amount_krw IS '확정 계약 합성 금액';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_event_fact.cancellation_fee_amount_krw IS '취소 계약의 합성 위약금';

CREATE OR REPLACE VIEW serving.analytics_v4_3.banquet_revenue_fact AS
SELECT
    r.recognized_date AS business_date,
    r.revenue_line_id,
    r.banquet_event_id,
    v.hotel_code,
    b.venue_id,
    v.public_name AS venue_name,
    v.venue_category,
    b.event_type,
    r.revenue_category,
    r.revenue_status,
    r.gross_amount AS gross_amount_krw,
    r.discount_amount AS discount_amount_krw,
    r.reversal_amount AS reversal_amount_krw,
    r.recognized_amount AS banquet_revenue_krw,
    r.cost_amount AS estimated_cost_krw
FROM banquet.walkerhill_v4_3.banquet_revenue_lines r
JOIN banquet.walkerhill_v4_3.banquet_bookings b
  ON b.banquet_event_id = r.banquet_event_id
JOIN banquet.walkerhill_v4_3.banquet_venues v
  ON v.venue_id = b.venue_id;

COMMENT ON VIEW serving.analytics_v4_3.banquet_revenue_fact IS '한 연회 매출 원장 행을 보존해 행사장·행사유형·매출범주별 인식매출과 원가를 분석하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.business_date IS '매출 인식 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.revenue_line_id IS '합성 연회 매출 원장 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.banquet_event_id IS '합성 연회 예약 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.hotel_code IS '행사장이 귀속되는 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.venue_id IS '합성 행사장 코드';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.venue_name IS '공개 행사장 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.venue_category IS '행사장 유형';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.event_type IS '연회 행사 유형';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.revenue_category IS 'FOOD·BEVERAGE·VENUE·EQUIPMENT·SERVICE 매출 범주';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.revenue_status IS '연회 매출 인식 상태';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.gross_amount_krw IS '할인·환입 전 연회 매출 총액';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.discount_amount_krw IS '연회 할인액';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.reversal_amount_krw IS '연회 취소·정정 환입액';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.banquet_revenue_krw IS '합성 연회 인식매출';
COMMENT ON COLUMN serving.analytics_v4_3.banquet_revenue_fact.estimated_cost_krw IS '분석용 합성 추정 원가';

CREATE OR REPLACE VIEW serving.analytics_v4_3.facility_usage_fact AS
SELECT
    CAST(u.event_time AS date) AS business_date,
    u.usage_event_id,
    m.reporting_hotel_code AS hotel_code,
    u.facility_id,
    m.facility_name,
    m.facility_type,
    u.usage_type,
    1 AS usage_count,
    u.party_size AS facility_guests,
    u.duration_minutes,
    u.gross_amount AS facility_revenue_krw
FROM facility.walkerhill_v4_3.facility_usage_events u
JOIN facility.walkerhill_v4_3.facility_master m
  ON m.facility_id = u.facility_id;

COMMENT ON VIEW serving.analytics_v4_3.facility_usage_fact IS '한 시설 이용 이벤트를 한 행으로 보존해 시설·시설유형·이용유형별 이용 건수·인원·시간·매출을 분석하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.facility_usage_fact.business_date IS '시설 이용 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.facility_usage_fact.usage_event_id IS '합성 시설 이용 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.facility_usage_fact.hotel_code IS '시설의 일관된 보고 귀속 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.facility_usage_fact.facility_id IS '합성 시설 코드';
COMMENT ON COLUMN serving.analytics_v4_3.facility_usage_fact.facility_name IS '시설 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.facility_usage_fact.facility_type IS 'POOL·FITNESS·WELLNESS 등 시설 유형';
COMMENT ON COLUMN serving.analytics_v4_3.facility_usage_fact.usage_type IS 'ENTRY·SESSION·RENTAL·PROGRAM 이용 유형';
COMMENT ON COLUMN serving.analytics_v4_3.facility_usage_fact.usage_count IS '한 행이 나타내는 시설 이용 건수로 항상 1';
COMMENT ON COLUMN serving.analytics_v4_3.facility_usage_fact.facility_guests IS '시설 이용 합성 인원';
COMMENT ON COLUMN serving.analytics_v4_3.facility_usage_fact.duration_minutes IS '시설 이용 지속 시간';
COMMENT ON COLUMN serving.analytics_v4_3.facility_usage_fact.facility_revenue_krw IS '유료 시설 합성 총매출';

CREATE OR REPLACE VIEW serving.analytics_v4_3.facility_incident_fact AS
SELECT
    CAST(i.opened_at AS date) AS business_date,
    i.incident_id,
    m.reporting_hotel_code AS hotel_code,
    i.facility_id,
    m.facility_name,
    m.facility_type,
    i.severity,
    i.incident_type,
    i.resolution_status,
    1 AS incident_count,
    CASE WHEN i.severity = 'HIGH' THEN 1 ELSE 0 END AS high_severity_incident_count,
    i.impact_minutes,
    i.guest_impact_count
FROM facility.walkerhill_v4_3.facility_incidents i
JOIN facility.walkerhill_v4_3.facility_master m
  ON m.facility_id = i.facility_id;

COMMENT ON VIEW serving.analytics_v4_3.facility_incident_fact IS '한 시설 사고·불편을 한 행으로 보존해 시설·원인·심각도·조치상태별 건수와 영향을 분석하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.business_date IS '시설 사고·불편 접수 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.incident_id IS '합성 시설 사고 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.hotel_code IS '시설의 보고 귀속 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.facility_id IS '합성 시설 코드';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.facility_name IS '시설 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.facility_type IS '시설 유형';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.severity IS 'LOW·MEDIUM·HIGH 운영 영향 심각도';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.incident_type IS 'EQUIPMENT·SAFETY·CLEANLINESS 등 사고 원인 유형';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.resolution_status IS 'RESOLVED·MONITORING·OPEN 조치 상태';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.incident_count IS '한 행이 나타내는 사고·불편 건수로 항상 1';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.high_severity_incident_count IS 'HIGH 심각도이면 1, 아니면 0';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.impact_minutes IS '시설 운영 또는 고객 경험 영향 시간';
COMMENT ON COLUMN serving.analytics_v4_3.facility_incident_fact.guest_impact_count IS '사고로 직접 영향을 받은 합성 고객 수';

CREATE OR REPLACE VIEW serving.analytics_v4_3.facility_resource_daily_fact AS
SELECT
    r.business_date,
    m.reporting_hotel_code AS hotel_code,
    r.facility_id,
    m.facility_name,
    m.facility_type,
    r.energy_kwh,
    r.water_m3,
    r.waste_kg
FROM facility.walkerhill_v4_3.facility_resource_daily r
JOIN facility.walkerhill_v4_3.facility_master m
  ON m.facility_id = r.facility_id;

COMMENT ON VIEW serving.analytics_v4_3.facility_resource_daily_fact IS '시설·영업일 grain에서 전력·용수·폐기물 사용량을 보존하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.facility_resource_daily_fact.business_date IS '자원 사용량 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.facility_resource_daily_fact.hotel_code IS '시설의 보고 귀속 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.facility_resource_daily_fact.facility_id IS '합성 시설 코드';
COMMENT ON COLUMN serving.analytics_v4_3.facility_resource_daily_fact.facility_name IS '시설 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.facility_resource_daily_fact.facility_type IS '시설 유형';
COMMENT ON COLUMN serving.analytics_v4_3.facility_resource_daily_fact.energy_kwh IS '합성 전력 사용량';
COMMENT ON COLUMN serving.analytics_v4_3.facility_resource_daily_fact.water_m3 IS '합성 용수 사용량';
COMMENT ON COLUMN serving.analytics_v4_3.facility_resource_daily_fact.waste_kg IS '합성 폐기물 발생량';

CREATE OR REPLACE VIEW serving.analytics_v4_3.staffing_daily_fact AS
SELECT
    business_date,
    hotel_code,
    department,
    shift_code,
    planned_hours,
    actual_hours,
    guest_facing_fte,
    overtime_hours,
    event_load_index
FROM facility.walkerhill_v4_3.hotel_staffing_daily;

COMMENT ON VIEW serving.analytics_v4_3.staffing_daily_fact IS '호텔·영업일·부서·근무조 grain을 보존해 인력 계획·실적·초과근로를 분석하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily_fact.business_date IS '인력 배치 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily_fact.hotel_code IS '인력이 배치된 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily_fact.department IS 'FRONT·HOUSEKEEPING·FNB·FACILITY·SECURITY 운영 부서';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily_fact.shift_code IS 'DAY·EVENING·NIGHT 근무조';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily_fact.planned_hours IS '합성 계획 근로시간';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily_fact.actual_hours IS '합성 실제 근로시간';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily_fact.guest_facing_fte IS '8시간 기준 합성 고객 접점 FTE';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily_fact.overtime_hours IS '계획 대비 합성 초과근로시간';
COMMENT ON COLUMN serving.analytics_v4_3.staffing_daily_fact.event_load_index IS '합성 이벤트 부하 지수';

CREATE OR REPLACE VIEW serving.analytics_v4_3.membership_current_snapshot AS
WITH watermark AS (
    SELECT MAX(CAST(event_at AT TIME ZONE 'Asia/Seoul' AS date)) AS snapshot_date
    FROM crm.walkerhill_v4_3.crm_point_transactions
)
SELECT
    w.snapshot_date,
    m.member_no,
    m.current_tier_code AS tier_code,
    t.public_name AS tier_name,
    t.synthetic_rank AS tier_rank,
    m.member_status,
    1 AS member_count,
    m.points_balance
FROM crm.walkerhill_v4_3.crm_members m
JOIN crm.walkerhill_v4_3.crm_membership_tiers t
  ON t.tier_code = m.current_tier_code
CROSS JOIN watermark w;

COMMENT ON VIEW serving.analytics_v4_3.membership_current_snapshot IS '원천 포인트 거래의 최대 영업일을 데이터 watermark로 사용한 회원 1인 1행 현재 등급·상태 합성 스냅샷';
COMMENT ON COLUMN serving.analytics_v4_3.membership_current_snapshot.snapshot_date IS '런타임 시계가 아니라 원천 데이터 최대 거래일에서 결정한 스냅샷 날짜';
COMMENT ON COLUMN serving.analytics_v4_3.membership_current_snapshot.member_no IS '실제 회원번호와 무관한 합성 회원 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.membership_current_snapshot.tier_code IS '합성 멤버십 등급 코드';
COMMENT ON COLUMN serving.analytics_v4_3.membership_current_snapshot.tier_name IS '공개 멤버십 등급 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.membership_current_snapshot.tier_rank IS '합성 등급 서열';
COMMENT ON COLUMN serving.analytics_v4_3.membership_current_snapshot.member_status IS '합성 회원 상태';
COMMENT ON COLUMN serving.analytics_v4_3.membership_current_snapshot.member_count IS '한 행이 나타내는 회원 수로 항상 1';
COMMENT ON COLUMN serving.analytics_v4_3.membership_current_snapshot.points_balance IS '스냅샷 기준 합성 포인트 잔액';

CREATE OR REPLACE VIEW serving.analytics_v4_3.membership_point_fact AS
SELECT
    CAST(p.event_at AT TIME ZONE 'Asia/Seoul' AS date) AS business_date,
    p.point_txn_id,
    p.member_no,
    m.current_tier_code AS tier_code,
    t.public_name AS tier_name,
    m.member_status,
    p.txn_type,
    p.related_source,
    1 AS point_transaction_count,
    CASE WHEN p.points_delta > 0 THEN p.points_delta ELSE 0 END AS points_earned,
    CASE WHEN p.txn_type = 'REDEEM' THEN -p.points_delta ELSE 0 END AS points_redeemed,
    CASE WHEN p.txn_type = 'EXPIRE' THEN -p.points_delta ELSE 0 END AS points_expired,
    p.points_delta AS net_points_delta
FROM crm.walkerhill_v4_3.crm_point_transactions p
JOIN crm.walkerhill_v4_3.crm_members m
  ON m.member_no = p.member_no
JOIN crm.walkerhill_v4_3.crm_membership_tiers t
  ON t.tier_code = m.current_tier_code;

COMMENT ON VIEW serving.analytics_v4_3.membership_point_fact IS '한 포인트 거래를 한 행으로 보존해 등급·회원상태·거래유형·근거시스템별 적립·사용·만료를 분석하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.business_date IS '포인트 거래의 한국 표준시 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.point_txn_id IS '합성 포인트 원장 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.member_no IS '합성 회원 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.tier_code IS '현재 합성 멤버십 등급 코드';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.tier_name IS '공개 멤버십 등급 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.member_status IS '합성 회원 상태';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.txn_type IS 'EARN·REDEEM·EXPIRE 포인트 거래 유형';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.related_source IS '포인트 거래 근거 시스템';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.point_transaction_count IS '한 행이 나타내는 포인트 거래 수로 항상 1';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.points_earned IS '양수 적립 포인트';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.points_redeemed IS '사용 포인트 절대값';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.points_expired IS '만료 포인트 절대값';
COMMENT ON COLUMN serving.analytics_v4_3.membership_point_fact.net_points_delta IS '부호 있는 포인트 순변동';

CREATE OR REPLACE VIEW serving.analytics_v4_3.voc_review_fact AS
SELECT
    v.source_business_date AS business_date,
    v.voc_review_id,
    v.hotel_code,
    v.source_channel,
    v.touchpoint,
    v.selected_category,
    v.related_source,
    v.outlet_id,
    v.facility_id,
    v.visit_cohort,
    a.sentiment_label,
    a.primary_topic,
    a.urgency_level,
    1 AS review_count,
    CASE WHEN v.rating_overall <= 2 THEN 1 ELSE 0 END AS low_rating_review_count,
    CASE WHEN a.sentiment_label = 'NEGATIVE' THEN 1 ELSE 0 END AS negative_review_count,
    CASE WHEN a.requires_followup THEN 1 ELSE 0 END AS followup_review_count,
    CAST(v.rating_overall AS integer) AS rating_points,
    CAST(v.rating_service AS integer) AS rating_service,
    CAST(v.rating_cleanliness AS integer) AS rating_cleanliness,
    CAST(v.rating_food AS integer) AS rating_food,
    CAST(v.rating_facility AS integer) AS rating_facility,
    CAST(v.rating_value AS integer) AS rating_value,
    a.sentiment_score,
    a.analysis_confidence
FROM crm.walkerhill_v4_3.crm_voc_reviews v
JOIN crm.walkerhill_v4_3.crm_voc_analysis a
  ON a.voc_review_id = v.voc_review_id
WHERE v.consent_for_analysis = true;

COMMENT ON VIEW serving.analytics_v4_3.voc_review_fact IS '리뷰 원문과 회원키를 제외하고 한 VOC를 한 행으로 보존해 채널·접점·유형·감성·주제별 건수와 평점을 분석하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.business_date IS 'VOC가 평가하는 원 운영 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.voc_review_id IS '합성 VOC 리뷰 식별자';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.hotel_code IS 'VOC 대상 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.source_channel IS 'VOC 수집 채널';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.touchpoint IS 'CHECKOUT·ROOM·FNB·FACILITY·BANQUET·OVERALL 고객 접점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.selected_category IS '고객이 선택한 합성 의견 범주';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.related_source IS '관련 운영 객체 유형';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.outlet_id IS 'FNB 접점의 합성 업장 코드';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.facility_id IS '시설 접점의 합성 시설 코드';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.visit_cohort IS 'NEW·RETURNING 방문 코호트';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.sentiment_label IS 'POSITIVE·NEUTRAL·NEGATIVE 합성 감성 라벨';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.primary_topic IS '분석기가 분류한 주요 운영 주제';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.urgency_level IS 'LOW·MEDIUM·HIGH 운영 확인 긴급도';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.review_count IS '한 행이 나타내는 VOC 수로 항상 1';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.low_rating_review_count IS '종합 평점 1~2점이면 1, 아니면 0';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.negative_review_count IS '부정 감성이면 1, 아니면 0';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.followup_review_count IS '후속 확인 대상이면 1, 아니면 0';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.rating_points IS '평균 종합 평점의 분자로 사용하는 1~5점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.rating_service IS '1~5점 서비스 평점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.rating_cleanliness IS '객실 접점의 1~5점 청결 평점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.rating_food IS '식음·연회 접점의 1~5점 음식 평점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.rating_facility IS '시설 접점의 1~5점 시설 평점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.rating_value IS '1~5점 가격 대비 가치 평점';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.sentiment_score IS '-1부터 1까지의 합성 감성 점수';
COMMENT ON COLUMN serving.analytics_v4_3.voc_review_fact.analysis_confidence IS '규칙 기반 합성 분류 신뢰도';

CREATE OR REPLACE VIEW serving.analytics_v4_3.operating_revenue_daily_fact AS
WITH calendar AS (
    SELECT business_date, hotel_code FROM serving.analytics_v4_3.room_kpi_daily_by_type
    UNION
    SELECT business_date, hotel_code FROM serving.analytics_v4_3.fnb_order_fact
    UNION
    SELECT business_date, hotel_code FROM serving.analytics_v4_3.banquet_revenue_fact
    UNION
    SELECT business_date, hotel_code FROM serving.analytics_v4_3.facility_usage_fact
), room AS (
    SELECT business_date, hotel_code, SUM(room_revenue_krw) AS room_revenue_krw
    FROM serving.analytics_v4_3.room_kpi_daily_by_type GROUP BY 1, 2
), fnb AS (
    SELECT business_date, hotel_code, SUM(fnb_revenue_krw) AS fnb_revenue_krw
    FROM serving.analytics_v4_3.fnb_order_fact GROUP BY 1, 2
), banquet AS (
    SELECT business_date, hotel_code, SUM(banquet_revenue_krw) AS banquet_revenue_krw
    FROM serving.analytics_v4_3.banquet_revenue_fact GROUP BY 1, 2
), facility AS (
    SELECT business_date, hotel_code, SUM(facility_revenue_krw) AS facility_revenue_krw
    FROM serving.analytics_v4_3.facility_usage_fact GROUP BY 1, 2
)
SELECT
    c.business_date,
    c.hotel_code,
    COALESCE(r.room_revenue_krw, DECIMAL '0') AS room_revenue_krw,
    COALESCE(f.fnb_revenue_krw, DECIMAL '0') AS fnb_revenue_krw,
    COALESCE(b.banquet_revenue_krw, DECIMAL '0') AS banquet_revenue_krw,
    COALESCE(x.facility_revenue_krw, DECIMAL '0') AS facility_revenue_krw,
    COALESCE(r.room_revenue_krw, DECIMAL '0')
      + COALESCE(f.fnb_revenue_krw, DECIMAL '0')
      + COALESCE(b.banquet_revenue_krw, DECIMAL '0')
      + COALESCE(x.facility_revenue_krw, DECIMAL '0') AS total_operating_revenue_krw
FROM calendar c
LEFT JOIN room r ON r.business_date = c.business_date AND r.hotel_code = c.hotel_code
LEFT JOIN fnb f ON f.business_date = c.business_date AND f.hotel_code = c.hotel_code
LEFT JOIN banquet b ON b.business_date = c.business_date AND b.hotel_code = c.hotel_code
LEFT JOIN facility x ON x.business_date = c.business_date AND x.hotel_code = c.hotel_code;

COMMENT ON VIEW serving.analytics_v4_3.operating_revenue_daily_fact IS '객실·식음·연회·시설 재사용 fact를 호텔·영업일 grain으로 선집계해 fan-out 없이 운영매출을 구성한 통합 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.operating_revenue_daily_fact.business_date IS '통합 운영매출 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.operating_revenue_daily_fact.hotel_code IS '합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.operating_revenue_daily_fact.room_revenue_krw IS '합성 객실매출';
COMMENT ON COLUMN serving.analytics_v4_3.operating_revenue_daily_fact.fnb_revenue_krw IS '합성 식음 순매출';
COMMENT ON COLUMN serving.analytics_v4_3.operating_revenue_daily_fact.banquet_revenue_krw IS '합성 연회 인식매출';
COMMENT ON COLUMN serving.analytics_v4_3.operating_revenue_daily_fact.facility_revenue_krw IS '합성 시설매출';
COMMENT ON COLUMN serving.analytics_v4_3.operating_revenue_daily_fact.total_operating_revenue_krw IS '객실·식음·연회·시설 매출 합계';
