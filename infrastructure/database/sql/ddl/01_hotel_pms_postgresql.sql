-- source_id=pms; engine=PostgreSQL; database=pms_db
-- ingestion_role=pms_ingest; query_role=pms_readonly
-- datahub_platform_instance=pms_db; trino_catalog=pms
-- schema_version=1.0.0
\set ON_ERROR_STOP on
SET client_encoding = 'UTF8';
SET timezone = 'Asia/Seoul';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pms_ingest') THEN
        CREATE ROLE pms_ingest NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pms_readonly') THEN
        CREATE ROLE pms_readonly NOLOGIN;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS pms_guests (
    property_id varchar(64) NOT NULL,
    guest_id varchar(36) PRIMARY KEY,
    guest_segment varchar(24) NOT NULL CHECK (guest_segment IN ('LEISURE','BUSINESS','GROUP')),
    country_group varchar(24) NOT NULL,
    crm_mapping_eligible boolean NOT NULL,
    created_at timestamptz NOT NULL,
    source_updated_at timestamptz NOT NULL,
    is_synthetic boolean NOT NULL CHECK (is_synthetic),
    CHECK (created_at <= source_updated_at),
    UNIQUE (property_id, guest_id)
);

CREATE TABLE IF NOT EXISTS pms_room_inventory_daily (
    property_id varchar(64) NOT NULL,
    inventory_id bigint PRIMARY KEY,
    business_date date NOT NULL,
    room_type_code varchar(32) NOT NULL CHECK (room_type_code IN ('STANDARD','DELUXE','SUITE','RESIDENCE')),
    physical_rooms integer NOT NULL CHECK (physical_rooms >= 0),
    out_of_order_rooms integer NOT NULL CHECK (out_of_order_rooms >= 0),
    house_use_rooms integer NOT NULL CHECK (house_use_rooms >= 0),
    available_room_nights integer NOT NULL CHECK (available_room_nights >= 0),
    data_period_status varchar(32) NOT NULL CHECK (data_period_status IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL CHECK (is_synthetic),
    source_updated_at timestamptz NOT NULL,
    UNIQUE (property_id, business_date, room_type_code),
    CHECK (available_room_nights = physical_rooms - out_of_order_rooms - house_use_rooms),
    CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO'))
);

CREATE TABLE IF NOT EXISTS pms_reservations (
    property_id varchar(64) NOT NULL,
    reservation_id varchar(36) PRIMARY KEY,
    guest_id varchar(36) NOT NULL REFERENCES pms_guests(guest_id),
    booked_at timestamptz NOT NULL,
    checkin_date date NOT NULL,
    checkout_date date NOT NULL,
    room_type_code varchar(32) NOT NULL CHECK (room_type_code IN ('STANDARD','DELUXE','SUITE','RESIDENCE')),
    rate_plan_code varchar(32) NOT NULL,
    market_segment varchar(24) NOT NULL CHECK (market_segment IN ('LEISURE','BUSINESS','GROUP')),
    booking_channel varchar(24) NOT NULL CHECK (booking_channel IN ('DIRECT','OTA','CORPORATE')),
    reservation_status varchar(20) NOT NULL CHECK (reservation_status IN ('BOOKED','CANCELLED','CHECKED_IN','CHECKED_OUT','NO_SHOW')),
    cancelled_at timestamptz,
    cancellation_reason_code varchar(32),
    adult_count integer NOT NULL CHECK (adult_count >= 0),
    child_count integer NOT NULL CHECK (child_count >= 0),
    quoted_room_rate numeric(14,2) NOT NULL CHECK (quoted_room_rate >= 0),
    gross_room_amount numeric(14,2) NOT NULL CHECK (gross_room_amount >= 0),
    discount_amount numeric(14,2) NOT NULL CHECK (discount_amount >= 0),
    commission_amount numeric(14,2) NOT NULL CHECK (commission_amount >= 0),
    booked_amount numeric(14,2) NOT NULL CHECK (booked_amount >= 0),
    refund_amount numeric(14,2) NOT NULL CHECK (refund_amount >= 0),
    cancellation_fee numeric(14,2) NOT NULL CHECK (cancellation_fee >= 0),
    data_period_status varchar(32) NOT NULL CHECK (data_period_status IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
    is_forecast boolean NOT NULL,
    is_synthetic boolean NOT NULL CHECK (is_synthetic),
    source_updated_at timestamptz NOT NULL,
    CHECK (checkout_date > checkin_date),
    CHECK (booked_at < checkin_date::timestamp AT TIME ZONE 'Asia/Seoul'),
    CHECK (booked_at <= source_updated_at),
    CHECK (gross_room_amount = quoted_room_rate * (checkout_date - checkin_date)),
    CHECK (booked_amount = gross_room_amount - discount_amount),
    CHECK (commission_amount <= booked_amount),
    CHECK (
        (reservation_status = 'CANCELLED'
         AND cancelled_at IS NOT NULL
         AND cancellation_fee <= booked_amount
         AND refund_amount + cancellation_fee = booked_amount)
        OR
        (reservation_status <> 'CANCELLED'
         AND cancelled_at IS NULL
         AND refund_amount = 0
         AND cancellation_fee = 0)
    ),
    CHECK (is_forecast = (data_period_status = 'FORECAST_SCENARIO'))
);

CREATE TABLE IF NOT EXISTS pms_stays (
    property_id varchar(64) NOT NULL,
    stay_id varchar(36) PRIMARY KEY,
    reservation_id varchar(36) NOT NULL UNIQUE REFERENCES pms_reservations(reservation_id),
    guest_id varchar(36) NOT NULL REFERENCES pms_guests(guest_id),
    room_unit_code varchar(32) NOT NULL,
    actual_checkin_at timestamptz,
    actual_checkout_at timestamptz,
    room_type_code varchar(32) NOT NULL CHECK (room_type_code IN ('STANDARD','DELUXE','SUITE','RESIDENCE')),
    occupied_room_nights integer NOT NULL CHECK (occupied_room_nights >= 0),
    guest_count integer NOT NULL CHECK (guest_count >= 1),
    complimentary_flag boolean NOT NULL,
    house_use_flag boolean NOT NULL,
    room_revenue numeric(14,2) NOT NULL CHECK (room_revenue >= 0),
    other_room_charges numeric(14,2) NOT NULL CHECK (other_room_charges >= 0),
    stay_status varchar(20) NOT NULL CHECK (stay_status IN ('EXPECTED','IN_HOUSE','COMPLETED','CANCELLED','NO_SHOW')),
    data_period_status varchar(32) NOT NULL CHECK (data_period_status IN ('REFERENCE_CALIBRATED','SYNTHETIC_ACTUAL_LIKE','YTD_SYNTHETIC','FORECAST_SCENARIO')),
    is_forecast boolean NOT NULL CHECK (NOT is_forecast),
    is_synthetic boolean NOT NULL CHECK (is_synthetic),
    source_updated_at timestamptz NOT NULL,
    CHECK (actual_checkout_at IS NULL OR actual_checkin_at IS NULL OR actual_checkout_at > actual_checkin_at),
    CHECK (
        stay_status <> 'COMPLETED'
        OR occupied_room_nights = (actual_checkout_at::date - actual_checkin_at::date)
    ),
    CHECK (
        NOT (complimentary_flag OR house_use_flag)
        OR room_revenue = 0
    )
);

CREATE TABLE IF NOT EXISTS schema_version (version varchar(32) PRIMARY KEY);
CREATE TABLE IF NOT EXISTS seed_metadata (seed integer PRIMARY KEY, data_class varchar(16) NOT NULL);
INSERT INTO schema_version(version) VALUES ('1.0.0') ON CONFLICT (version) DO NOTHING;
INSERT INTO seed_metadata(seed, data_class) VALUES (20260729, 'synthetic') ON CONFLICT (seed) DO NOTHING;

CREATE OR REPLACE VIEW pms_stays_actual AS
SELECT *
FROM pms_stays
WHERE is_forecast = false
  AND data_period_status <> 'FORECAST_SCENARIO';

CREATE INDEX IF NOT EXISTS idx_pms_reservations_date_status ON pms_reservations(checkin_date, reservation_status);
CREATE INDEX IF NOT EXISTS idx_pms_reservations_guest_date ON pms_reservations(guest_id, checkin_date);
CREATE INDEX IF NOT EXISTS idx_pms_stays_guest_checkin ON pms_stays(guest_id, actual_checkin_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON pms_guests, pms_room_inventory_daily, pms_reservations, pms_stays TO pms_ingest;
GRANT SELECT ON pms_guests, pms_room_inventory_daily, pms_reservations, pms_stays, pms_stays_actual TO pms_readonly;
GRANT SELECT ON schema_version, seed_metadata TO pms_readonly;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM pms_readonly;
REVOKE CREATE ON SCHEMA public FROM pms_readonly;

COMMENT ON TABLE pms_guests IS 'Synthetic PMS guest without direct identifiers';
COMMENT ON TABLE pms_room_inventory_daily IS 'Daily room supply by room type';
COMMENT ON TABLE pms_reservations IS 'Synthetic reservation contract and cancellation amounts';
COMMENT ON TABLE pms_stays IS 'Actual synthetic stay and recognized room revenue';
COMMENT ON COLUMN pms_reservations.booked_amount IS 'Contract value; not recognized room revenue';
COMMENT ON COLUMN pms_stays.room_revenue IS 'Recognized revenue for completed non-free stays';

SELECT count(*) AS pms_table_count
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
