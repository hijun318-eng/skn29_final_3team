CREATE TABLE IF NOT EXISTS environment_manifest (
    database_name varchar(128) NOT NULL,
    schema_version varchar(128) NOT NULL,
    synthetic_data_seed bigint unsigned NOT NULL,
    scenario_version varchar(128) NOT NULL,
    fixture_version varchar(128) NOT NULL,
    generated_at varchar(32) NOT NULL,
    is_synthetic boolean NOT NULL,
    PRIMARY KEY (database_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO environment_manifest VALUES (
    DATABASE(),
    @database_schema_version,
    CAST(@synthetic_data_seed AS UNSIGNED),
    @scenario_version,
    @fixture_version,
    @generated_at,
    true
) AS new
ON DUPLICATE KEY UPDATE
    schema_version = new.schema_version,
    synthetic_data_seed = new.synthetic_data_seed,
    scenario_version = new.scenario_version,
    fixture_version = new.fixture_version,
    generated_at = new.generated_at,
    is_synthetic = true;

GRANT SELECT ON hotel_pos.environment_manifest TO 'pos_query';
