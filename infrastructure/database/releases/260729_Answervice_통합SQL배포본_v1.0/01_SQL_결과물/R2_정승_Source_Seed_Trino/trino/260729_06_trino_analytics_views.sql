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
-- work_card=R2-TRINO
-- output=260729_06_trino_analytics_views.sql

-- ============================================================================
-- 260729_06_trino_analytics_views.sql
-- Answervice cross-source analytics schema contract v4.6
-- Trino setup 관리자 세션 전용
-- catalogs: app, pms, pos, crm, facility, banquet
-- schema_version=schema-v4.6-websql
-- 일반 분석 실행 계정은 이 View들에 대한 SELECT만 허용한다.
-- 원시 fact는 먼저 목표 grain으로 집계한 뒤 결합한다.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS app.analytics;

-- ----------------------------------------------------------------------------
-- 1. 일별 객실 운영 지표
-- grain: property_id + business_date + room_type_code + period status
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW app.analytics.hotel_daily_metrics AS
WITH inventory AS (
    SELECT
        property_id,
        business_date,
        room_type_code,
        data_period_status,
        is_forecast,
        SUM(physical_rooms) AS physical_rooms,
        SUM(out_of_order_rooms) AS out_of_order_rooms,
        SUM(house_use_rooms) AS house_use_rooms,
        SUM(available_room_nights) AS available_room_nights,
        MAX(source_updated_at) AS pms_inventory_watermark
    FROM pms.public.pms_room_inventory_daily
    WHERE source_updated_at <= CURRENT_TIMESTAMP
    GROUP BY property_id, business_date, room_type_code, data_period_status, is_forecast
),
stay_base AS (
    SELECT
        property_id,
        stay_id,
        room_unit_code,
        room_type_code,
        CAST(at_timezone(actual_checkin_at, 'Asia/Seoul') AS date) AS checkin_date,
        CAST(at_timezone(actual_checkout_at, 'Asia/Seoul') AS date) AS checkout_date,
        occupied_room_nights,
        CAST(room_revenue AS decimal(18,2)) AS room_revenue,
        data_period_status,
        is_forecast,
        source_updated_at,
        CAST(
            floor(CAST(room_revenue AS double) * 100.0 / NULLIF(occupied_room_nights, 0)) / 100.0
            AS decimal(18,2)
        ) AS daily_base_revenue
    FROM pms.public.pms_stays
    WHERE stay_status = 'COMPLETED'
      AND is_forecast = false
      AND data_period_status <> 'FORECAST_SCENARIO'
      AND complimentary_flag = false
      AND house_use_flag = false
      AND actual_checkin_at IS NOT NULL
      AND actual_checkout_at IS NOT NULL
      AND occupied_room_nights > 0
      AND source_updated_at <= CURRENT_TIMESTAMP
),
stay_nights AS (
    SELECT
        s.property_id,
        d AS business_date,
        s.room_type_code,
        s.data_period_status,
        s.is_forecast,
        s.room_unit_code,
        CASE
            WHEN d = date_add('day', -1, s.checkout_date)
                THEN CAST(
                    s.room_revenue
                    - (s.daily_base_revenue * CAST(s.occupied_room_nights - 1 AS decimal(18,2)))
                    AS decimal(18,2)
                )
            ELSE s.daily_base_revenue
        END AS daily_room_revenue,
        s.source_updated_at
    FROM stay_base s
    CROSS JOIN UNNEST(sequence(s.checkin_date, date_add('day', -1, s.checkout_date))) AS u(d)
),
stay_daily AS (
    SELECT
        property_id,
        business_date,
        room_type_code,
        data_period_status,
        is_forecast,
        COUNT(DISTINCT room_unit_code) AS rooms_sold,
        CAST(SUM(daily_room_revenue) AS decimal(18,2)) AS room_revenue,
        MAX(source_updated_at) AS pms_stay_watermark
    FROM stay_nights
    GROUP BY property_id, business_date, room_type_code, data_period_status, is_forecast
)
SELECT
    COALESCE(i.property_id, s.property_id) AS property_id,
    COALESCE(i.business_date, s.business_date) AS business_date,
    COALESCE(i.room_type_code, s.room_type_code) AS room_type_code,
    'ROOMS' AS business_unit_code,
    COALESCE(i.data_period_status, s.data_period_status) AS data_period_status,
    COALESCE(i.is_forecast, s.is_forecast) AS is_forecast,
    COALESCE(i.physical_rooms, 0) AS physical_rooms,
    COALESCE(i.out_of_order_rooms, 0) AS out_of_order_rooms,
    COALESCE(i.house_use_rooms, 0) AS house_use_rooms,
    COALESCE(i.available_room_nights, 0) AS available_room_nights,
    COALESCE(s.rooms_sold, 0) AS rooms_sold,
    COALESCE(s.room_revenue, CAST(0 AS decimal(18,2))) AS room_revenue,
    CAST(
        CAST(COALESCE(s.rooms_sold, 0) AS decimal(18,6))
        / NULLIF(CAST(COALESCE(i.available_room_nights, 0) AS decimal(18,6)), CAST(0 AS decimal(18,6)))
        AS decimal(18,6)
    ) AS occupancy_rate,
    CAST(
        COALESCE(s.room_revenue, CAST(0 AS decimal(18,2)))
        / NULLIF(CAST(COALESCE(s.rooms_sold, 0) AS decimal(18,2)), CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS adr_krw,
    CAST(
        COALESCE(s.room_revenue, CAST(0 AS decimal(18,2)))
        / NULLIF(CAST(COALESCE(i.available_room_nights, 0) AS decimal(18,2)), CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS revpar_krw,
    CASE
        WHEN COALESCE(i.available_room_nights, 0) = 0 THEN 'ZERO_DENOMINATOR'
        ELSE NULL
    END AS occupancy_reason_code,
    CASE
        WHEN COALESCE(s.rooms_sold, 0) = 0 THEN 'ZERO_DENOMINATOR'
        ELSE NULL
    END AS adr_reason_code,
    i.pms_inventory_watermark,
    s.pms_stay_watermark
FROM inventory i
FULL OUTER JOIN stay_daily s
  ON i.property_id = s.property_id
 AND i.business_date = s.business_date
 AND i.room_type_code = s.room_type_code
 AND i.data_period_status = s.data_period_status
 AND i.is_forecast = s.is_forecast;

-- ----------------------------------------------------------------------------
-- 2. 월별 통합 운영 지표
-- source별 월 집계를 UNION ALL한 뒤 최종 집계한다.
-- grain: property_id + year_month + business_unit_code + period status
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW app.analytics.hotel_monthly_metrics AS
WITH rooms_monthly AS (
    SELECT
        property_id,
        date_trunc('month', CAST(business_date AS timestamp)) AS month_start,
        data_period_status,
        is_forecast,
        SUM(available_room_nights) AS available_room_nights,
        SUM(rooms_sold) AS rooms_sold,
        CAST(SUM(room_revenue) AS decimal(18,2)) AS operating_revenue,
        MAX(pms_inventory_watermark) AS pms_inventory_watermark,
        MAX(pms_stay_watermark) AS pms_stay_watermark
    FROM app.analytics.hotel_daily_metrics
    GROUP BY property_id, date_trunc('month', CAST(business_date AS timestamp)),
             data_period_status, is_forecast
),
fnb_monthly AS (
    SELECT
        property_id,
        date_trunc(
            'month',
            CAST(at_timezone(with_timezone(ordered_at, 'UTC'), 'Asia/Seoul') AS timestamp)
        ) AS month_start,
        data_period_status,
        is_forecast,
        CAST(SUM(net_amount) AS decimal(18,2)) AS operating_revenue,
        MAX(at_timezone(with_timezone(source_updated_at, 'UTC'), 'UTC')) AS pos_watermark
    FROM pos.hotel_pos.pos_orders
    WHERE order_status IN ('PAID','PARTIAL_REFUND')
      AND is_forecast = false
      AND source_updated_at <= CAST(CURRENT_TIMESTAMP AT TIME ZONE 'UTC' AS timestamp)
    GROUP BY property_id,
             date_trunc('month', CAST(at_timezone(with_timezone(ordered_at, 'UTC'), 'Asia/Seoul') AS timestamp)),
             data_period_status, is_forecast
),
facility_monthly AS (
    SELECT
        property_id,
        date_trunc('month', CAST(at_timezone(event_at, 'Asia/Seoul') AS timestamp)) AS month_start,
        data_period_status,
        (is_forecast = 1) AS is_forecast,
        CAST(SUM(CASE WHEN event_type='USAGE' AND event_status='COMPLETED' THEN amount ELSE 0 END) AS decimal(18,2))
            AS operating_revenue,
        MAX(source_updated_at) AS facility_watermark
    FROM facility.hotel_facility.facility_events
    WHERE is_forecast = 0
      AND source_updated_at <= CURRENT_TIMESTAMP
    GROUP BY property_id,
             date_trunc('month', CAST(at_timezone(event_at, 'Asia/Seoul') AS timestamp)),
             data_period_status, (is_forecast = 1)
),
banquet_monthly AS (
    SELECT
        property_id,
        date_trunc('month', CAST(recognized_date AS timestamp)) AS month_start,
        data_period_status,
        is_forecast,
        CAST(SUM(
            CASE
                WHEN revenue_status='RECOGNIZED' THEN revenue_amount
                WHEN revenue_status='REVERSED' THEN -reversal_amount
                ELSE 0
            END
        ) AS decimal(18,2)) AS operating_revenue,
        MAX(source_updated_at) AS banquet_watermark
    FROM banquet.public.banquet_revenue
    WHERE is_forecast = false
      AND revenue_status IN ('RECOGNIZED','REVERSED')
      AND source_updated_at <= CURRENT_TIMESTAMP
    GROUP BY property_id, date_trunc('month', CAST(recognized_date AS timestamp)),
             data_period_status, is_forecast
),
source_rows AS (
    SELECT property_id, month_start, 'ROOMS' AS business_unit_code,
           data_period_status, is_forecast,
           available_room_nights, rooms_sold, operating_revenue,
           pms_inventory_watermark, pms_stay_watermark,
           CAST(NULL AS timestamp with time zone) AS pos_watermark,
           CAST(NULL AS timestamp with time zone) AS facility_watermark,
           CAST(NULL AS timestamp with time zone) AS banquet_watermark
    FROM rooms_monthly
    UNION ALL
    SELECT property_id, month_start, 'FNB',
           data_period_status, is_forecast,
           CAST(0 AS bigint), CAST(0 AS bigint), operating_revenue,
           CAST(NULL AS timestamp with time zone), CAST(NULL AS timestamp with time zone),
           pos_watermark, CAST(NULL AS timestamp with time zone), CAST(NULL AS timestamp with time zone)
    FROM fnb_monthly
    UNION ALL
    SELECT property_id, month_start, 'FACILITY',
           data_period_status, is_forecast,
           CAST(0 AS bigint), CAST(0 AS bigint), operating_revenue,
           CAST(NULL AS timestamp with time zone), CAST(NULL AS timestamp with time zone),
           CAST(NULL AS timestamp with time zone), facility_watermark, CAST(NULL AS timestamp with time zone)
    FROM facility_monthly
    UNION ALL
    SELECT property_id, month_start, 'BANQUET',
           data_period_status, is_forecast,
           CAST(0 AS bigint), CAST(0 AS bigint), operating_revenue,
           CAST(NULL AS timestamp with time zone), CAST(NULL AS timestamp with time zone),
           CAST(NULL AS timestamp with time zone), CAST(NULL AS timestamp with time zone), banquet_watermark
    FROM banquet_monthly
),
aggregated AS (
    SELECT
        property_id,
        month_start,
        business_unit_code,
        data_period_status,
        is_forecast,
        SUM(available_room_nights) AS unit_available_room_nights,
        SUM(rooms_sold) AS unit_rooms_sold,
        CAST(SUM(operating_revenue) AS decimal(18,2)) AS operating_revenue,
        MAX(pms_inventory_watermark) AS pms_inventory_watermark,
        MAX(pms_stay_watermark) AS pms_stay_watermark,
        MAX(pos_watermark) AS pos_watermark,
        MAX(facility_watermark) AS facility_watermark,
        MAX(banquet_watermark) AS banquet_watermark
    FROM source_rows
    GROUP BY property_id, month_start, business_unit_code, data_period_status, is_forecast
)
SELECT
    a.property_id,
    CAST(a.month_start AS date) AS month_start,
    format_datetime(a.month_start, 'yyyy-MM') AS year_month,
    a.business_unit_code,
    a.data_period_status,
    a.is_forecast,
    COALESCE(r.available_room_nights, 0) AS available_room_nights,
    COALESCE(r.rooms_sold, 0) AS rooms_sold,
    a.operating_revenue,
    CAST(
        a.operating_revenue
        / NULLIF(CAST(COALESCE(r.available_room_nights, 0) AS decimal(18,2)), CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS trevpar_krw,
    CAST(
        a.operating_revenue
        / NULLIF(CAST(COALESCE(r.rooms_sold, 0) AS decimal(18,2)), CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS revpor_krw,
    CASE
        WHEN COALESCE(r.available_room_nights, 0)=0 THEN 'ZERO_DENOMINATOR'
        ELSE NULL
    END AS trevpar_reason_code,
    CASE
        WHEN COALESCE(r.rooms_sold, 0)=0 THEN 'ZERO_DENOMINATOR'
        ELSE NULL
    END AS revpor_reason_code,
    a.pms_inventory_watermark,
    a.pms_stay_watermark,
    a.pos_watermark,
    a.facility_watermark,
    a.banquet_watermark
FROM aggregated a
LEFT JOIN rooms_monthly r
  ON r.property_id=a.property_id
 AND r.month_start=a.month_start
 AND r.data_period_status=a.data_period_status
 AND r.is_forecast=a.is_forecast;

-- ----------------------------------------------------------------------------
-- 3. 연도별 운영·시장 기준점 비교
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW app.analytics.hotel_yearly_metrics AS
WITH annual AS (
    SELECT
        property_id,
        year(month_start) AS metric_year,
        business_unit_code,
        data_period_status,
        is_forecast,
        SUM(available_room_nights) AS available_room_nights,
        SUM(rooms_sold) AS rooms_sold,
        CAST(SUM(operating_revenue) AS decimal(18,2)) AS operating_revenue,
        MAX(pms_inventory_watermark) AS pms_inventory_watermark,
        MAX(pms_stay_watermark) AS pms_stay_watermark,
        MAX(pos_watermark) AS pos_watermark,
        MAX(facility_watermark) AS facility_watermark,
        MAX(banquet_watermark) AS banquet_watermark
    FROM app.analytics.hotel_monthly_metrics
    GROUP BY property_id, year(month_start), business_unit_code, data_period_status, is_forecast
)
SELECT
    a.property_id,
    a.metric_year,
    a.business_unit_code,
    a.data_period_status,
    a.is_forecast,
    a.available_room_nights,
    a.rooms_sold,
    a.operating_revenue,
    CAST(
        CAST(a.rooms_sold AS decimal(18,6))
        / NULLIF(CAST(a.available_room_nights AS decimal(18,6)), CAST(0 AS decimal(18,6)))
        AS decimal(18,6)
    ) AS occupancy_rate,
    CAST(
        a.operating_revenue
        / NULLIF(CAST(a.rooms_sold AS decimal(18,2)), CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS adr_or_revpor_krw,
    CAST(
        a.operating_revenue
        / NULLIF(CAST(a.available_room_nights AS decimal(18,2)), CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS revpar_or_trevpar_krw,
    b.population_code AS benchmark_population_code,
    b.occupancy_rate AS benchmark_occupancy_rate,
    b.adr_krw AS benchmark_adr_krw,
    b.revpar_krw AS benchmark_revpar_krw,
    b.reference_status AS benchmark_reference_status,
    CASE
        WHEN a.available_room_nights=0 OR a.rooms_sold=0 THEN 'ZERO_DENOMINATOR'
        ELSE NULL
    END AS metric_reason_code,
    a.pms_inventory_watermark,
    a.pms_stay_watermark,
    a.pos_watermark,
    a.facility_watermark,
    a.banquet_watermark
FROM annual a
LEFT JOIN app.reference.market_benchmark_annual b
  ON b.benchmark_year=a.metric_year
 AND b.population_code='HOTEL_INDUSTRY';

-- ----------------------------------------------------------------------------
-- 4. F&B 시간대 지표
-- order item을 order grain으로 먼저 정합화한 뒤 service period와 결합한다.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW app.analytics.fnb_daypart_metrics AS
WITH item_by_order AS (
    SELECT
        property_id,
        order_id,
        CAST(SUM(gross_amount) AS decimal(18,2)) AS item_gross_amount,
        CAST(SUM(discount_amount) AS decimal(18,2)) AS item_discount_amount,
        CAST(SUM(net_amount) AS decimal(18,2)) AS item_net_amount,
        MAX(at_timezone(with_timezone(source_updated_at, 'UTC'), 'UTC')) AS item_watermark
    FROM pos.hotel_pos.pos_order_items
    GROUP BY property_id, order_id
),
order_grain AS (
    SELECT
        o.property_id,
        o.store_id,
        CAST(at_timezone(with_timezone(o.ordered_at, 'UTC'), 'Asia/Seoul') AS date) AS business_date,
        o.service_period,
        o.data_period_status,
        o.is_forecast,
        o.order_id,
        o.guest_count,
        CAST(o.net_amount AS decimal(18,2)) AS order_net_amount,
        i.item_gross_amount,
        i.item_discount_amount,
        i.item_net_amount,
        MAX(at_timezone(with_timezone(o.source_updated_at, 'UTC'), 'UTC')) AS order_watermark,
        MAX(i.item_watermark) AS item_watermark
    FROM pos.hotel_pos.pos_orders o
    LEFT JOIN item_by_order i
      ON i.property_id=o.property_id AND i.order_id=o.order_id
    WHERE o.order_status IN ('PAID','PARTIAL_REFUND')
      AND o.is_forecast=false
      AND o.source_updated_at <= CAST(CURRENT_TIMESTAMP AT TIME ZONE 'UTC' AS timestamp)
    GROUP BY o.property_id,o.store_id,
             CAST(at_timezone(with_timezone(o.ordered_at, 'UTC'), 'Asia/Seoul') AS date),
             o.service_period,o.data_period_status,o.is_forecast,o.order_id,o.guest_count,
             CAST(o.net_amount AS decimal(18,2)),
             i.item_gross_amount,i.item_discount_amount,i.item_net_amount
),
orders_agg AS (
    SELECT
        property_id,store_id,business_date,service_period,data_period_status,is_forecast,
        COUNT(*) AS order_count,
        SUM(guest_count) AS order_guest_count,
        CAST(SUM(order_net_amount) AS decimal(18,2)) AS fnb_net_revenue,
        CAST(SUM(COALESCE(item_net_amount,0)) AS decimal(18,2)) AS item_net_revenue,
        MAX(order_watermark) AS order_watermark,
        MAX(item_watermark) AS item_watermark
    FROM order_grain
    GROUP BY property_id,store_id,business_date,service_period,data_period_status,is_forecast
),
service_agg AS (
    SELECT
        property_id,store_id,business_date,service_period,data_period_status,is_forecast,
        SUM(covers) AS covers,
        CAST(SUM(seat_hours_available) AS decimal(18,2)) AS seat_hours_available,
        CAST(SUM(seat_hours_used) AS decimal(18,2)) AS seat_hours_used,
        MAX(at_timezone(with_timezone(source_updated_at, 'UTC'), 'UTC')) AS service_watermark
    FROM pos.hotel_pos.pos_service_periods
    GROUP BY property_id,store_id,business_date,service_period,data_period_status,is_forecast
)
SELECT
    COALESCE(s.property_id,o.property_id) AS property_id,
    COALESCE(s.store_id,o.store_id) AS store_id,
    COALESCE(s.business_date,o.business_date) AS business_date,
    COALESCE(s.service_period,o.service_period) AS service_period,
    'FNB' AS business_unit_code,
    COALESCE(s.data_period_status,o.data_period_status) AS data_period_status,
    COALESCE(s.is_forecast,o.is_forecast) AS is_forecast,
    COALESCE(s.covers,0) AS covers,
    COALESCE(o.order_count,0) AS order_count,
    COALESCE(o.fnb_net_revenue,CAST(0 AS decimal(18,2))) AS fnb_net_revenue,
    COALESCE(s.seat_hours_available,CAST(0 AS decimal(18,2))) AS seat_hours_available,
    COALESCE(s.seat_hours_used,CAST(0 AS decimal(18,2))) AS seat_hours_used,
    CAST(
        COALESCE(o.fnb_net_revenue,CAST(0 AS decimal(18,2)))
        / NULLIF(CAST(COALESCE(s.covers,0) AS decimal(18,2)),CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS average_check_krw,
    CAST(
        COALESCE(o.fnb_net_revenue,CAST(0 AS decimal(18,2)))
        / NULLIF(COALESCE(s.seat_hours_available,CAST(0 AS decimal(18,2))),CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS revpash_krw,
    CAST(
        COALESCE(o.fnb_net_revenue,CAST(0 AS decimal(18,2)))
        - COALESCE(o.item_net_revenue,CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS order_item_variance_amount,
    CASE WHEN COALESCE(s.seat_hours_available,0)=0 THEN 'ZERO_DENOMINATOR' ELSE NULL END AS revpash_reason_code,
    s.service_watermark,
    o.order_watermark,
    o.item_watermark
FROM service_agg s
FULL OUTER JOIN orders_agg o
  ON s.property_id=o.property_id
 AND s.store_id=o.store_id
 AND s.business_date=o.business_date
 AND s.service_period=o.service_period
 AND s.data_period_status=o.data_period_status
 AND s.is_forecast=o.is_forecast;

-- ----------------------------------------------------------------------------
-- 5. 시설 일별 이용·장애 지표
-- USAGE와 INCIDENT를 각각 집계한 뒤 facility grain에서 결합한다.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW app.analytics.facility_daily_metrics AS
WITH usage_daily AS (
    SELECT
        property_id,
        facility_id,
        CAST(at_timezone(event_at,'Asia/Seoul') AS date) AS business_date,
        data_period_status,
        (is_forecast = 1) AS is_forecast,
        COUNT_IF(event_type='USAGE' AND event_status='COMPLETED') AS completed_usage_count,
        CAST(SUM(CASE WHEN event_type='USAGE' AND event_status='COMPLETED' THEN amount ELSE 0 END) AS decimal(18,2))
            AS usage_revenue,
        MAX(source_updated_at) AS usage_watermark
    FROM facility.hotel_facility.facility_events
    WHERE event_type='USAGE'
      AND source_updated_at<=CURRENT_TIMESTAMP
    GROUP BY property_id,facility_id,CAST(at_timezone(event_at,'Asia/Seoul') AS date),
             data_period_status,(is_forecast = 1)
),
incident_daily AS (
    SELECT
        property_id,
        facility_id,
        CAST(at_timezone(event_at,'Asia/Seoul') AS date) AS business_date,
        data_period_status,
        (is_forecast = 1) AS is_forecast,
        COUNT_IF(event_type='INCIDENT') AS incident_count,
        SUM(CASE WHEN event_type='INCIDENT' THEN downtime_minutes ELSE 0 END) AS downtime_minutes,
        MAX(source_updated_at) AS incident_watermark
    FROM facility.hotel_facility.facility_events
    WHERE event_type='INCIDENT'
      AND source_updated_at<=CURRENT_TIMESTAMP
    GROUP BY property_id,facility_id,CAST(at_timezone(event_at,'Asia/Seoul') AS date),
             data_period_status,(is_forecast = 1)
)
SELECT
    COALESCE(u.property_id,i.property_id) AS property_id,
    COALESCE(u.facility_id,i.facility_id) AS facility_id,
    m.facility_name,
    m.facility_type,
    COALESCE(u.business_date,i.business_date) AS business_date,
    'FACILITY' AS business_unit_code,
    COALESCE(u.data_period_status,i.data_period_status) AS data_period_status,
    COALESCE(u.is_forecast,i.is_forecast) AS is_forecast,
    COALESCE(u.completed_usage_count,0) AS completed_usage_count,
    COALESCE(i.incident_count,0) AS incident_count,
    COALESCE(i.downtime_minutes,0) AS downtime_minutes,
    COALESCE(u.usage_revenue,CAST(0 AS decimal(18,2))) AS usage_revenue,
    CAST(
        COALESCE(u.usage_revenue,CAST(0 AS decimal(18,2)))
        / NULLIF(CAST(COALESCE(u.completed_usage_count,0) AS decimal(18,2)),CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS revenue_per_usage_krw,
    CASE WHEN COALESCE(u.completed_usage_count,0)=0 THEN 'ZERO_DENOMINATOR' ELSE NULL END AS revenue_per_usage_reason_code,
    u.usage_watermark,
    i.incident_watermark,
    m.source_updated_at AS facility_master_watermark
FROM usage_daily u
FULL OUTER JOIN incident_daily i
  ON u.property_id=i.property_id
 AND u.facility_id=i.facility_id
 AND u.business_date=i.business_date
 AND u.data_period_status=i.data_period_status
 AND u.is_forecast=i.is_forecast
LEFT JOIN facility.hotel_facility.facility_master m
  ON m.property_id=COALESCE(u.property_id,i.property_id)
 AND m.facility_id=COALESCE(u.facility_id,i.facility_id);

-- ----------------------------------------------------------------------------
-- 6. 연회 월별 지표
-- booking과 revenue를 각각 월·상품 grain으로 집계한 뒤 결합한다.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW app.analytics.banquet_monthly_metrics AS
WITH booking_monthly AS (
    SELECT
        property_id,
        date_trunc('month',CAST(event_date AS timestamp)) AS month_start,
        product_category,
        data_period_status,
        is_forecast,
        COUNT(*) AS inquiry_count,
        COUNT_IF(booking_status='CONFIRMED') AS confirmed_count,
        COUNT_IF(booking_status='CANCELLED') AS cancelled_count,
        COUNT_IF(booking_status='COMPLETED') AS completed_count,
        SUM(expected_guests) AS expected_guests,
        SUM(COALESCE(actual_attendees,0)) AS actual_attendees,
        SUM(reserved_room_block_count) AS reserved_room_block_count,
        SUM(pickup_room_count) AS pickup_room_count,
        MAX(source_updated_at) AS booking_watermark
    FROM banquet.public.banquet_bookings
    WHERE source_updated_at<=CURRENT_TIMESTAMP
    GROUP BY property_id,date_trunc('month',CAST(event_date AS timestamp)),
             product_category,data_period_status,is_forecast
),
revenue_monthly AS (
    SELECT
        property_id,
        date_trunc('month',CAST(recognized_date AS timestamp)) AS month_start,
        product_category,
        data_period_status,
        is_forecast,
        CAST(SUM(CASE WHEN revenue_status='EXPECTED' THEN revenue_amount ELSE 0 END) AS decimal(18,2))
            AS expected_revenue,
        CAST(SUM(CASE WHEN revenue_status='RECOGNIZED' THEN revenue_amount ELSE 0 END) AS decimal(18,2))
            AS recognized_revenue,
        CAST(SUM(CASE WHEN revenue_status='REVERSED' THEN reversal_amount ELSE 0 END) AS decimal(18,2))
            AS reversal_amount,
        CAST(SUM(CASE WHEN revenue_status='RECOGNIZED' THEN cost_amount ELSE 0 END) AS decimal(18,2))
            AS recognized_cost,
        MAX(source_updated_at) AS revenue_watermark
    FROM banquet.public.banquet_revenue
    WHERE source_updated_at<=CURRENT_TIMESTAMP
    GROUP BY property_id,date_trunc('month',CAST(recognized_date AS timestamp)),
             product_category,data_period_status,is_forecast
)
SELECT
    COALESCE(b.property_id,r.property_id) AS property_id,
    CAST(COALESCE(b.month_start,r.month_start) AS date) AS month_start,
    COALESCE(b.product_category,r.product_category) AS product_category,
    'BANQUET' AS business_unit_code,
    COALESCE(b.data_period_status,r.data_period_status) AS data_period_status,
    COALESCE(b.is_forecast,r.is_forecast) AS is_forecast,
    COALESCE(b.inquiry_count,0) AS inquiry_count,
    COALESCE(b.confirmed_count,0) AS confirmed_count,
    COALESCE(b.cancelled_count,0) AS cancelled_count,
    COALESCE(b.completed_count,0) AS completed_count,
    COALESCE(b.expected_guests,0) AS expected_guests,
    COALESCE(b.actual_attendees,0) AS actual_attendees,
    COALESCE(b.reserved_room_block_count,0) AS reserved_room_block_count,
    COALESCE(b.pickup_room_count,0) AS pickup_room_count,
    COALESCE(r.expected_revenue,CAST(0 AS decimal(18,2))) AS expected_revenue,
    COALESCE(r.recognized_revenue,CAST(0 AS decimal(18,2))) AS recognized_revenue,
    COALESCE(r.reversal_amount,CAST(0 AS decimal(18,2))) AS reversal_amount,
    CAST(
        COALESCE(r.recognized_revenue,CAST(0 AS decimal(18,2)))
        - COALESCE(r.reversal_amount,CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS net_recognized_revenue,
    COALESCE(r.recognized_cost,CAST(0 AS decimal(18,2))) AS recognized_cost,
    b.booking_watermark,
    r.revenue_watermark
FROM booking_monthly b
FULL OUTER JOIN revenue_monthly r
  ON b.property_id=r.property_id
 AND b.month_start=r.month_start
 AND b.product_category=r.product_category
 AND b.data_period_status=r.data_period_status
 AND b.is_forecast=r.is_forecast;

-- ----------------------------------------------------------------------------
-- 7. 인력 월별 지표
-- staffing 월 집계와 PMS 판매 객실 월 집계를 결합한다.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW app.analytics.workforce_monthly_metrics AS
WITH staffing_monthly AS (
    SELECT
        property_id,
        date_trunc('month',CAST(business_date AS timestamp)) AS month_start,
        department,
        data_period_status,
        (is_forecast = 1) AS is_forecast,
        SUM(approved_positions) AS approved_positions,
        SUM(scheduled_hours) AS scheduled_hours,
        SUM(worked_hours) AS worked_hours,
        CAST(SUM(labor_cost) AS decimal(18,2)) AS labor_cost,
        SUM(fte) AS fte,
        SUM(vacancies) AS vacancies,
        MAX(source_updated_at) AS staffing_watermark
    FROM facility.hotel_facility.hotel_staffing_daily
    GROUP BY property_id,date_trunc('month',CAST(business_date AS timestamp)),
             department,data_period_status,(is_forecast = 1)
),
rooms_monthly AS (
    SELECT
        property_id,
        date_trunc('month',CAST(business_date AS timestamp)) AS month_start,
        data_period_status,
        is_forecast,
        SUM(rooms_sold) AS rooms_sold,
        MAX(pms_stay_watermark) AS pms_stay_watermark
    FROM app.analytics.hotel_daily_metrics
    GROUP BY property_id,date_trunc('month',CAST(business_date AS timestamp)),
             data_period_status,is_forecast
)
SELECT
    s.property_id,
    CAST(s.month_start AS date) AS month_start,
    s.department,
    s.data_period_status,
    s.is_forecast,
    s.approved_positions,
    s.scheduled_hours,
    s.worked_hours,
    s.labor_cost,
    s.fte,
    s.vacancies,
    COALESCE(r.rooms_sold,0) AS rooms_sold,
    CAST(
        s.worked_hours
        / NULLIF(CAST(COALESCE(r.rooms_sold,0) AS double),0.0)
        AS decimal(18,6)
    ) AS hpor,
    CAST(
        s.labor_cost
        / NULLIF(CAST(COALESCE(r.rooms_sold,0) AS decimal(18,2)),CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS labor_cpor_krw,
    CASE WHEN COALESCE(r.rooms_sold,0)=0 THEN 'ZERO_DENOMINATOR' ELSE NULL END AS productivity_reason_code,
    s.staffing_watermark,
    r.pms_stay_watermark
FROM staffing_monthly s
LEFT JOIN rooms_monthly r
  ON r.property_id=s.property_id
 AND r.month_start=s.month_start
 AND r.data_period_status=s.data_period_status
 AND r.is_forecast=s.is_forecast;

-- ----------------------------------------------------------------------------
-- 8. 자원 월별 지표
-- resource 월 집계와 PMS occupied room nights 월 집계를 결합한다.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW app.analytics.resource_monthly_metrics AS
WITH resource_monthly AS (
    SELECT
        property_id,
        date_trunc('month',CAST(business_date AS timestamp)) AS month_start,
        resource_scope,
        data_period_status,
        (is_forecast = 1) AS is_forecast,
        SUM(energy_kwh) AS energy_kwh,
        SUM(water_m3) AS water_m3,
        SUM(waste_kg) AS waste_kg,
        CAST(SUM(resource_cost) AS decimal(18,2)) AS resource_cost,
        SUM(scheduled_hours) AS scheduled_hours,
        SUM(downtime_hours) AS downtime_hours,
        MAX(source_updated_at) AS resource_watermark
    FROM facility.hotel_facility.facility_resource_daily
    GROUP BY property_id,date_trunc('month',CAST(business_date AS timestamp)),
             resource_scope,data_period_status,(is_forecast = 1)
),
room_nights AS (
    SELECT
        property_id,
        date_trunc('month',CAST(business_date AS timestamp)) AS month_start,
        data_period_status,
        is_forecast,
        SUM(rooms_sold) AS occupied_room_nights,
        MAX(pms_stay_watermark) AS pms_stay_watermark
    FROM app.analytics.hotel_daily_metrics
    GROUP BY property_id,date_trunc('month',CAST(business_date AS timestamp)),
             data_period_status,is_forecast
)
SELECT
    r.property_id,
    CAST(r.month_start AS date) AS month_start,
    r.resource_scope,
    r.data_period_status,
    r.is_forecast,
    r.energy_kwh,
    r.water_m3,
    r.waste_kg,
    r.resource_cost,
    r.scheduled_hours,
    r.downtime_hours,
    COALESCE(n.occupied_room_nights,0) AS occupied_room_nights,
    CAST(r.energy_kwh / NULLIF(CAST(COALESCE(n.occupied_room_nights,0) AS double),0.0) AS decimal(18,6))
        AS energy_kwh_per_occupied_room,
    CAST(r.water_m3 / NULLIF(CAST(COALESCE(n.occupied_room_nights,0) AS double),0.0) AS decimal(18,6))
        AS water_m3_per_occupied_room,
    CAST(r.waste_kg / NULLIF(CAST(COALESCE(n.occupied_room_nights,0) AS double),0.0) AS decimal(18,6))
        AS waste_kg_per_occupied_room,
    CAST(
        r.resource_cost
        / NULLIF(CAST(COALESCE(n.occupied_room_nights,0) AS decimal(18,2)),CAST(0 AS decimal(18,2)))
        AS decimal(18,2)
    ) AS resource_cost_per_occupied_room_krw,
    CASE WHEN COALESCE(n.occupied_room_nights,0)=0 THEN 'ZERO_DENOMINATOR' ELSE NULL END AS resource_reason_code,
    r.resource_watermark,
    n.pms_stay_watermark
FROM resource_monthly r
LEFT JOIN room_nights n
  ON n.property_id=r.property_id
 AND n.month_start=r.month_start
 AND n.data_period_status=r.data_period_status
 AND n.is_forecast=r.is_forecast;

-- ----------------------------------------------------------------------------
-- 구조·권한 검증
-- ----------------------------------------------------------------------------
SELECT table_catalog, table_schema, table_name
FROM app.information_schema.views
WHERE table_schema='analytics'
  AND table_name IN (
    'hotel_daily_metrics','hotel_monthly_metrics','hotel_yearly_metrics',
    'fnb_daypart_metrics','facility_daily_metrics','banquet_monthly_metrics',
    'workforce_monthly_metrics','resource_monthly_metrics'
  )
ORDER BY table_name;

SELECT COUNT(*) AS trino_view_count,
       CASE WHEN COUNT(*)=8 THEN 'PASS' ELSE 'SCHEMA_CONTRACT_MISMATCH' END AS status
FROM app.information_schema.views
WHERE table_schema='analytics'
  AND table_name IN (
    'hotel_daily_metrics','hotel_monthly_metrics','hotel_yearly_metrics',
    'fnb_daypart_metrics','facility_daily_metrics','banquet_monthly_metrics',
    'workforce_monthly_metrics','resource_monthly_metrics'
  );

-- runtime read-only negative test:
-- 일반 분석 계정에서 CREATE VIEW, INSERT, UPDATE, DELETE, DROP을 실행하면 access control에 의해 거부되어야 한다.
-- setup 관리자만 이 파일의 View DDL을 실행한다.

SELECT *
FROM (
    VALUES
      ('pms','PostgreSQL','hotel_pms','pms_ingest','pms_query','hotel_pms','pms'),
      ('pos','MySQL','hotel_pos','pos_ingest','pos_query','hotel_pos','pos'),
      ('crm','SQL Server','hotel_crm','crm_ingest','crm_query','hotel_crm','crm'),
      ('facility','ClickHouse','hotel_facility','facility_ingest','facility_query','hotel_facility','facility'),
      ('banquet','PostgreSQL','hotel_banquet','banquet_ingest','banquet_query','hotel_banquet','banquet')
) AS binding(source_id,engine,database_name,ingestion_role,query_role,datahub_platform_instance,trino_catalog);
