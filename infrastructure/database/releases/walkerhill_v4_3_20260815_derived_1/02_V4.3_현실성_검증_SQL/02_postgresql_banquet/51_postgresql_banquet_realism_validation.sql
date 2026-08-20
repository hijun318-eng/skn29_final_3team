-- Walkerhill V4.3 banquet realism pilot. PostgreSQL 16. Read-only.

SELECT v.hotel_code,v.venue_category,b.event_type,b.booking_status,
       COUNT(*) AS bookings,
       CASE WHEN COUNT(*)>=30 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       MIN(b.event_date-b.inquiry_at::date) AS min_lead_days,
       percentile_cont(0.10) WITHIN GROUP (ORDER BY b.event_date-b.inquiry_at::date) AS p10_lead_days,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY b.event_date-b.inquiry_at::date) AS median_lead_days,
       percentile_cont(0.90) WITHIN GROUP (ORDER BY b.event_date-b.inquiry_at::date) AS p90_lead_days,
       MAX(b.event_date-b.inquiry_at::date) AS max_lead_days,
       AVG(b.actual_attendees) FILTER (WHERE b.actual_attendees IS NOT NULL) AS average_attendees,
       stddev_samp(b.actual_attendees) FILTER (WHERE b.actual_attendees IS NOT NULL) AS stddev_attendees,
       AVG(b.contracted_amount) AS average_contracted_krw
FROM walkerhill_v4_3.banquet_bookings b
JOIN walkerhill_v4_3.banquet_venues v USING(venue_id)
GROUP BY v.hotel_code,v.venue_category,b.event_type,b.booking_status
ORDER BY v.hotel_code,v.venue_category,b.event_type,b.booking_status;

WITH booking_monthly AS (
  SELECT date_trunc('month',b.event_date)::date AS month_start,v.hotel_code,
         COUNT(*) AS booking_count,
         SUM(COALESCE(b.actual_attendees,0)) AS attendees
  FROM walkerhill_v4_3.banquet_bookings b
  JOIN walkerhill_v4_3.banquet_venues v USING(venue_id)
  GROUP BY date_trunc('month',b.event_date)::date,v.hotel_code
), revenue_monthly AS (
  SELECT date_trunc('month',b.event_date)::date AS month_start,v.hotel_code,
         SUM(r.recognized_amount) AS recognized_revenue_krw,
         MIN(r.recognized_amount) AS min_revenue_line,
         percentile_cont(0.50) WITHIN GROUP (ORDER BY r.recognized_amount) AS median_revenue_line,
         percentile_cont(0.90) WITHIN GROUP (ORDER BY r.recognized_amount) AS p90_revenue_line,
         MAX(r.recognized_amount) AS max_revenue_line,
         stddev_samp(r.recognized_amount) AS stddev_revenue_line
  FROM walkerhill_v4_3.banquet_revenue_lines r
  JOIN walkerhill_v4_3.banquet_bookings b USING(banquet_event_id)
  JOIN walkerhill_v4_3.banquet_venues v USING(venue_id)
  GROUP BY date_trunc('month',b.event_date)::date,v.hotel_code
)
SELECT b.month_start,b.hotel_code,b.booking_count,
       CASE WHEN b.booking_count>=14 THEN 'USABLE' ELSE 'INSUFFICIENT' END AS sample_status,
       b.attendees,COALESCE(r.recognized_revenue_krw,0) AS recognized_revenue_krw,
       COALESCE(r.recognized_revenue_krw,0)/NULLIF(b.attendees,0) AS revenue_per_attendee_krw,
       r.min_revenue_line,r.median_revenue_line,r.p90_revenue_line,
       r.max_revenue_line,r.stddev_revenue_line
FROM booking_monthly b
LEFT JOIN revenue_monthly r USING(month_start,hotel_code)
ORDER BY b.month_start,b.hotel_code;

WITH slot_overlap AS (
  SELECT venue_id,event_date,event_slot,COUNT(*) AS concurrent_bookings
  FROM walkerhill_v4_3.banquet_bookings
  WHERE booking_status IN('CONFIRMED','COMPLETED')
  GROUP BY venue_id,event_date,event_slot
), pickup AS (
  SELECT banquet_event_id,SUM(pickup_room_nights) AS pickup_room_nights,
         SUM(reserved_room_nights) AS reserved_room_nights
  FROM walkerhill_v4_3.banquet_room_blocks GROUP BY banquet_event_id
), checks AS (
  SELECT 'venue_slot_overlap' AS check_name,COUNT(*) AS violation_count
  FROM slot_overlap WHERE concurrent_bookings>1
  UNION ALL
  SELECT 'attendees_over_capacity',COUNT(*)
  FROM walkerhill_v4_3.banquet_bookings b
  JOIN walkerhill_v4_3.banquet_venues v USING(venue_id)
  WHERE COALESCE(b.actual_attendees,b.expected_guests)>v.synthetic_capacity
  UNION ALL
  SELECT 'booking_time_order_violation',COUNT(*)
  FROM walkerhill_v4_3.banquet_bookings
  WHERE starts_at>=ends_at OR inquiry_at>starts_at
     OR (quoted_at IS NOT NULL AND quoted_at<inquiry_at)
     OR (confirmed_at IS NOT NULL AND (quoted_at IS NULL OR confirmed_at<quoted_at))
     OR (cancelled_at IS NOT NULL AND cancelled_at<inquiry_at)
  UNION ALL
  SELECT 'pickup_over_reserved',COUNT(*) FROM pickup WHERE pickup_room_nights>reserved_room_nights
  UNION ALL
  SELECT 'amount_equation_mismatch',COUNT(*)
  FROM walkerhill_v4_3.banquet_bookings
  WHERE (booking_status='COMPLETED' AND (deposit_amount+balance_amount<>contracted_amount OR cancellation_fee_amount<>0))
     OR (booking_status='CANCELLED' AND (balance_amount<>0 OR cancellation_fee_amount>deposit_amount))
  UNION ALL
  SELECT 'revenue_recognition_date_status_mismatch',COUNT(*)
  FROM walkerhill_v4_3.banquet_revenue_lines r
  JOIN walkerhill_v4_3.banquet_bookings b USING(banquet_event_id)
  WHERE b.booking_status<>'COMPLETED' OR r.recognized_date<>b.event_date OR r.revenue_status<>'RECOGNIZED'
)
SELECT check_name,violation_count,
       CASE WHEN violation_count=0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM checks ORDER BY check_name;
