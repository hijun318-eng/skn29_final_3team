CREATE TABLE pms_guests (guest_id text PRIMARY KEY, guest_name text NOT NULL);
CREATE TABLE schema_version (version text PRIMARY KEY);
CREATE TABLE seed_metadata (seed integer PRIMARY KEY, classification text NOT NULL);
