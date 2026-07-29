\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE IF NOT EXISTS public.banquet_bookings (
    property_id varchar(64) NOT NULL,
    banquet_event_id varchar(36) PRIMARY KEY,
    customer_id varchar(36) NOT NULL,
    inquiry_at timestamptz NOT NULL,
    quoted_at timestamptz,
    confirmed_at timestamptz,
    cancelled_at timestamptz,
    event_date date NOT NULL,
    product_code varchar(32) NOT NULL,
    product_category varchar(32) NOT NULL,
    expected_guests integer NOT NULL,
    actual_attendees integer,
    lead_source varchar(24) NOT NULL,
    sales_owner_team varchar(32) NOT NULL,
    booking_status varchar(20) NOT NULL,
    contracted_amount numeric(14,2) NOT NULL,
    pickup_room_count integer NOT NULL,
    released_room_count integer NOT NULL,
    group_checkout_date date,
    group_checkin_date date,
    expected_room_nights integer NOT NULL,
    reserved_room_block_count integer NOT NULL,
    cancellation_fee numeric(14,2) NOT NULL,
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL,
    source_updated_at timestamptz NOT NULL,
    CONSTRAINT ck_banquet_bookings_property
        CHECK (property_id = 'SYNTHETIC_HOTEL_001'),
    CONSTRAINT ck_banquet_bookings_customer_id
        CHECK (customer_id ~ '^BQC-[0-9A-F]{8}$'),
    CONSTRAINT ck_banquet_bookings_time_order
        CHECK (
            (quoted_at IS NULL OR quoted_at >= inquiry_at)
            AND (confirmed_at IS NULL OR confirmed_at >= inquiry_at)
            AND (cancelled_at IS NULL OR cancelled_at >= inquiry_at)
        ),
    CONSTRAINT ck_banquet_bookings_category
        CHECK (
            product_category IN (
                'WEDDING',
                'CONFERENCE',
                'MEETING',
                'CORPORATE_EVENT',
                'SOCIAL_EVENT'
            )
        ),
    CONSTRAINT ck_banquet_bookings_counts
        CHECK (
            expected_guests >= 0
            AND (actual_attendees IS NULL OR actual_attendees >= 0)
            AND pickup_room_count >= 0
            AND released_room_count >= 0
            AND expected_room_nights >= 0
            AND reserved_room_block_count >= 0
        ),
    CONSTRAINT ck_banquet_bookings_group_dates
        CHECK (
            (group_checkin_date IS NULL AND group_checkout_date IS NULL)
            OR (
                group_checkin_date IS NOT NULL
                AND group_checkout_date IS NOT NULL
                AND group_checkout_date > group_checkin_date
            )
        ),
    CONSTRAINT ck_banquet_bookings_status
        CHECK (
            booking_status IN (
                'INQUIRY',
                'QUOTED',
                'TENTATIVE',
                'CONFIRMED',
                'CANCELLED',
                'COMPLETED'
            )
        ),
    CONSTRAINT ck_banquet_bookings_amounts
        CHECK (contracted_amount >= 0 AND cancellation_fee >= 0),
    CONSTRAINT ck_banquet_bookings_period
        CHECK (
            data_period_status IN (
                'REFERENCE_CALIBRATED',
                'SYNTHETIC_ACTUAL_LIKE',
                'YTD_SYNTHETIC',
                'FORECAST_SCENARIO'
            )
        ),
    CONSTRAINT ck_banquet_bookings_forecast
        CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO')),
    CONSTRAINT ck_banquet_bookings_cutoff
        CHECK (
            (event_date < DATE '2026-07-29' AND NOT is_forecast)
            OR (event_date >= DATE '2026-07-29' AND is_forecast)
        ),
    CONSTRAINT ck_banquet_bookings_synthetic
        CHECK (is_synthetic)
);

CREATE INDEX IF NOT EXISTS ix_banquet_bookings_event_status
    ON public.banquet_bookings (event_date, booking_status);
CREATE INDEX IF NOT EXISTS ix_banquet_bookings_customer_event
    ON public.banquet_bookings (customer_id, event_date);

CREATE TABLE IF NOT EXISTS public.banquet_revenue (
    property_id varchar(64) NOT NULL,
    revenue_id varchar(36) PRIMARY KEY,
    banquet_event_id varchar(36) NOT NULL
        REFERENCES public.banquet_bookings (banquet_event_id),
    recognized_date date NOT NULL,
    product_code varchar(32) NOT NULL,
    product_category varchar(32) NOT NULL,
    revenue_amount numeric(14,2) NOT NULL,
    reversal_amount numeric(14,2) NOT NULL,
    cost_amount numeric(14,2) NOT NULL,
    revenue_status varchar(16) NOT NULL,
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL,
    source_updated_at timestamptz NOT NULL,
    CONSTRAINT ck_banquet_revenue_property
        CHECK (property_id = 'SYNTHETIC_HOTEL_001'),
    CONSTRAINT ck_banquet_revenue_category
        CHECK (
            product_category IN (
                'VENUE',
                'FOOD_BEVERAGE',
                'EQUIPMENT',
                'DECORATION',
                'SERVICE',
                'ACCOMMODATION_PACKAGE'
            )
        ),
    CONSTRAINT ck_banquet_revenue_amounts
        CHECK (
            revenue_amount >= 0
            AND reversal_amount >= 0
            AND cost_amount >= 0
        ),
    CONSTRAINT ck_banquet_revenue_status
        CHECK (revenue_status IN ('EXPECTED', 'RECOGNIZED', 'REVERSED')),
    CONSTRAINT ck_banquet_revenue_reversal
        CHECK (
            (revenue_status = 'REVERSED' AND reversal_amount > 0)
            OR (revenue_status <> 'REVERSED' AND reversal_amount = 0)
        ),
    CONSTRAINT ck_banquet_revenue_period
        CHECK (
            data_period_status IN (
                'REFERENCE_CALIBRATED',
                'SYNTHETIC_ACTUAL_LIKE',
                'YTD_SYNTHETIC',
                'FORECAST_SCENARIO'
            )
        ),
    CONSTRAINT ck_banquet_revenue_forecast
        CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO')),
    CONSTRAINT ck_banquet_revenue_cutoff
        CHECK (
            (recognized_date < DATE '2026-07-29' AND NOT is_forecast)
            OR (recognized_date >= DATE '2026-07-29' AND is_forecast)
        ),
    CONSTRAINT ck_banquet_revenue_synthetic
        CHECK (is_synthetic)
);

CREATE INDEX IF NOT EXISTS ix_banquet_revenue_event_recognized
    ON public.banquet_revenue (banquet_event_id, recognized_date);

COMMENT ON TABLE public.banquet_bookings IS
    'Synthetic banquet events using local customer keys only; no direct identifiers are permitted.';
COMMENT ON TABLE public.banquet_revenue IS
    'Synthetic banquet revenue facts linked only within the banquet source.';

COMMIT;
