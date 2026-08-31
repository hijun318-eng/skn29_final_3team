-- release_id=walkerhill-member-revenue-physical-v1.20260830.1
-- source_release_id=walkerhill-analysis-semantics-v1.20260827.1
-- target_dbms=Trino 483; target_schema=serving.analytics_v4_3
-- state=REVIEW_REQUIRED; script_type=VALIDATION_READONLY; execution_order=30; execution_default=NOT_RUN
-- gate_rule=모든 violation_count가 0이고 EXPLAIN이 물리화 저장소만 읽을 때만 활성 catalog 후보를 작성한다.

SELECT 'member_room_revenue_daily_grain' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT business_date, hotel_code, tier_code
    FROM serving.analytics_v4_3.member_room_revenue_daily
    GROUP BY 1, 2, 3
    HAVING COUNT(*) <> 1
);

SELECT 'member_fnb_revenue_daily_grain' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT business_date, hotel_code, tier_code
    FROM serving.analytics_v4_3.member_fnb_revenue_daily
    GROUP BY 1, 2, 3
    HAVING COUNT(*) <> 1
);

SELECT 'member_room_revenue_daily_not_empty' AS check_name,
       CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END AS violation_count
FROM serving.analytics_v4_3.member_room_revenue_daily;

SELECT 'member_fnb_revenue_daily_not_empty' AS check_name,
       CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END AS violation_count
FROM serving.analytics_v4_3.member_fnb_revenue_daily;

SELECT 'member_revenue_daily_required_keys' AS check_name,
       COUNT_IF(business_date IS NULL OR hotel_code IS NULL OR tier_code IS NULL) AS violation_count
FROM serving.analytics_v4_3.member_revenue_daily;

SELECT 'member_room_revenue_reconciliation' AS check_name,
       CASE
           WHEN (
               SELECT SUM(room_revenue_krw)
               FROM serving.analytics_v4_3.member_revenue_daily
           ) IS DISTINCT FROM (
               SELECT SUM(room_revenue_krw)
               FROM serving.analytics_v4_3.member_room_revenue_daily
           ) THEN 1
           ELSE 0
       END AS violation_count;

SELECT 'member_fnb_revenue_reconciliation' AS check_name,
       CASE
           WHEN (
               SELECT SUM(fnb_revenue_krw)
               FROM serving.analytics_v4_3.member_revenue_daily
           ) IS DISTINCT FROM (
               SELECT SUM(fnb_revenue_krw)
               FROM serving.analytics_v4_3.member_fnb_revenue_daily
           ) THEN 1
           ELSE 0
       END AS violation_count;

EXPLAIN
SELECT SUM(room_revenue_krw)
FROM serving.analytics_v4_3.member_revenue_daily
WHERE business_date >= DATE '2026-01-01'
  AND business_date < DATE '2026-02-01';

EXPLAIN
SELECT SUM(room_revenue_krw), SUM(fnb_revenue_krw)
FROM serving.analytics_v4_3.member_revenue_daily
WHERE business_date >= DATE '2026-01-01'
  AND business_date < DATE '2026-02-01';
