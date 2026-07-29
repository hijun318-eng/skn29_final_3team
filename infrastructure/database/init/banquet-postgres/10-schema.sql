CREATE TABLE banquet_bookings (booking_id text PRIMARY KEY, event_name text NOT NULL);
CREATE TABLE schema_version (version text PRIMARY KEY);
CREATE TABLE seed_metadata (seed integer PRIMARY KEY, classification text NOT NULL);
