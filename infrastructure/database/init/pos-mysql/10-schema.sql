CREATE TABLE pos_orders (order_id VARCHAR(32) PRIMARY KEY, store_name VARCHAR(128) NOT NULL);
CREATE TABLE schema_version (version VARCHAR(16) PRIMARY KEY);
CREATE TABLE seed_metadata (seed INT PRIMARY KEY, classification VARCHAR(32) NOT NULL);
