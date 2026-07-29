\set ON_ERROR_STOP on

BEGIN;
SET LOCAL TIME ZONE 'UTC';

WITH fixture AS (
    SELECT
        'BQE-' || upper(substr(md5(:'synthetic_data_seed' || ':banquet:event:1'), 1, 8))
            AS banquet_event_id,
        'BQC-' || upper(substr(md5(:'synthetic_data_seed' || ':banquet:customer:1'), 1, 8))
            AS customer_id
)
INSERT INTO public.banquet_bookings (
    property_id,
    banquet_event_id,
    customer_id,
    inquiry_at,
    quoted_at,
    confirmed_at,
    cancelled_at,
    event_date,
    product_code,
    product_category,
    expected_guests,
    actual_attendees,
    lead_source,
    sales_owner_team,
    booking_status,
    contracted_amount,
    pickup_room_count,
    released_room_count,
    group_checkout_date,
    group_checkin_date,
    expected_room_nights,
    reserved_room_block_count,
    cancellation_fee,
    data_period_status,
    is_forecast,
    is_synthetic,
    source_updated_at
)
SELECT
    'SYNTHETIC_HOTEL_001',
    banquet_event_id,
    customer_id,
    TIMESTAMPTZ '2026-06-20 10:00:00+09',
    TIMESTAMPTZ '2026-06-21 14:00:00+09',
    TIMESTAMPTZ '2026-06-23 11:00:00+09',
    NULL,
    DATE '2026-07-20',
    'CORP-CONF-01',
    'CONFERENCE',
    80,
    76,
    'DIRECT',
    'BANQUET_TEAM_A',
    'COMPLETED',
    5000000.00,
    4,
    1,
    DATE '2026-07-21',
    DATE '2026-07-19',
    8,
    5,
    0.00,
    'YTD_SYNTHETIC',
    false,
    true,
    :'generated_at'::timestamptz
FROM fixture
ON CONFLICT (banquet_event_id) DO UPDATE
SET
    customer_id = EXCLUDED.customer_id,
    expected_guests = EXCLUDED.expected_guests,
    actual_attendees = EXCLUDED.actual_attendees,
    booking_status = EXCLUDED.booking_status,
    contracted_amount = EXCLUDED.contracted_amount,
    data_period_status = EXCLUDED.data_period_status,
    is_forecast = EXCLUDED.is_forecast,
    is_synthetic = true,
    source_updated_at = EXCLUDED.source_updated_at;

WITH fixture AS (
    SELECT
        'BQE-' || upper(substr(md5(:'synthetic_data_seed' || ':banquet:event:1'), 1, 8))
            AS banquet_event_id,
        'BQR-' || upper(substr(md5(:'synthetic_data_seed' || ':banquet:revenue:1'), 1, 8))
            AS revenue_id
)
INSERT INTO public.banquet_revenue (
    property_id,
    revenue_id,
    banquet_event_id,
    recognized_date,
    product_code,
    product_category,
    revenue_amount,
    reversal_amount,
    cost_amount,
    revenue_status,
    data_period_status,
    is_forecast,
    is_synthetic,
    source_updated_at
)
SELECT
    'SYNTHETIC_HOTEL_001',
    revenue_id,
    banquet_event_id,
    DATE '2026-07-20',
    'CORP-CONF-01',
    'VENUE',
    5000000.00,
    0.00,
    3100000.00,
    'RECOGNIZED',
    'YTD_SYNTHETIC',
    false,
    true,
    :'generated_at'::timestamptz
FROM fixture
ON CONFLICT (revenue_id) DO UPDATE
SET
    banquet_event_id = EXCLUDED.banquet_event_id,
    revenue_amount = EXCLUDED.revenue_amount,
    reversal_amount = EXCLUDED.reversal_amount,
    cost_amount = EXCLUDED.cost_amount,
    revenue_status = EXCLUDED.revenue_status,
    data_period_status = EXCLUDED.data_period_status,
    is_forecast = EXCLUDED.is_forecast,
    is_synthetic = true,
    source_updated_at = EXCLUDED.source_updated_at;

COMMIT;
