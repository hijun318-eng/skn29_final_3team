-- Banquet deterministic synthetic load v2.2
-- seed=20260729; schema_version=1.0.0; scenario_version=1.0.0
-- fixture_version=1.0.0; synthetic=true; property_id=SYNTHETIC_HOTEL_001
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL DateStyle = 'ISO, YMD';
SET LOCAL statement_timeout = '30min';
SET LOCAL lock_timeout = '15s';
SET LOCAL idle_in_transaction_session_timeout = '5min';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001' AND NOT is_synthetic)
       OR EXISTS (SELECT 1 FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001' AND NOT is_synthetic) THEN
        RAISE EXCEPTION 'SCHEMA_CONTRACT_MISMATCH: non-synthetic banquet rows exist';
    END IF;
END $$;

DELETE FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001';
DELETE FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001';

WITH base AS (
    SELECT n,
           DATE '2022-01-01' + ((n*37)%1826) AS event_date,
           'BQE-' || substr(md5('SYNTHETIC_HOTEL_001|' || n),1,32) AS banquet_event_id
    FROM generate_series(1,6000) AS g(n)
),
timed AS (
    SELECT *,
           least(
               (event_date::timestamp - INTERVAL '90 days') AT TIME ZONE 'UTC',
               TIMESTAMPTZ '2026-06-01 00:00:00+00'
           ) AS inquiry_at
    FROM base
)
INSERT INTO banquet_bookings (
    property_id,banquet_event_id,customer_id,inquiry_at,quoted_at,confirmed_at,
    cancelled_at,event_date,product_code,product_category,expected_guests,
    actual_attendees,lead_source,sales_owner_team,booking_status,contracted_amount,
    cancellation_fee,reserved_room_block_count,expected_room_nights,
    group_checkin_date,group_checkout_date,released_room_count,pickup_room_count,
    data_period_status,is_forecast,is_synthetic,source_updated_at
)
SELECT 'SYNTHETIC_HOTEL_001',banquet_event_id,
       'BQC-' || lpad((1+(n%80000))::text,8,'0'),
       inquiry_at,inquiry_at+INTERVAL '2 days',inquiry_at+INTERVAL '7 days',
       CASE WHEN event_date<=DATE '2026-07-28' AND n%10=0
            THEN least(inquiry_at+INTERVAL '30 days',(event_date::timestamp-INTERVAL '5 days') AT TIME ZONE 'UTC') END,
       event_date,
       'BQ-PROD-' || lpad((1+n%12)::text,2,'0'),
       (ARRAY['WEDDING','CONFERENCE','MEETING','CORPORATE_EVENT','SOCIAL_EVENT'])[1+(n%5)],
       40+(n%260),
       CASE WHEN event_date<=DATE '2026-07-28' AND n%10<>0 THEN 35+(n%250) END,
       (ARRAY['DIRECT','AGENCY','CORPORATE','ONLINE'])[1+(n%4)],
       (ARRAY['BANQUET_A','BANQUET_B','SALES_GROUP'])[1+(n%3)],
       CASE WHEN event_date>DATE '2026-07-28' THEN 'CONFIRMED'
            WHEN n%10=0 THEN 'CANCELLED' ELSE 'COMPLETED' END,
       (40+(n%260))*150000,
       CASE WHEN event_date<=DATE '2026-07-28' AND n%10=0 THEN (40+(n%260))*15000 ELSE 0 END,
       CASE WHEN n%4=0 THEN 10+(n%30) ELSE 0 END,
       CASE WHEN n%4=0 THEN (10+(n%30))*(1+n%3) ELSE 0 END,
       CASE WHEN n%4=0 THEN event_date-1 END,
       CASE WHEN n%4=0 THEN event_date+1+(n%2) END,
       CASE WHEN n%4=0 THEN n%5 ELSE 0 END,
       CASE WHEN n%4=0 THEN greatest(0,(10+(n%30))-(n%5)-(n%4)) ELSE 0 END,
       CASE WHEN event_date<DATE '2025-01-01' THEN 'REFERENCE_CALIBRATED'
            WHEN event_date<DATE '2026-01-01' THEN 'SYNTHETIC_ACTUAL_LIKE'
            WHEN event_date<=DATE '2026-07-28' THEN 'YTD_SYNTHETIC'
            ELSE 'FORECAST_SCENARIO' END,
       event_date>DATE '2026-07-28',true,
       CASE WHEN event_date>DATE '2026-07-28' THEN TIMESTAMPTZ '2026-07-28 05:00:00+00'
            ELSE least((event_date::timestamp+INTERVAL '18 hours') AT TIME ZONE 'UTC',
                       TIMESTAMPTZ '2026-07-28 05:00:00+00') END
FROM timed;

WITH lines(line_no,category,ratio) AS (
    VALUES (1,'VENUE',0.40::numeric),(2,'FOOD_BEVERAGE',0.60::numeric)
)
INSERT INTO banquet_revenue (
    property_id,revenue_id,banquet_event_id,recognized_date,product_code,
    product_category,revenue_amount,reversal_amount,cost_amount,revenue_status,
    data_period_status,is_forecast,is_synthetic,source_updated_at
)
SELECT b.property_id,
       'BQR-' || substr(md5(b.property_id || '|' || b.banquet_event_id || '|' || l.line_no),1,32),
       b.banquet_event_id,b.event_date,
       b.product_code || '-' || l.line_no,l.category,
       round(b.contracted_amount*l.ratio,2),0,
       round(b.contracted_amount*l.ratio*0.35,2),
       CASE WHEN b.booking_status='COMPLETED' THEN 'RECOGNIZED' ELSE 'EXPECTED' END,
       b.data_period_status,b.is_forecast,true,b.source_updated_at
FROM banquet_bookings b
CROSS JOIN lines l
WHERE b.property_id='SYNTHETIC_HOTEL_001'
  AND b.booking_status IN ('COMPLETED','CONFIRMED');

COMMIT;

SELECT 'banquet_bookings' AS table_name,count(*) AS row_count,max(source_updated_at) AS watermark,
       md5(sum(hashtext(banquet_event_id))::text) AS checksum
FROM banquet_bookings WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'banquet_revenue',count(*),max(source_updated_at),
       md5(sum(hashtext(revenue_id))::text)
FROM banquet_revenue WHERE property_id='SYNTHETIC_HOTEL_001';

SELECT data_period_status,is_forecast,booking_status,count(*) AS booking_count
FROM banquet_bookings
WHERE property_id='SYNTHETIC_HOTEL_001'
GROUP BY data_period_status,is_forecast,booking_status
ORDER BY data_period_status,is_forecast,booking_status;
