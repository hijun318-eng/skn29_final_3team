-- release_id=walkerhill-analysis-semantics-v1.20260826.1
-- source_release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 483; target_schema=serving.analytics_v4_3
-- state=REVIEW_REQUIRED; script_type=VIEW; execution_order=10; execution_default=NOT_RUN
-- purpose=질문별 SQL이 아니라 회원 event-time 매출과 실제 투숙 시간 역할을 재사용 가능한 grain으로 제공한다.

CREATE OR REPLACE VIEW serving.analytics_v4_3.room_stay_fact AS
SELECT
    CAST(s.actual_checkin_at AT TIME ZONE 'Asia/Seoul' AS date) AS checkin_date,
    CAST(s.actual_checkout_at AT TIME ZONE 'Asia/Seoul' AS date) AS checkout_date,
    s.stay_id,
    s.hotel_code,
    s.room_type_code,
    CAST(s.occupied_room_nights AS integer) AS occupied_room_nights,
    CAST(s.guest_count AS integer) AS guest_count,
    s.room_revenue AS room_revenue_krw
FROM pms.walkerhill_v4_3.pms_stays s
WHERE s.stay_status = 'CHECKED_OUT'
  AND NOT s.complimentary_flag
  AND NOT s.house_use_flag;

COMMENT ON VIEW serving.analytics_v4_3.room_stay_fact IS '완료된 실제 투숙 한 건을 한 행으로 보존해 체크인일·체크아웃일 역할별 객실매출을 분석하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_fact.checkin_date IS '실제 체크인 시각을 Asia/Seoul 달력일로 변환한 날짜';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_fact.checkout_date IS '실제 체크아웃 시각을 Asia/Seoul 달력일로 변환한 날짜';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_fact.stay_id IS '한 투숙을 식별하는 비식별 합성 키';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_fact.hotel_code IS '투숙이 발생한 GRAND·VISTA·DOUGLAS 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_fact.room_type_code IS '호텔 안에서 투숙 객실유형을 식별하는 합성 코드';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_fact.occupied_room_nights IS '해당 완료 투숙의 점유 객실박 수';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_fact.guest_count IS '해당 완료 투숙의 합성 투숙 인원 수';
COMMENT ON COLUMN serving.analytics_v4_3.room_stay_fact.room_revenue_krw IS '무료·하우스유즈를 제외한 완료 투숙 전체의 원화 합성 객실매출';

CREATE OR REPLACE VIEW serving.analytics_v4_3.member_revenue_daily AS
WITH room_events AS (
    SELECT
        n.business_date,
        s.hotel_code,
        s.guest_id,
        greatest(
            s.actual_checkin_at,
            with_timezone(CAST(n.business_date AS timestamp), 'Asia/Seoul')
        ) AS event_at,
        n.net_room_revenue AS room_revenue_krw
    FROM pms.walkerhill_v4_3.pms_stay_nights n
    JOIN pms.walkerhill_v4_3.pms_stays s
      ON s.stay_id = n.stay_id
    WHERE s.stay_status = 'CHECKED_OUT'
      AND NOT s.complimentary_flag
      AND NOT s.house_use_flag
), room_attributed AS (
    SELECT
        e.business_date,
        e.hotel_code,
        g.tier_code,
        t.public_name AS tier_name,
        e.room_revenue_krw
    FROM room_events e
    JOIN crm.walkerhill_v4_3.crm_customer_map m
      ON m.pms_guest_id = e.guest_id
     AND m.mapping_status = 'ACTIVE'
     AND e.event_at >= m.valid_from
     AND (m.valid_to IS NULL OR e.event_at < m.valid_to)
    JOIN crm.walkerhill_v4_3.crm_member_grade_history g
      ON g.member_no = m.member_no
     AND e.event_at >= g.valid_from
     AND (g.valid_to IS NULL OR e.event_at < g.valid_to)
    JOIN crm.walkerhill_v4_3.crm_membership_tiers t
      ON t.tier_code = g.tier_code
), fnb_events AS (
    SELECT
        o.business_date,
        x.hotel_code,
        o.pos_customer_ref,
        with_timezone(o.ordered_at, 'Asia/Seoul') AS event_at,
        o.net_amount AS fnb_revenue_krw
    FROM pos.walkerhill_v4_3.pos_orders o
    JOIN pos.walkerhill_v4_3.pos_outlets x
      ON x.outlet_id = o.outlet_id
    WHERE o.pos_customer_ref IS NOT NULL
), fnb_attributed AS (
    SELECT
        e.business_date,
        e.hotel_code,
        g.tier_code,
        t.public_name AS tier_name,
        e.fnb_revenue_krw
    FROM fnb_events e
    JOIN crm.walkerhill_v4_3.crm_customer_map m
      ON m.pos_customer_ref = e.pos_customer_ref
     AND m.mapping_status = 'ACTIVE'
     AND e.event_at >= m.valid_from
     AND (m.valid_to IS NULL OR e.event_at < m.valid_to)
    JOIN crm.walkerhill_v4_3.crm_member_grade_history g
      ON g.member_no = m.member_no
     AND e.event_at >= g.valid_from
     AND (g.valid_to IS NULL OR e.event_at < g.valid_to)
    JOIN crm.walkerhill_v4_3.crm_membership_tiers t
      ON t.tier_code = g.tier_code
), room AS (
    SELECT
        business_date,
        hotel_code,
        tier_code,
        tier_name,
        SUM(room_revenue_krw) AS room_revenue_krw
    FROM room_attributed
    GROUP BY 1, 2, 3, 4
), fnb AS (
    SELECT
        business_date,
        hotel_code,
        tier_code,
        tier_name,
        SUM(fnb_revenue_krw) AS fnb_revenue_krw
    FROM fnb_attributed
    GROUP BY 1, 2, 3, 4
)
SELECT
    COALESCE(r.business_date, f.business_date) AS business_date,
    COALESCE(r.hotel_code, f.hotel_code) AS hotel_code,
    COALESCE(r.tier_code, f.tier_code) AS tier_code,
    COALESCE(r.tier_name, f.tier_name) AS tier_name,
    COALESCE(r.room_revenue_krw, DECIMAL '0') AS room_revenue_krw,
    COALESCE(f.fnb_revenue_krw, DECIMAL '0') AS fnb_revenue_krw
FROM room r
FULL OUTER JOIN fnb f
  ON f.business_date = r.business_date
 AND f.hotel_code = r.hotel_code
 AND f.tier_code = r.tier_code;

COMMENT ON VIEW serving.analytics_v4_3.member_revenue_daily IS 'PMS·POS 고객키와 CRM 유효기간 이력을 거래 시점에 결합해 회원등급·호텔·영업일별 객실·식음 매출을 제공하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.member_revenue_daily.business_date IS '객실박 또는 POS 주문 매출이 귀속되는 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.member_revenue_daily.hotel_code IS '회원 매출이 발생한 GRAND·VISTA·DOUGLAS 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.member_revenue_daily.tier_code IS '매출 발생 시점의 CRM 유효기간 이력에서 확정한 멤버십 등급 코드';
COMMENT ON COLUMN serving.analytics_v4_3.member_revenue_daily.tier_name IS '등급 마스터에 등록된 멤버십 공개 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.member_revenue_daily.room_revenue_krw IS '매출 발생 시점에 회원으로 확인된 객실박의 원화 합성 객실매출';
COMMENT ON COLUMN serving.analytics_v4_3.member_revenue_daily.fnb_revenue_krw IS '주문 시점에 회원으로 확인된 POS 주문의 원화 합성 식음 순매출';
