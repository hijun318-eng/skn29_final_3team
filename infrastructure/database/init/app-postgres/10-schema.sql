CREATE TABLE IF NOT EXISTS schema_version (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS seed_metadata (seed_name text PRIMARY KEY, seed_value integer NOT NULL, data_classification text NOT NULL);
CREATE TABLE IF NOT EXISTS application_health (id integer PRIMARY KEY, status text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
INSERT INTO schema_version(version) VALUES ('app-postgres/v1') ON CONFLICT DO NOTHING;
INSERT INTO seed_metadata(seed_name, seed_value, data_classification) VALUES ('synthetic-demo', 20260729, 'synthetic') ON CONFLICT DO NOTHING;
INSERT INTO application_health(id, status) VALUES (1, 'ready') ON CONFLICT DO NOTHING;
