CREATE TABLE schema_version (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE seed_metadata (seed_name text PRIMARY KEY, seed_value integer NOT NULL, data_classification text NOT NULL);
CREATE TABLE banquet_bookings (booking_id text PRIMARY KEY, event_name text NOT NULL, event_date date NOT NULL);
INSERT INTO schema_version VALUES ('banquet-postgres/v1', now());
INSERT INTO seed_metadata VALUES ('synthetic-demo', 20260729, 'synthetic');
INSERT INTO banquet_bookings VALUES ('BNQ-0001', 'Synthetic Banquet', DATE '2026-08-01');
