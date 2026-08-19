-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=pms_db; target_schema=walkerhill_v4_3
-- domain=PMS; script_type=PREFLIGHT_READONLY; execution_order=00
-- dependencies=none; period=2024-01-01..2026-08-31; base_seed=20260814
-- expected_rows=0; execution_default=NOT_RUN; destructive_operation=false
-- next=10_postgresql_pms_reference_ddl.sql

SELECT current_database() AS database_name,
       current_user AS execution_user,
       current_setting('server_version') AS server_version,
       current_setting('TimeZone') AS session_timezone;

SELECT 'candidate_schema_collision' AS check_name,
       count(*) AS violation_count,
       CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
       'walkerhill_v4_3 must not exist before first creation' AS details
FROM information_schema.schemata
WHERE schema_name = 'walkerhill_v4_3';

SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema IN ('public', 'walkerhill_v4', 'walkerhill_v4_3')
ORDER BY table_schema, table_name;
