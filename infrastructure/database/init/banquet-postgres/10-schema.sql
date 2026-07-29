CREATE SCHEMA IF NOT EXISTS banquet;

CREATE TABLE IF NOT EXISTS banquet.venue (
    venue_id integer PRIMARY KEY,
    venue_name text NOT NULL,
    capacity integer NOT NULL CHECK (capacity > 0)
);

CREATE TABLE IF NOT EXISTS banquet.event (
    event_id bigint PRIMARY KEY,
    venue_id integer NOT NULL REFERENCES banquet.venue(venue_id),
    event_type text NOT NULL,
    event_date date NOT NULL,
    attendees integer NOT NULL CHECK (attendees >= 0),
    status text NOT NULL CHECK (status IN ('contracted', 'completed', 'cancelled')),
    contracted_amount numeric(14,2) NOT NULL CHECK (contracted_amount >= 0)
);

CREATE TABLE IF NOT EXISTS banquet.sales_line (
    sales_line_id bigint PRIMARY KEY,
    event_id bigint NOT NULL REFERENCES banquet.event(event_id),
    category text NOT NULL,
    net_amount numeric(14,2) NOT NULL CHECK (net_amount >= 0)
);

CREATE TABLE IF NOT EXISTS banquet.schema_version (
    version text PRIMARY KEY,
    seed bigint NOT NULL,
    applied_at timestamptz NOT NULL
);
