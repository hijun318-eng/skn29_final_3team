-- release_id=walkerhill-member-revenue-physical-v1.20260830.1
-- source_release_id=walkerhill-analysis-semantics-v1.20260827.1
-- target_dbms=Trino 483; target_schema=serving.analytics_v4_3
-- state=REVIEW_REQUIRED; script_type=MATERIALIZED_VIEW; execution_order=10; execution_default=NOT_RUN
-- purpose=회원 객실·식음 원천 집계를 독립적으로 물리화해 단일 지표 조회가 양쪽 원천을 반복 스캔하지 않게 한다.

CREATE OR REPLACE MATERIALIZED VIEW serving.analytics_v4_3.member_room_revenue_daily
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['month(business_date)'],
    sorted_by = ARRAY['business_date', 'hotel_code', 'tier_code']
)
AS
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
)
SELECT
    business_date,
    hotel_code,
    tier_code,
    tier_name,
    SUM(room_revenue_krw) AS room_revenue_krw
FROM room_attributed
GROUP BY 1, 2, 3, 4;

COMMENT ON MATERIALIZED VIEW serving.analytics_v4_3.member_room_revenue_daily IS 'PMS 객실박 매출을 거래 시점의 유효한 CRM 회원등급에 귀속해 영업일·호텔·등급별로 물리화한 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.member_room_revenue_daily.business_date IS '회원 객실박 매출이 귀속되는 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.member_room_revenue_daily.hotel_code IS '회원 객실박 매출이 발생한 GRAND·VISTA·DOUGLAS 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.member_room_revenue_daily.tier_code IS '객실박 매출 발생 시점의 CRM 유효기간 이력에서 확정한 멤버십 등급 코드';
COMMENT ON COLUMN serving.analytics_v4_3.member_room_revenue_daily.tier_name IS '등급 마스터에 등록된 멤버십 공개 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.member_room_revenue_daily.room_revenue_krw IS '매출 발생 시점에 회원으로 확인된 객실박의 원화 합성 객실매출';

CREATE OR REPLACE MATERIALIZED VIEW serving.analytics_v4_3.member_fnb_revenue_daily
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['month(business_date)'],
    sorted_by = ARRAY['business_date', 'hotel_code', 'tier_code']
)
AS
WITH fnb_events AS (
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
)
SELECT
    business_date,
    hotel_code,
    tier_code,
    tier_name,
    SUM(fnb_revenue_krw) AS fnb_revenue_krw
FROM fnb_attributed
GROUP BY 1, 2, 3, 4;

COMMENT ON MATERIALIZED VIEW serving.analytics_v4_3.member_fnb_revenue_daily IS 'POS 식음 순매출을 거래 시점의 유효한 CRM 회원등급에 귀속해 영업일·호텔·등급별로 물리화한 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.member_fnb_revenue_daily.business_date IS '회원 식음 순매출이 귀속되는 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.member_fnb_revenue_daily.hotel_code IS '회원 식음 순매출이 발생한 GRAND·VISTA·DOUGLAS 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.member_fnb_revenue_daily.tier_code IS '식음 순매출 발생 시점의 CRM 유효기간 이력에서 확정한 멤버십 등급 코드';
COMMENT ON COLUMN serving.analytics_v4_3.member_fnb_revenue_daily.tier_name IS '등급 마스터에 등록된 멤버십 공개 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.member_fnb_revenue_daily.fnb_revenue_krw IS '주문 시점에 회원으로 확인된 POS 주문의 원화 합성 식음 순매출';

CREATE OR REPLACE VIEW serving.analytics_v4_3.member_revenue_daily AS
SELECT
    COALESCE(r.business_date, f.business_date) AS business_date,
    COALESCE(r.hotel_code, f.hotel_code) AS hotel_code,
    COALESCE(r.tier_code, f.tier_code) AS tier_code,
    COALESCE(r.tier_name, f.tier_name) AS tier_name,
    COALESCE(r.room_revenue_krw, DECIMAL '0') AS room_revenue_krw,
    COALESCE(f.fnb_revenue_krw, DECIMAL '0') AS fnb_revenue_krw
FROM serving.analytics_v4_3.member_room_revenue_daily r
FULL OUTER JOIN serving.analytics_v4_3.member_fnb_revenue_daily f
  ON f.business_date = r.business_date
 AND f.hotel_code = r.hotel_code
 AND f.tier_code = r.tier_code;

COMMENT ON VIEW serving.analytics_v4_3.member_revenue_daily IS '물리화된 회원 객실·식음 일별 집계를 결합해 기존 지표·차원 계약을 보존하는 재사용 합성 fact';
COMMENT ON COLUMN serving.analytics_v4_3.member_revenue_daily.business_date IS '객실박 또는 POS 주문 매출이 귀속되는 영업일';
COMMENT ON COLUMN serving.analytics_v4_3.member_revenue_daily.hotel_code IS '회원 매출이 발생한 GRAND·VISTA·DOUGLAS 합성 호텔 코드';
COMMENT ON COLUMN serving.analytics_v4_3.member_revenue_daily.tier_code IS '매출 발생 시점의 CRM 유효기간 이력에서 확정한 멤버십 등급 코드';
COMMENT ON COLUMN serving.analytics_v4_3.member_revenue_daily.tier_name IS '등급 마스터에 등록된 멤버십 공개 표시명';
COMMENT ON COLUMN serving.analytics_v4_3.member_revenue_daily.room_revenue_krw IS '매출 발생 시점에 회원으로 확인된 객실박의 원화 합성 객실매출';
COMMENT ON COLUMN serving.analytics_v4_3.member_revenue_daily.fnb_revenue_krw IS '주문 시점에 회원으로 확인된 POS 주문의 원화 합성 식음 순매출';
