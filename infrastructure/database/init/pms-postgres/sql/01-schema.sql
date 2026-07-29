\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE IF NOT EXISTS public.pms_guests (
    property_id varchar(64) NOT NULL,
    guest_id varchar(36) PRIMARY KEY,
    guest_segment varchar(24) NOT NULL,
    country_group varchar(24) NOT NULL,
    crm_mapping_eligible boolean NOT NULL,
    created_at timestamptz NOT NULL,
    source_updated_at timestamptz NOT NULL,
    is_synthetic boolean NOT NULL,
    CONSTRAINT ck_pms_guests_property
        CHECK (property_id = 'SYNTHETIC_HOTEL_001'),
    CONSTRAINT ck_pms_guests_id
        CHECK (guest_id ~ '^GST-[0-9A-F]{8}$'),
    CONSTRAINT ck_pms_guests_segment
        CHECK (guest_segment IN ('LEISURE', 'BUSINESS', 'GROUP')),
    CONSTRAINT ck_pms_guests_synthetic
        CHECK (is_synthetic)
);

CREATE TABLE IF NOT EXISTS public.pms_room_inventory_daily (
    property_id varchar(64) NOT NULL,
    inventory_id bigint PRIMARY KEY,
    business_date date NOT NULL,
    room_type_code varchar(32) NOT NULL,
    physical_rooms integer NOT NULL,
    out_of_order_rooms integer NOT NULL,
    house_use_rooms integer NOT NULL,
    available_room_nights integer NOT NULL,
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL,
    source_updated_at timestamptz NOT NULL,
    CONSTRAINT uq_pms_inventory_date_room_type
        UNIQUE (business_date, room_type_code),
    CONSTRAINT ck_pms_inventory_property
        CHECK (property_id = 'SYNTHETIC_HOTEL_001'),
    CONSTRAINT ck_pms_inventory_counts
        CHECK (
            physical_rooms >= 0
            AND out_of_order_rooms >= 0
            AND house_use_rooms >= 0
            AND available_room_nights >= 0
        ),
    CONSTRAINT ck_pms_inventory_available
        CHECK (
            available_room_nights =
                physical_rooms - out_of_order_rooms - house_use_rooms
        ),
    CONSTRAINT ck_pms_inventory_period
        CHECK (
            data_period_status IN (
                'REFERENCE_CALIBRATED',
                'SYNTHETIC_ACTUAL_LIKE',
                'YTD_SYNTHETIC',
                'FORECAST_SCENARIO'
            )
        ),
    CONSTRAINT ck_pms_inventory_forecast
        CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO')),
    CONSTRAINT ck_pms_inventory_cutoff
        CHECK (
            (business_date < DATE '2026-07-29' AND NOT is_forecast)
            OR (business_date >= DATE '2026-07-29' AND is_forecast)
        ),
    CONSTRAINT ck_pms_inventory_synthetic
        CHECK (is_synthetic)
);

CREATE TABLE IF NOT EXISTS public.pms_reservations (
    property_id varchar(64) NOT NULL,
    reservation_id varchar(36) PRIMARY KEY,
    guest_id varchar(36) NOT NULL
        REFERENCES public.pms_guests (guest_id),
    booked_at timestamptz NOT NULL,
    checkin_date date NOT NULL,
    checkout_date date NOT NULL,
    room_type_code varchar(32) NOT NULL,
    rate_plan_code varchar(32) NOT NULL,
    market_segment varchar(24) NOT NULL,
    booking_channel varchar(24) NOT NULL,
    reservation_status varchar(20) NOT NULL,
    cancelled_at timestamptz,
    cancellation_reason_code varchar(32),
    adult_count integer NOT NULL,
    child_count integer NOT NULL,
    quoted_room_rate numeric(14,2) NOT NULL,
    gross_room_amount numeric(14,2) NOT NULL,
    discount_amount numeric(14,2) NOT NULL,
    commission_amount numeric(14,2) NOT NULL,
    booked_amount numeric(14,2) NOT NULL,
    refund_amount numeric(14,2) NOT NULL,
    cancellation_fee numeric(14,2) NOT NULL,
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL,
    source_updated_at timestamptz NOT NULL,
    CONSTRAINT ck_pms_reservations_property
        CHECK (property_id = 'SYNTHETIC_HOTEL_001'),
    CONSTRAINT ck_pms_reservations_date_range
        CHECK (checkout_date > checkin_date),
    CONSTRAINT ck_pms_reservations_booking_channel
        CHECK (booking_channel IN ('DIRECT', 'OTA', 'CORPORATE')),
    CONSTRAINT ck_pms_reservations_status
        CHECK (
            reservation_status IN (
                'BOOKED',
                'CANCELLED',
                'CHECKED_IN',
                'CHECKED_OUT',
                'NO_SHOW'
            )
        ),
    CONSTRAINT ck_pms_reservations_cancellation
        CHECK (
            (reservation_status = 'CANCELLED' AND cancelled_at IS NOT NULL)
            OR (reservation_status <> 'CANCELLED')
        ),
    CONSTRAINT ck_pms_reservations_counts
        CHECK (adult_count >= 0 AND child_count >= 0),
    CONSTRAINT ck_pms_reservations_amounts
        CHECK (
            quoted_room_rate >= 0
            AND gross_room_amount >= 0
            AND discount_amount >= 0
            AND commission_amount >= 0
            AND booked_amount >= 0
            AND refund_amount >= 0
            AND cancellation_fee >= 0
        ),
    CONSTRAINT ck_pms_reservations_gross_amount
        CHECK (
            gross_room_amount =
                quoted_room_rate * (checkout_date - checkin_date)
        ),
    CONSTRAINT ck_pms_reservations_period
        CHECK (
            data_period_status IN (
                'REFERENCE_CALIBRATED',
                'SYNTHETIC_ACTUAL_LIKE',
                'YTD_SYNTHETIC',
                'FORECAST_SCENARIO'
            )
        ),
    CONSTRAINT ck_pms_reservations_forecast
        CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO')),
    CONSTRAINT ck_pms_reservations_synthetic
        CHECK (is_synthetic)
);

CREATE INDEX IF NOT EXISTS ix_pms_reservations_checkin_status
    ON public.pms_reservations (checkin_date, reservation_status);
CREATE INDEX IF NOT EXISTS ix_pms_reservations_guest_checkin
    ON public.pms_reservations (guest_id, checkin_date);

CREATE TABLE IF NOT EXISTS public.pms_stays (
    property_id varchar(64) NOT NULL,
    stay_id varchar(36) PRIMARY KEY,
    reservation_id varchar(36) NOT NULL
        REFERENCES public.pms_reservations (reservation_id),
    guest_id varchar(36) NOT NULL
        REFERENCES public.pms_guests (guest_id),
    room_unit_code varchar(32) NOT NULL,
    actual_checkin_at timestamptz,
    actual_checkout_at timestamptz,
    room_type_code varchar(32) NOT NULL,
    occupied_room_nights integer NOT NULL,
    guest_count integer NOT NULL,
    complimentary_flag boolean NOT NULL,
    house_use_flag boolean NOT NULL,
    room_revenue numeric(14,2) NOT NULL,
    other_room_charges numeric(14,2) NOT NULL,
    stay_status varchar(20) NOT NULL,
    data_period_status varchar(32) NOT NULL,
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL,
    source_updated_at timestamptz NOT NULL,
    CONSTRAINT ck_pms_stays_property
        CHECK (property_id = 'SYNTHETIC_HOTEL_001'),
    CONSTRAINT ck_pms_stays_times
        CHECK (
            actual_checkout_at IS NULL
            OR actual_checkin_at IS NULL
            OR actual_checkout_at > actual_checkin_at
        ),
    CONSTRAINT ck_pms_stays_counts
        CHECK (occupied_room_nights >= 0 AND guest_count >= 1),
    CONSTRAINT ck_pms_stays_amounts
        CHECK (room_revenue >= 0 AND other_room_charges >= 0),
    CONSTRAINT ck_pms_stays_status
        CHECK (
            stay_status IN (
                'EXPECTED',
                'IN_HOUSE',
                'COMPLETED',
                'CANCELLED',
                'NO_SHOW'
            )
        ),
    CONSTRAINT ck_pms_stays_period
        CHECK (
            data_period_status IN (
                'REFERENCE_CALIBRATED',
                'SYNTHETIC_ACTUAL_LIKE',
                'YTD_SYNTHETIC',
                'FORECAST_SCENARIO'
            )
        ),
    CONSTRAINT ck_pms_stays_forecast
        CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO')),
    CONSTRAINT ck_pms_stays_synthetic
        CHECK (is_synthetic)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pms_stays_reservation
    ON public.pms_stays (reservation_id);
CREATE INDEX IF NOT EXISTS ix_pms_stays_guest_checkin
    ON public.pms_stays (guest_id, actual_checkin_at);

COMMENT ON TABLE public.pms_guests IS
    'Synthetic PMS-local guest keys and coarse groups only; no direct identifiers are permitted.';
COMMENT ON TABLE public.pms_room_inventory_daily IS
    'Synthetic daily room supply with explicit actual-like/YTD/forecast state.';
COMMENT ON TABLE public.pms_reservations IS
    'Synthetic reservations; no names, contact details, addresses, cards, or credentials.';
COMMENT ON TABLE public.pms_stays IS
    'Synthetic stay facts linked only within the PMS source.';

COMMIT;
