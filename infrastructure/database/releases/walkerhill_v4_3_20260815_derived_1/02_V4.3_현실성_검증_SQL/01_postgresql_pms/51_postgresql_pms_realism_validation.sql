-- Walkerhill V4.3 PMS realism pilot. PostgreSQL 16. Read-only.
-- Run only after the V4.1 PMS scripts have been loaded in an isolated environment.

SELECT room_rate_day_type,
       COUNT(*) AS calendar_days,
       CASE WHEN COUNT(*)>=14 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       COUNT(*) FILTER (WHERE is_holiday) AS holiday_days,
       MIN(synthetic_demand_index) AS min_demand_index,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY synthetic_demand_index) AS median_demand_index,
       MAX(synthetic_demand_index) AS max_demand_index,
       stddev_samp(synthetic_demand_index) AS stddev_demand_index
FROM walkerhill_v4_3.calendar_daily
GROUP BY room_rate_day_type
ORDER BY room_rate_day_type;

WITH sold AS (
  SELECT s.hotel_code,n.business_date,s.room_type_code,
         COUNT(*) AS rooms_sold,
         SUM(n.net_room_revenue) AS room_revenue
  FROM walkerhill_v4_3.pms_stay_nights n
  JOIN walkerhill_v4_3.pms_stays s ON s.stay_id=n.stay_id
  GROUP BY s.hotel_code,n.business_date,s.room_type_code
), daily AS (
  SELECT i.hotel_code,i.room_type_code,i.business_date,c.season_code,c.room_rate_day_type,
         i.available_room_nights,COALESCE(s.rooms_sold,0) AS rooms_sold,
         COALESCE(s.room_revenue,0) AS room_revenue
  FROM walkerhill_v4_3.pms_room_inventory_daily i
  JOIN walkerhill_v4_3.calendar_daily c USING(business_date)
  LEFT JOIN sold s USING(hotel_code,room_type_code,business_date)
)
SELECT hotel_code,room_type_code,season_code,room_rate_day_type,
       COUNT(*) AS sample_days,
       CASE WHEN COUNT(*)>=14 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       SUM(rooms_sold)::numeric/NULLIF(SUM(available_room_nights),0) AS occupancy_rate,
       SUM(room_revenue)/NULLIF(SUM(rooms_sold),0) AS adr_krw,
       MIN(rooms_sold::numeric/NULLIF(available_room_nights,0)) AS min_daily_occupancy,
       percentile_cont(0.10) WITHIN GROUP (ORDER BY rooms_sold::numeric/NULLIF(available_room_nights,0)) AS p10_daily_occupancy,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY rooms_sold::numeric/NULLIF(available_room_nights,0)) AS median_daily_occupancy,
       percentile_cont(0.90) WITHIN GROUP (ORDER BY rooms_sold::numeric/NULLIF(available_room_nights,0)) AS p90_daily_occupancy,
       MAX(rooms_sold::numeric/NULLIF(available_room_nights,0)) AS max_daily_occupancy,
       stddev_samp(rooms_sold::numeric/NULLIF(available_room_nights,0)) AS stddev_daily_occupancy
FROM daily
GROUP BY hotel_code,room_type_code,season_code,room_rate_day_type
ORDER BY hotel_code,room_type_code,season_code,room_rate_day_type;

SELECT hotel_code,booking_channel,market_segment,
       COUNT(*) AS reservations,
       CASE WHEN COUNT(*)>=30 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       MIN(checkin_date-booked_at::date) AS min_lead_days,
       percentile_cont(0.10) WITHIN GROUP (ORDER BY checkin_date-booked_at::date) AS p10_lead_days,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY checkin_date-booked_at::date) AS median_lead_days,
       percentile_cont(0.90) WITHIN GROUP (ORDER BY checkin_date-booked_at::date) AS p90_lead_days,
       MAX(checkin_date-booked_at::date) AS max_lead_days,
       AVG(checkout_date-checkin_date) AS average_los,
       stddev_samp(checkout_date-checkin_date) AS stddev_los,
       COUNT(*) FILTER (WHERE reservation_status='CANCELLED')::numeric/COUNT(*) AS cancellation_rate
FROM walkerhill_v4_3.pms_reservations
GROUP BY hotel_code,booking_channel,market_segment
ORDER BY hotel_code,booking_channel,market_segment;

WITH occupied AS (
  SELECT s.room_id,n.business_date,COUNT(*) AS occupied_stays
  FROM walkerhill_v4_3.pms_stay_nights n
  JOIN walkerhill_v4_3.pms_stays s ON s.stay_id=n.stay_id
  GROUP BY s.room_id,n.business_date
), checks AS (
  SELECT 'inventory_equation_mismatch' AS check_name,COUNT(*) AS violation_count
  FROM walkerhill_v4_3.pms_room_inventory_daily
  WHERE available_room_nights<>physical_rooms-out_of_order_rooms-house_use_rooms
  UNION ALL
  SELECT 'negative_or_overstated_inventory',COUNT(*)
  FROM walkerhill_v4_3.pms_room_inventory_daily
  WHERE available_room_nights<0 OR out_of_order_rooms<0 OR house_use_rooms<0
     OR out_of_order_rooms+house_use_rooms>physical_rooms
  UNION ALL
  SELECT 'duplicate_room_night',COUNT(*) FROM occupied WHERE occupied_stays>1
  UNION ALL
  SELECT 'reservation_time_order_violation',COUNT(*)
  FROM walkerhill_v4_3.pms_reservations
  WHERE checkout_date<=checkin_date OR booked_at::date>checkin_date
     OR (cancelled_at IS NOT NULL AND cancelled_at<booked_at)
  UNION ALL
  SELECT 'stay_time_order_violation',COUNT(*)
  FROM walkerhill_v4_3.pms_stays
  WHERE actual_checkout_at<=actual_checkin_at OR occupied_room_nights<=0
)
SELECT check_name,violation_count,
       CASE WHEN violation_count=0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM checks ORDER BY check_name;

SELECT e.event_id,x.hotel_code,x.domain,x.metric_name,x.lead_days,x.lag_days,
       x.uplift_min,x.uplift_mode,x.uplift_max,x.capacity_limit,x.confidence,
       e.fact_or_assumption,
       CASE WHEN x.uplift_min<=x.uplift_mode AND x.uplift_mode<=x.uplift_max
                  AND x.capacity_limit>0 AND x.capacity_limit<=1
            THEN 'PASS' ELSE 'FAIL' END AS parameter_order_status
FROM walkerhill_v4_3.event_master e
JOIN walkerhill_v4_3.hotel_event_effect x USING(event_id)
ORDER BY e.event_id,x.hotel_code,x.domain,x.metric_name;
