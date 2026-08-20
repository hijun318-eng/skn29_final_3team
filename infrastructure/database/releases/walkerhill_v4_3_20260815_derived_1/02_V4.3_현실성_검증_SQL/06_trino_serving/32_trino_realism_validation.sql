-- Walkerhill V4.3 cross-domain realism pilot. Trino 476+. Read-only.

SELECT d.hotel_code,c.season_code,c.room_rate_day_type,c.is_holiday,
       COUNT(*) AS sample_days,
       CASE WHEN COUNT(*)>=14 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       MIN(d.occupancy_rate) AS min_occupancy,approx_percentile(d.occupancy_rate,0.10) AS p10_occupancy,
       approx_percentile(d.occupancy_rate,0.50) AS median_occupancy,approx_percentile(d.occupancy_rate,0.90) AS p90_occupancy,
       MAX(d.occupancy_rate) AS max_occupancy,stddev_samp(d.occupancy_rate) AS stddev_occupancy,
       AVG(d.adr_krw) AS average_adr_krw,AVG(d.fnb_revenue_krw) AS average_fnb_revenue_krw,
       AVG(d.banquet_revenue_krw) AS average_banquet_revenue_krw,AVG(CAST(d.facility_uses AS double)) AS average_facility_uses
FROM serving.analytics_v4_3.hotel_operations_daily d
JOIN pms.walkerhill_v4_3.calendar_daily c ON c.business_date=d.business_date
GROUP BY d.hotel_code,c.season_code,c.room_rate_day_type,c.is_holiday
ORDER BY d.hotel_code,c.season_code,c.room_rate_day_type,c.is_holiday;

WITH event_windows AS (
  SELECT e.event_id,e.event_name,e.start_date,e.end_date,x.hotel_code,x.domain,x.metric_name,
         x.lead_days,x.lag_days,x.uplift_min,x.uplift_mode,x.uplift_max
  FROM pms.walkerhill_v4_3.event_master e
  JOIN pms.walkerhill_v4_3.hotel_event_effect x ON x.event_id=e.event_id
), observations AS (
  SELECT e.*,
         CASE WHEN d.business_date<e.start_date THEN 'LEAD'
              WHEN d.business_date<=e.end_date THEN 'EVENT' ELSE 'LAG' END AS relative_phase,
         CASE e.metric_name
           WHEN 'OCCUPANCY_RATE' THEN d.occupancy_rate
           WHEN 'ADR' THEN d.adr_krw
           WHEN 'ORDER_COUNT' THEN CAST(d.fnb_orders AS double)
           WHEN 'BOOKING_COUNT' THEN CAST(d.banquet_events AS double)
           WHEN 'USAGE_COUNT' THEN CAST(d.facility_uses AS double)
         END AS metric_value
  FROM event_windows e
  JOIN serving.analytics_v4_3.hotel_operations_daily d ON d.hotel_code=e.hotel_code
   AND d.business_date BETWEEN date_add('day',-e.lead_days,e.start_date) AND date_add('day',e.lag_days,e.end_date)
)
SELECT event_id,event_name,hotel_code,domain,metric_name,relative_phase,
       COUNT(*) AS sample_days,MIN(metric_value) AS min_value,
       CASE WHEN COUNT(*)>=14 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       approx_percentile(metric_value,0.10) AS p10_value,AVG(metric_value) AS average_value,
       approx_percentile(metric_value,0.50) AS median_value,approx_percentile(metric_value,0.90) AS p90_value,
       MAX(metric_value) AS max_value,stddev_samp(metric_value) AS stddev_value,
       MIN(uplift_min) AS contracted_uplift_min,MIN(uplift_mode) AS contracted_uplift_mode,
       MIN(uplift_max) AS contracted_uplift_max
FROM observations
GROUP BY event_id,event_name,hotel_code,domain,metric_name,relative_phase
ORDER BY event_id,hotel_code,domain,metric_name,relative_phase;

WITH event_windows AS (
  SELECT e.event_id,e.start_date,e.end_date,x.hotel_code,
         MAX(x.lead_days) AS lead_days,MAX(x.lag_days) AS lag_days,MAX(x.confidence) AS confidence
  FROM pms.walkerhill_v4_3.event_master e
  JOIN pms.walkerhill_v4_3.hotel_event_effect x ON x.event_id=e.event_id
  GROUP BY e.event_id,e.start_date,e.end_date,x.hotel_code
), tender_base AS (
  SELECT p.payment_line_id,o.business_date,x.hotel_code,x.outlet_category,
         CASE WHEN o.linked_stay_id IS NULL THEN 'NON_STAY' ELSE 'IN_STAY' END AS stay_link_type,
         CASE WHEN m.member_no IS NULL THEN 'NON_MEMBER' ELSE 'MEMBER' END AS member_type,
         CASE WHEN o.net_amount<50000 THEN 'LT_50K'
              WHEN o.net_amount<150000 THEN '50K_150K'
              WHEN o.net_amount<300000 THEN '150K_300K' ELSE 'GE_300K' END AS amount_band,
         p.tender_type,p.transaction_type,p.signed_amount
  FROM pos.walkerhill_v4_3.pos_payment_lines p
  JOIN pos.walkerhill_v4_3.pos_orders o ON o.order_id=p.order_id
  JOIN pos.walkerhill_v4_3.pos_outlets x ON x.outlet_id=o.outlet_id
  LEFT JOIN crm.walkerhill_v4_3.crm_customer_map m ON m.pos_customer_ref=o.pos_customer_ref
), tender_candidates AS (
  SELECT t.*,
         COALESCE(e.event_id,'NO_EVENT') AS event_id,
         CASE WHEN e.event_id IS NULL THEN 'NON_EVENT'
              WHEN t.business_date<e.start_date THEN 'LEAD'
              WHEN t.business_date<=e.end_date THEN 'EVENT' ELSE 'LAG' END AS relative_phase,
         ROW_NUMBER() OVER(
           PARTITION BY t.payment_line_id
           ORDER BY CASE WHEN e.event_id IS NULL THEN 3
                         WHEN t.business_date BETWEEN e.start_date AND e.end_date THEN 0
                         WHEN t.business_date<e.start_date THEN 1 ELSE 2 END,
                    e.confidence DESC NULLS LAST,e.event_id
         ) AS event_rank
  FROM tender_base t
  LEFT JOIN event_windows e ON e.hotel_code=t.hotel_code
   AND t.business_date BETWEEN date_add('day',-e.lead_days,e.start_date) AND date_add('day',e.lag_days,e.end_date)
), tender AS (
  SELECT * FROM tender_candidates WHERE event_rank=1
)
SELECT hotel_code,outlet_category,stay_link_type,member_type,amount_band,event_id,relative_phase,transaction_type,tender_type,
       COUNT(*) AS payment_lines,SUM(ABS(signed_amount)) AS absolute_amount_krw,
       CASE WHEN COUNT(*)>=30 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       COUNT(*)*1.0/SUM(COUNT(*)) OVER(
         PARTITION BY hotel_code,outlet_category,stay_link_type,member_type,amount_band,event_id,relative_phase,transaction_type
       ) AS line_share,
       SUM(ABS(signed_amount))*1.0/NULLIF(SUM(SUM(ABS(signed_amount))) OVER(
         PARTITION BY hotel_code,outlet_category,stay_link_type,member_type,amount_band,event_id,relative_phase,transaction_type
       ),0) AS amount_share
FROM tender
GROUP BY hotel_code,outlet_category,stay_link_type,member_type,amount_band,event_id,relative_phase,transaction_type,tender_type
ORDER BY hotel_code,outlet_category,stay_link_type,member_type,amount_band,event_id,relative_phase,transaction_type,tender_type;

WITH daily AS (
  SELECT hotel_code,business_date,occupied_room_nights AS rooms_sold,fnb_orders,facility_uses,staffing_hours,
         CASE WHEN event_id IS NOT NULL THEN 'EVENT' ELSE 'NON_EVENT' END AS event_flag
  FROM serving.analytics_v4_3.hotel_operations_daily
)
SELECT hotel_code,event_flag,COUNT(*) AS sample_days,
       CASE WHEN COUNT(*)>=14 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       corr(CAST(rooms_sold AS double),CAST(fnb_orders AS double)) AS rooms_fnb_correlation,
       corr(CAST(rooms_sold AS double),CAST(facility_uses AS double)) AS rooms_facility_correlation,
       corr(CAST(rooms_sold AS double),CAST(staffing_hours AS double)) AS rooms_staffing_correlation
FROM daily
GROUP BY hotel_code,event_flag
ORDER BY hotel_code,event_flag;

WITH resource_load AS (
  SELECT o.hotel_code,o.business_date,o.facility_uses,o.staffing_hours,
         f.energy_kwh,f.water_m3,f.waste_kg,
         CASE WHEN o.event_id IS NULL THEN 'NON_EVENT' ELSE 'EVENT' END AS event_flag
  FROM serving.analytics_v4_3.hotel_operations_daily o
  JOIN serving.analytics_v4_3.facility_daily f
    ON f.business_date=o.business_date AND f.hotel_code=o.hotel_code
)
SELECT hotel_code,event_flag,COUNT(*) AS sample_days,
       CASE WHEN COUNT(*)>=14 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       corr(CAST(facility_uses AS double),CAST(staffing_hours AS double)) AS usage_staffing_correlation,
       corr(CAST(facility_uses AS double),CAST(energy_kwh AS double)) AS usage_energy_correlation,
       corr(CAST(facility_uses AS double),CAST(water_m3 AS double)) AS usage_water_correlation,
       corr(CAST(facility_uses AS double),CAST(waste_kg AS double)) AS usage_waste_correlation
FROM resource_load
GROUP BY hotel_code,event_flag
ORDER BY hotel_code,event_flag;

WITH checks AS (
  SELECT 'journey_room_charge_missing' AS check_name,COUNT(*) AS violation_count
  FROM pos.walkerhill_v4_3.pos_orders o
  WHERE o.linked_stay_id LIKE 'S_JOURNEY_%'
    AND NOT EXISTS (
      SELECT 1 FROM pos.walkerhill_v4_3.pos_payment_lines p
      WHERE p.order_id=o.order_id AND p.transaction_type='SALE' AND p.tender_type='ROOM_CHARGE'
    )
  UNION ALL
  SELECT 'bridge_room_charge_present',COUNT(*)
  FROM pos.walkerhill_v4_3.pos_orders o
  JOIN pos.walkerhill_v4_3.pos_payment_lines p ON p.order_id=o.order_id
  WHERE o.linked_stay_id LIKE 'S_BRIDGE_%'
    AND p.transaction_type='SALE' AND p.tender_type='ROOM_CHARGE'
  UNION ALL
  SELECT 'room_charge_folio_mismatch',COUNT(*)
  FROM pos.walkerhill_v4_3.pos_payment_lines p
  JOIN pos.walkerhill_v4_3.pos_orders o ON o.order_id=p.order_id
  LEFT JOIN pms.walkerhill_v4_3.pms_stays s ON s.stay_id=o.linked_stay_id
  LEFT JOIN pms.walkerhill_v4_3.pms_folio_postings f
    ON f.source_system='POS' AND f.source_transaction_id=o.order_id
  WHERE p.transaction_type='SALE' AND p.tender_type='ROOM_CHARGE'
    AND (o.linked_stay_id IS NULL OR s.stay_id IS NULL OR f.folio_posting_id IS NULL
      OR f.stay_id<>o.linked_stay_id OR f.posting_type<>'POS_ROOM_CHARGE'
      OR f.net_amount<>p.signed_amount OR f.currency_code<>o.currency_code OR f.posting_status<>'POSTED'
      OR CAST(f.posted_at AT TIME ZONE 'Asia/Seoul' AS date)<>o.business_date
      OR CAST(f.posted_at AT TIME ZONE 'Asia/Seoul' AS date) NOT BETWEEN
           CAST(s.actual_checkin_at AT TIME ZONE 'Asia/Seoul' AS date)
           AND CAST(s.actual_checkout_at AT TIME ZONE 'Asia/Seoul' AS date)-INTERVAL '1' DAY)
  UNION ALL
  SELECT 'event_same_uplift_all_hotels',COUNT(*)
  FROM (
    SELECT event_id,domain,metric_name,uplift_mode
    FROM pms.walkerhill_v4_3.hotel_event_effect
    GROUP BY event_id,domain,metric_name,uplift_mode
    HAVING COUNT(DISTINCT hotel_code)=(
      SELECT COUNT(DISTINCT hotel_code) FROM pms.walkerhill_v4_3.hotel_event_effect
    )
  ) q
  UNION ALL
  SELECT 'event_without_cross_domain_trace',COUNT(*)
  FROM (
    SELECT e.event_id,x.hotel_code,
           SUM(CASE WHEN d.fnb_orders>0 THEN 1 ELSE 0 END) AS fnb_days,
           SUM(CASE WHEN d.facility_uses>0 THEN 1 ELSE 0 END) AS facility_days,
           SUM(CASE WHEN d.review_count>0 THEN 1 ELSE 0 END) AS voc_days
    FROM pms.walkerhill_v4_3.event_master e
    JOIN pms.walkerhill_v4_3.hotel_event_effect x ON x.event_id=e.event_id
    JOIN serving.analytics_v4_3.hotel_voc_signal_daily d ON d.hotel_code=x.hotel_code
     AND d.business_date BETWEEN e.start_date AND e.end_date
    GROUP BY e.event_id,x.hotel_code
    HAVING SUM(CASE WHEN d.fnb_orders>0 THEN 1 ELSE 0 END)=0
        OR SUM(CASE WHEN d.facility_uses>0 THEN 1 ELSE 0 END)=0
        OR SUM(CASE WHEN d.review_count>0 THEN 1 ELSE 0 END)=0
  ) q
)
SELECT check_name,violation_count,
       CASE WHEN violation_count=0 THEN 'PASS' ELSE 'REVIEW' END AS status
FROM checks ORDER BY check_name;

WITH event_windows AS (
  SELECT e.event_id,e.event_name,e.start_date,e.end_date,x.hotel_code,
         MAX(x.lead_days) AS lead_days,MAX(x.lag_days) AS lag_days
  FROM pms.walkerhill_v4_3.event_master e
  JOIN pms.walkerhill_v4_3.hotel_event_effect x ON x.event_id=e.event_id
  GROUP BY e.event_id,e.event_name,e.start_date,e.end_date,x.hotel_code
), event_voc AS (
  SELECT e.event_id,e.event_name,e.hotel_code,
         COALESCE(SUM(v.review_count),0) AS review_count,
         SUM(v.average_rating*v.review_count)/NULLIF(SUM(v.review_count),0) AS average_rating,
         SUM(v.negative_reviews)*1.0/NULLIF(SUM(v.review_count),0) AS negative_rate
  FROM event_windows e
  LEFT JOIN serving.analytics_v4_3.voc_daily v ON v.hotel_code=e.hotel_code
   AND v.business_date BETWEEN date_add('day',-e.lead_days,e.start_date) AND date_add('day',e.lag_days,e.end_date)
  GROUP BY e.event_id,e.event_name,e.hotel_code
)
SELECT event_id,event_name,hotel_code,review_count,average_rating,negative_rate
      ,CASE WHEN review_count>=30 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status
FROM event_voc ORDER BY event_id,hotel_code;
