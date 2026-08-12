-- PMS deterministic synthetic load v2.2 for contract 1.0.0
-- seed=20260729; schema_version=1.0.0; scenario_version=1.0.0
-- dataset_version=1.0.0; synthetic=true; property_id=SYNTHETIC_HOTEL_001
-- generated_at=2026-07-28T05:00:00Z; timezone=UTC
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL DateStyle = 'ISO, YMD';
SET LOCAL statement_timeout = '30min';
SET LOCAL lock_timeout = '15s';
SET LOCAL idle_in_transaction_session_timeout = '5min';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pms_guests WHERE property_id='SYNTHETIC_HOTEL_001' AND NOT is_synthetic)
       OR EXISTS (SELECT 1 FROM pms_room_inventory_daily WHERE property_id='SYNTHETIC_HOTEL_001' AND NOT is_synthetic)
       OR EXISTS (SELECT 1 FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001' AND NOT is_synthetic)
       OR EXISTS (SELECT 1 FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001' AND NOT is_synthetic) THEN
        RAISE EXCEPTION 'SCHEMA_CONTRACT_MISMATCH: non-synthetic PMS rows exist';
    END IF;
END $$;

DELETE FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001';
DELETE FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001';
DELETE FROM pms_room_inventory_daily WHERE property_id='SYNTHETIC_HOTEL_001';
DELETE FROM pms_guests WHERE property_id='SYNTHETIC_HOTEL_001';

INSERT INTO pms_guests (
    property_id, guest_id, guest_segment, country_group, crm_mapping_eligible,
    created_at, source_updated_at, is_synthetic
)
SELECT 'SYNTHETIC_HOTEL_001',
       'GST-' || lpad(n::text, 8, '0'),
       (ARRAY['LEISURE','BUSINESS','GROUP'])[1 + (n % 3)],
       (ARRAY['DOMESTIC','EAST_ASIA','SOUTHEAST_ASIA','OTHER'])[1 + (n % 4)],
       n <= 80000,
       TIMESTAMPTZ '2021-01-01 00:00:00+00' + ((n % 365) || ' days')::interval,
       TIMESTAMPTZ '2021-01-02 00:00:00+00' + ((n % 365) || ' days')::interval,
       true
FROM generate_series(1,100000) AS g(n);

WITH room_types(room_type_code, physical_rooms, type_order) AS (
    VALUES ('STANDARD',150,1),('DELUXE',90,2),('SUITE',40,3),('RESIDENCE',20,4)
)
INSERT INTO pms_room_inventory_daily (
    property_id, inventory_id, business_date, room_type_code, physical_rooms,
    out_of_order_rooms, house_use_rooms, available_room_nights,
    data_period_status, is_forecast, is_synthetic, source_updated_at
)
SELECT 'SYNTHETIC_HOTEL_001',
       row_number() OVER (ORDER BY d, type_order),
       d,
       room_type_code,
       physical_rooms,
       CASE WHEN extract(doy FROM d)::int % 31 = 0 THEN 2 ELSE 1 END,
       CASE WHEN extract(isodow FROM d)::int = 1 THEN 1 ELSE 0 END,
       physical_rooms
         - CASE WHEN extract(doy FROM d)::int % 31 = 0 THEN 2 ELSE 1 END
         - CASE WHEN extract(isodow FROM d)::int = 1 THEN 1 ELSE 0 END,
       CASE
           WHEN d < DATE '2025-01-01' THEN 'REFERENCE_CALIBRATED'
           WHEN d < DATE '2026-01-01' THEN 'SYNTHETIC_ACTUAL_LIKE'
           WHEN d <= DATE '2026-07-28' THEN 'YTD_SYNTHETIC'
           ELSE 'FORECAST_SCENARIO'
       END,
       d > DATE '2026-07-28',
       true,
       CASE
           WHEN d > DATE '2026-07-28' THEN TIMESTAMPTZ '2026-07-28 05:00:00+00'
           ELSE (d::timestamp + INTERVAL '18 hours') AT TIME ZONE 'UTC'
       END
FROM generate_series(DATE '2022-01-01', DATE '2026-12-31', INTERVAL '1 day') AS dates(d)
CROSS JOIN room_types;

CREATE TEMP TABLE scheduled_stays ON COMMIT DROP AS
WITH room_units AS (
    SELECT room_no,
           CASE
               WHEN room_no <= 150 THEN 'STANDARD'
               WHEN room_no <= 240 THEN 'DELUXE'
               WHEN room_no <= 280 THEN 'SUITE'
               ELSE 'RESIDENCE'
           END AS room_type_code,
           CASE
               WHEN room_no <= 150 THEN room_no
               WHEN room_no <= 240 THEN room_no - 150
               WHEN room_no <= 280 THEN room_no - 240
               ELSE room_no - 280
           END AS unit_sequence
    FROM generate_series(1,300) AS r(room_no)
),
cycles AS (
    SELECT d::date AS cycle_start
    FROM generate_series(DATE '2022-01-01', DATE '2026-07-27', INTERVAL '12 days') AS x(d)
),
slots AS (
    SELECT slot_no FROM generate_series(1,4) AS s(slot_no)
),
schedule AS (
    SELECT ru.*,
           c.cycle_start,
           s.slot_no,
           CASE
               WHEN ru.room_no % 10 = 0 THEN (ARRAY[0,6,8,10])[s.slot_no]
               ELSE (ARRAY[0,2,5,8])[s.slot_no]
           END AS start_offset,
           CASE
               WHEN ru.room_no % 10 = 0 THEN (ARRAY[5,1,1,1])[s.slot_no]
               ELSE (ARRAY[1,2,2,3])[s.slot_no]
           END AS stay_nights
    FROM room_units ru CROSS JOIN cycles c CROSS JOIN slots s
)
SELECT room_no,
       room_type_code,
       room_type_code || '-' || lpad(unit_sequence::text,3,'0') AS room_unit_code,
       cycle_start + start_offset AS checkin_date,
       cycle_start + start_offset + stay_nights AS checkout_date,
       stay_nights,
       slot_no,
       'RES-' || substr(md5(
           'SYNTHETIC_HOTEL_001|' || room_type_code || '|' || unit_sequence || '|' ||
           to_char(cycle_start + start_offset,'YYYY-MM-DD') || '|' || slot_no
       ),1,32) AS reservation_id
FROM schedule
WHERE cycle_start + start_offset + stay_nights <= DATE '2026-07-28';

WITH priced AS (
    SELECT s.*,
           'GST-' || lpad((1 + (abs(hashtext(reservation_id)) % 100000))::text,8,'0') AS guest_id,
           CASE room_type_code
               WHEN 'STANDARD' THEN 120000
               WHEN 'DELUXE' THEN 160000
               WHEN 'SUITE' THEN 220000
               ELSE 260000
           END *
           CASE extract(year FROM checkin_date)::int
               WHEN 2022 THEN 1.00
               WHEN 2023 THEN 1.07
               WHEN 2024 THEN 1.18
               WHEN 2025 THEN 1.26
               ELSE 1.32
           END AS nightly_rate
    FROM scheduled_stays s
)
INSERT INTO pms_reservations (
    property_id, reservation_id, guest_id, booked_at, checkin_date, checkout_date,
    room_type_code, rate_plan_code, market_segment, booking_channel,
    reservation_status, cancelled_at, cancellation_reason_code, adult_count,
    child_count, quoted_room_rate, gross_room_amount, discount_amount,
    commission_amount, booked_amount, refund_amount, cancellation_fee,
    data_period_status, is_forecast, is_synthetic, source_updated_at
)
SELECT 'SYNTHETIC_HOTEL_001', reservation_id, guest_id,
       (checkin_date::timestamp - INTERVAL '45 days') AT TIME ZONE 'UTC',
       checkin_date, checkout_date, room_type_code,
       CASE WHEN room_no % 5 = 0 THEN 'ADVANCE' ELSE 'FLEX' END,
       (ARRAY['LEISURE','BUSINESS','GROUP'])[1 + (room_no % 3)],
       (ARRAY['DIRECT','OTA','CORPORATE'])[1 + (room_no % 3)],
       'CHECKED_OUT', NULL, NULL, 1 + (room_no % 2), room_no % 2,
       round(nightly_rate,2),
       round(nightly_rate * stay_nights,2),
       0,
       round(nightly_rate * stay_nights * CASE WHEN room_no % 3 = 1 THEN 0.12 ELSE 0.03 END,2),
       round(nightly_rate * stay_nights,2),
       0, 0,
       CASE
           WHEN checkin_date < DATE '2025-01-01' THEN 'REFERENCE_CALIBRATED'
           WHEN checkin_date < DATE '2026-01-01' THEN 'SYNTHETIC_ACTUAL_LIKE'
           ELSE 'YTD_SYNTHETIC'
       END,
       false, true,
       (checkin_date::timestamp - INTERVAL '44 days 23 hours') AT TIME ZONE 'UTC'
FROM priced;

INSERT INTO pms_stays (
    property_id, stay_id, reservation_id, guest_id, room_unit_code,
    actual_checkin_at, actual_checkout_at, room_type_code, occupied_room_nights,
    guest_count, complimentary_flag, house_use_flag, room_revenue,
    other_room_charges, stay_status, data_period_status, is_forecast,
    is_synthetic, source_updated_at
)
SELECT r.property_id,
       'STY-' || substr(md5(r.property_id || '|' || r.reservation_id),1,32),
       r.reservation_id, r.guest_id, s.room_unit_code,
       (r.checkin_date::timestamp + INTERVAL '6 hours') AT TIME ZONE 'UTC',
       (r.checkout_date::timestamp + INTERVAL '2 hours') AT TIME ZONE 'UTC',
       r.room_type_code, r.checkout_date-r.checkin_date,
       r.adult_count+r.child_count, false, false, r.booked_amount,
       round(r.booked_amount*0.04,2), 'COMPLETED', r.data_period_status,
       false, true,
       least(
           (r.checkout_date::timestamp + INTERVAL '18 hours') AT TIME ZONE 'UTC',
           TIMESTAMPTZ '2026-07-28 05:00:00+00'
       )
FROM pms_reservations r
JOIN scheduled_stays s USING (reservation_id);

INSERT INTO pms_reservations VALUES (
    'SYNTHETIC_HOTEL_001','RES-INHOUSE-20260727-STD-001','GST-00000001',
    TIMESTAMPTZ '2026-06-01 03:00:00+00',DATE '2026-07-27',DATE '2026-07-30',
    'STANDARD','FLEX','LEISURE','DIRECT','CHECKED_IN',NULL,NULL,2,0,
    158400,475200,0,14256,475200,0,0,'YTD_SYNTHETIC',false,true,
    TIMESTAMPTZ '2026-07-28 04:00:00+00'
);

INSERT INTO pms_stays VALUES (
    'SYNTHETIC_HOTEL_001','STY-INHOUSE-20260727-STD-001','RES-INHOUSE-20260727-STD-001',
    'GST-00000001','STANDARD-150',TIMESTAMPTZ '2026-07-27 06:00:00+00',NULL,
    'STANDARD',0,2,false,false,0,0,'IN_HOUSE','YTD_SYNTHETIC',false,true,
    TIMESTAMPTZ '2026-07-28 04:00:00+00'
);

WITH needed AS (
    SELECT 220000 - count(*)::int AS remaining FROM pms_reservations
),
extra AS (
    SELECT g.n,
           DATE '2022-01-01' + ((g.n * 17) % 1820) AS checkin_date,
           1 + CASE WHEN g.n % 50 = 0 THEN 4 ELSE g.n % 3 END AS stay_nights
    FROM needed CROSS JOIN LATERAL generate_series(1, needed.remaining) AS g(n)
),
base AS (
    SELECT *,
           checkin_date + stay_nights AS checkout_date,
           'GST-' || lpad((1 + (n % 100000))::text,8,'0') AS guest_id,
           'RES-' || substr(md5('SYNTHETIC_HOTEL_001|EXTRA|' || n),1,32) AS reservation_id
    FROM extra
)
INSERT INTO pms_reservations (
    property_id, reservation_id, guest_id, booked_at, checkin_date, checkout_date,
    room_type_code, rate_plan_code, market_segment, booking_channel,
    reservation_status, cancelled_at, cancellation_reason_code, adult_count,
    child_count, quoted_room_rate, gross_room_amount, discount_amount,
    commission_amount, booked_amount, refund_amount, cancellation_fee,
    data_period_status, is_forecast, is_synthetic, source_updated_at
)
SELECT 'SYNTHETIC_HOTEL_001', reservation_id, guest_id,
       least(
           (checkin_date::timestamp - INTERVAL '60 days') AT TIME ZONE 'UTC',
           TIMESTAMPTZ '2026-06-01 00:00:00+00'
       ),
       checkin_date, checkout_date,
       (ARRAY['STANDARD','DELUXE','SUITE','RESIDENCE'])[1+(n%4)],
       'ADVANCE',
       (ARRAY['BUSINESS','GROUP','LEISURE'])[1+(n%3)],
       (ARRAY['OTA','DIRECT','CORPORATE'])[1+(n%3)],
       CASE WHEN checkin_date <= DATE '2026-07-28' THEN 'CANCELLED' ELSE 'BOOKED' END,
       CASE WHEN checkin_date <= DATE '2026-07-28'
            THEN (checkin_date::timestamp - INTERVAL '10 days') AT TIME ZONE 'UTC' END,
       CASE WHEN checkin_date <= DATE '2026-07-28' THEN 'PLAN_CHANGED' END,
       2, 0, 150000, 150000*stay_nights, 0, 0, 150000*stay_nights,
       CASE WHEN checkin_date <= DATE '2026-07-28' THEN 135000*stay_nights ELSE 0 END,
       CASE WHEN checkin_date <= DATE '2026-07-28' THEN 15000*stay_nights ELSE 0 END,
       CASE
           WHEN checkin_date < DATE '2025-01-01' THEN 'REFERENCE_CALIBRATED'
           WHEN checkin_date < DATE '2026-01-01' THEN 'SYNTHETIC_ACTUAL_LIKE'
           WHEN checkin_date <= DATE '2026-07-28' THEN 'YTD_SYNTHETIC'
           ELSE 'FORECAST_SCENARIO'
       END,
       checkin_date > DATE '2026-07-28', true,
       CASE
           WHEN checkin_date > DATE '2026-07-28' THEN TIMESTAMPTZ '2026-07-28 05:00:00+00'
           ELSE (checkin_date::timestamp - INTERVAL '9 days') AT TIME ZONE 'UTC'
       END
FROM base;

COMMIT;

SELECT 'pms_guests' AS table_name, count(*) AS row_count, max(source_updated_at) AS watermark,
       md5(string_agg(guest_id,',' ORDER BY guest_id)) AS checksum
FROM pms_guests WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'pms_room_inventory_daily', count(*), max(source_updated_at),
       md5(sum(inventory_id)::text)
FROM pms_room_inventory_daily WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'pms_reservations', count(*), max(source_updated_at),
       md5(sum(hashtext(reservation_id))::text)
FROM pms_reservations WHERE property_id='SYNTHETIC_HOTEL_001'
UNION ALL
SELECT 'pms_stays', count(*), max(source_updated_at),
       md5(sum(hashtext(stay_id))::text)
FROM pms_stays WHERE property_id='SYNTHETIC_HOTEL_001';

SELECT data_period_status, is_forecast, count(*) AS reservation_count
FROM pms_reservations
WHERE property_id='SYNTHETIC_HOTEL_001'
GROUP BY data_period_status, is_forecast
ORDER BY data_period_status, is_forecast;
