CREATE SCHEMA app;
CREATE TABLE app.application_health (id integer PRIMARY KEY, status text NOT NULL);
CREATE TABLE app.schema_version (version text PRIMARY KEY);
CREATE TABLE app.seed_metadata (seed integer PRIMARY KEY, classification text NOT NULL);
