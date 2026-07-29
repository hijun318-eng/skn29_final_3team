CREATE SCHEMA IF NOT EXISTS pms;

CREATE TABLE IF NOT EXISTS pms.hotel (
    hotel_id integer PRIMARY KEY,
    hotel_name text NOT NULL,
    city text NOT NULL,
    timezone text NOT NULL
);

CREATE TABLE IF NOT EXISTS pms.room_type (
    room_type_code text PRIMARY KEY,
    room_type_name text NOT NULL,
    base_capacity integer NOT NULL CHECK (base_capacity > 0)
);

CREATE TABLE IF NOT EXISTS pms.reservation (
    reservation_id bigint PRIMARY KEY,
    guest_token text NOT NULL,
    hotel_id integer NOT NULL REFERENCES pms.hotel(hotel_id),
    room_type_code text NOT NULL REFERENCES pms.room_type(room_type_code),
    check_in_date date NOT NULL,
    check_out_date date NOT NULL,
    status text NOT NULL CHECK (status IN ('booked', 'checked_in', 'checked_out', 'cancelled')),
    total_amount numeric(14,2) NOT NULL CHECK (total_amount >= 0),
    created_at timestamptz NOT NULL,
    CHECK (check_out_date > check_in_date)
);

CREATE TABLE IF NOT EXISTS pms.schema_version (
    version text PRIMARY KEY,
    seed bigint NOT NULL,
    applied_at timestamptz NOT NULL
);
