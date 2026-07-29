\set ON_ERROR_STOP on

BEGIN;
SET LOCAL TIME ZONE 'UTC';

WITH fixture AS (
    SELECT
        'GST-' || upper(substr(md5(:'synthetic_data_seed' || ':pms:guest:1'), 1, 8))
            AS guest_id
)
INSERT INTO public.pms_guests (
    property_id,
    guest_id,
    guest_segment,
    country_group,
    crm_mapping_eligible,
    created_at,
    source_updated_at,
    is_synthetic
)
SELECT
    'SYNTHETIC_HOTEL_001',
    guest_id,
    'BUSINESS',
    'DOMESTIC',
    true,
    :'generated_at'::timestamptz,
    :'generated_at'::timestamptz,
    true
FROM fixture
ON CONFLICT (guest_id) DO UPDATE
SET
    guest_segment = EXCLUDED.guest_segment,
    country_group = EXCLUDED.country_group,
    crm_mapping_eligible = EXCLUDED.crm_mapping_eligible,
    source_updated_at = EXCLUDED.source_updated_at,
    is_synthetic = true;

INSERT INTO public.pms_room_inventory_daily (
    property_id,
    inventory_id,
    business_date,
    room_type_code,
    physical_rooms,
    out_of_order_rooms,
    house_use_rooms,
    available_room_nights,
    data_period_status,
    is_forecast,
    is_synthetic,
    source_updated_at
)
VALUES (
    'SYNTHETIC_HOTEL_001',
    (
        ('x' || substr(md5(:'synthetic_data_seed' || ':pms:inventory:1'), 1, 8))
        ::bit(32)::bigint
    ),
    DATE '2026-07-28',
    'DELUXE',
    100,
    3,
    2,
    95,
    'YTD_SYNTHETIC',
    false,
    true,
    :'generated_at'::timestamptz
)
ON CONFLICT (inventory_id) DO UPDATE
SET
    physical_rooms = EXCLUDED.physical_rooms,
    out_of_order_rooms = EXCLUDED.out_of_order_rooms,
    house_use_rooms = EXCLUDED.house_use_rooms,
    available_room_nights = EXCLUDED.available_room_nights,
    data_period_status = EXCLUDED.data_period_status,
    is_forecast = EXCLUDED.is_forecast,
    is_synthetic = true,
    source_updated_at = EXCLUDED.source_updated_at;

WITH fixture AS (
    SELECT
        'GST-' || upper(substr(md5(:'synthetic_data_seed' || ':pms:guest:1'), 1, 8))
            AS guest_id,
        'RSV-' || upper(substr(md5(:'synthetic_data_seed' || ':pms:reservation:1'), 1, 8))
            AS reservation_id
)
INSERT INTO public.pms_reservations (
    property_id,
    reservation_id,
    guest_id,
    booked_at,
    checkin_date,
    checkout_date,
    room_type_code,
    rate_plan_code,
    market_segment,
    booking_channel,
    reservation_status,
    cancelled_at,
    cancellation_reason_code,
    adult_count,
    child_count,
    quoted_room_rate,
    gross_room_amount,
    discount_amount,
    commission_amount,
    booked_amount,
    refund_amount,
    cancellation_fee,
    data_period_status,
    is_forecast,
    is_synthetic,
    source_updated_at
)
SELECT
    'SYNTHETIC_HOTEL_001',
    reservation_id,
    guest_id,
    TIMESTAMPTZ '2026-07-01 09:00:00+09',
    DATE '2026-07-27',
    DATE '2026-07-29',
    'DELUXE',
    'FLEX',
    'BUSINESS',
    'DIRECT',
    'CHECKED_OUT',
    NULL,
    NULL,
    2,
    0,
    220000.00,
    440000.00,
    20000.00,
    0.00,
    420000.00,
    0.00,
    0.00,
    'YTD_SYNTHETIC',
    false,
    true,
    :'generated_at'::timestamptz
FROM fixture
ON CONFLICT (reservation_id) DO UPDATE
SET
    guest_id = EXCLUDED.guest_id,
    reservation_status = EXCLUDED.reservation_status,
    gross_room_amount = EXCLUDED.gross_room_amount,
    booked_amount = EXCLUDED.booked_amount,
    data_period_status = EXCLUDED.data_period_status,
    is_forecast = EXCLUDED.is_forecast,
    is_synthetic = true,
    source_updated_at = EXCLUDED.source_updated_at;

WITH fixture AS (
    SELECT
        'GST-' || upper(substr(md5(:'synthetic_data_seed' || ':pms:guest:1'), 1, 8))
            AS guest_id,
        'RSV-' || upper(substr(md5(:'synthetic_data_seed' || ':pms:reservation:1'), 1, 8))
            AS reservation_id,
        'STY-' || upper(substr(md5(:'synthetic_data_seed' || ':pms:stay:1'), 1, 8))
            AS stay_id
)
INSERT INTO public.pms_stays (
    property_id,
    stay_id,
    reservation_id,
    guest_id,
    room_unit_code,
    actual_checkin_at,
    actual_checkout_at,
    room_type_code,
    occupied_room_nights,
    guest_count,
    complimentary_flag,
    house_use_flag,
    room_revenue,
    other_room_charges,
    stay_status,
    data_period_status,
    is_forecast,
    is_synthetic,
    source_updated_at
)
SELECT
    'SYNTHETIC_HOTEL_001',
    stay_id,
    reservation_id,
    guest_id,
    'DELUXE-0001',
    TIMESTAMPTZ '2026-07-27 15:00:00+09',
    TIMESTAMPTZ '2026-07-29 11:00:00+09',
    'DELUXE',
    2,
    2,
    false,
    false,
    420000.00,
    50000.00,
    'COMPLETED',
    'YTD_SYNTHETIC',
    false,
    true,
    :'generated_at'::timestamptz
FROM fixture
ON CONFLICT (stay_id) DO UPDATE
SET
    reservation_id = EXCLUDED.reservation_id,
    guest_id = EXCLUDED.guest_id,
    room_revenue = EXCLUDED.room_revenue,
    other_room_charges = EXCLUDED.other_room_charges,
    stay_status = EXCLUDED.stay_status,
    data_period_status = EXCLUDED.data_period_status,
    is_forecast = EXCLUDED.is_forecast,
    is_synthetic = true,
    source_updated_at = EXCLUDED.source_updated_at;

COMMIT;
