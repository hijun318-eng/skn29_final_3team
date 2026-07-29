CREATE TABLE schema_version (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE seed_metadata (seed_name text PRIMARY KEY, seed_value integer NOT NULL, data_classification text NOT NULL);
CREATE TABLE pms_guests (guest_id text PRIMARY KEY, guest_name text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
INSERT INTO schema_version VALUES ('pms-postgres/v1', now());
INSERT INTO seed_metadata VALUES ('synthetic-demo', 20260729, 'synthetic');
INSERT INTO pms_guests VALUES ('PMS-0001', 'Synthetic Guest', now());
