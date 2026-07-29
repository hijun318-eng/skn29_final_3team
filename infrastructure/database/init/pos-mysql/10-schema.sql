CREATE TABLE schema_version (version VARCHAR(64) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE seed_metadata (seed_name VARCHAR(64) PRIMARY KEY, seed_value INT NOT NULL, data_classification VARCHAR(32) NOT NULL);
CREATE TABLE pos_orders (order_id VARCHAR(32) PRIMARY KEY, store_name VARCHAR(128) NOT NULL, ordered_at DATETIME(3) NOT NULL);
INSERT INTO schema_version VALUES ('pos-mysql/v1', CURRENT_TIMESTAMP);
INSERT INTO seed_metadata VALUES ('synthetic-demo', 20260729, 'synthetic');
INSERT INTO pos_orders VALUES ('POS-0001', 'Synthetic Cafe', '2026-07-29 09:00:00.000');
