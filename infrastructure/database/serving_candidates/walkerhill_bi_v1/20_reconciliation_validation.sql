-- release_id=walkerhill-bi-serving-v1.20260820.1
-- target_dbms=Trino 483; target_schema=serving.analytics_v4_3
-- script_type=VALIDATION_READONLY; execution_order=20; execution_default=NOT_RUN
-- gate_rule=모든 violation_count가 0이어야 semantic review로 진행할 수 있다.

SELECT 'room_stay_night_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT stay_id, business_date
    FROM serving.analytics_v4_3.room_stay_night_fact
    GROUP BY 1, 2 HAVING COUNT(*) <> 1
);

SELECT 'room_kpi_daily_by_type_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT business_date, hotel_code, room_type_code
    FROM serving.analytics_v4_3.room_kpi_daily_by_type
    GROUP BY 1, 2, 3 HAVING COUNT(*) <> 1
);

SELECT 'room_revenue_reconciliation' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT business_date, hotel_code, SUM(room_revenue_krw) AS value
    FROM serving.analytics_v4_3.room_stay_night_fact GROUP BY 1, 2
) candidate
FULL OUTER JOIN (
    SELECT business_date, hotel_code, room_revenue_krw AS value
    FROM serving.analytics_v4_3.room_daily
) baseline USING (business_date, hotel_code)
WHERE candidate.value IS DISTINCT FROM baseline.value;

SELECT 'fnb_order_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT order_id FROM serving.analytics_v4_3.fnb_order_fact
    GROUP BY 1 HAVING COUNT(*) <> 1
);

SELECT 'fnb_revenue_reconciliation' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT business_date, hotel_code, SUM(fnb_revenue_krw) AS value
    FROM serving.analytics_v4_3.fnb_order_fact GROUP BY 1, 2
) candidate
FULL OUTER JOIN (
    SELECT business_date, hotel_code, net_revenue_krw AS value
    FROM serving.analytics_v4_3.fnb_daily
) baseline USING (business_date, hotel_code)
WHERE candidate.value IS DISTINCT FROM baseline.value;

SELECT 'banquet_event_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT banquet_event_id FROM serving.analytics_v4_3.banquet_event_fact
    GROUP BY 1 HAVING COUNT(*) <> 1
);

SELECT 'banquet_revenue_line_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT revenue_line_id FROM serving.analytics_v4_3.banquet_revenue_fact
    GROUP BY 1 HAVING COUNT(*) <> 1
);

SELECT 'banquet_revenue_reconciliation' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT business_date, hotel_code, SUM(banquet_revenue_krw) AS value
    FROM serving.analytics_v4_3.banquet_revenue_fact GROUP BY 1, 2
) candidate
FULL OUTER JOIN (
    SELECT business_date, hotel_code, recognized_revenue_krw AS value
    FROM serving.analytics_v4_3.banquet_daily
) baseline USING (business_date, hotel_code)
WHERE candidate.value IS DISTINCT FROM baseline.value;

SELECT 'facility_usage_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT usage_event_id FROM serving.analytics_v4_3.facility_usage_fact
    GROUP BY 1 HAVING COUNT(*) <> 1
);

SELECT 'facility_incident_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT incident_id FROM serving.analytics_v4_3.facility_incident_fact
    GROUP BY 1 HAVING COUNT(*) <> 1
);

SELECT 'facility_resource_daily_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT business_date, facility_id
    FROM serving.analytics_v4_3.facility_resource_daily_fact
    GROUP BY 1, 2 HAVING COUNT(*) <> 1
);

SELECT 'staffing_daily_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT business_date, hotel_code, department, shift_code
    FROM serving.analytics_v4_3.staffing_daily_fact
    GROUP BY 1, 2, 3, 4 HAVING COUNT(*) <> 1
);

SELECT 'membership_snapshot_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT snapshot_date, member_no
    FROM serving.analytics_v4_3.membership_current_snapshot
    GROUP BY 1, 2 HAVING COUNT(*) <> 1
);

SELECT 'membership_point_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT point_txn_id FROM serving.analytics_v4_3.membership_point_fact
    GROUP BY 1 HAVING COUNT(*) <> 1
);

SELECT 'voc_review_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT voc_review_id FROM serving.analytics_v4_3.voc_review_fact
    GROUP BY 1 HAVING COUNT(*) <> 1
);

SELECT 'voc_review_reconciliation' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT business_date, hotel_code, COUNT(*) AS value
    FROM serving.analytics_v4_3.voc_review_fact GROUP BY 1, 2
) candidate
FULL OUTER JOIN (
    SELECT business_date, hotel_code, SUM(review_count) AS value
    FROM serving.analytics_v4_3.voc_daily GROUP BY 1, 2
) baseline USING (business_date, hotel_code)
WHERE candidate.value IS DISTINCT FROM baseline.value;

SELECT 'operating_revenue_key' AS check_name, COUNT(*) AS violation_count
FROM (
    SELECT business_date, hotel_code
    FROM serving.analytics_v4_3.operating_revenue_daily_fact
    GROUP BY 1, 2 HAVING COUNT(*) <> 1
);

SELECT 'operating_revenue_reconciliation' AS check_name, COUNT(*) AS violation_count
FROM serving.analytics_v4_3.operating_revenue_daily_fact candidate
FULL OUTER JOIN serving.analytics_v4_3.hotel_operations_daily baseline
  USING (business_date, hotel_code)
WHERE candidate.total_operating_revenue_krw
      IS DISTINCT FROM baseline.total_operating_revenue_krw;
