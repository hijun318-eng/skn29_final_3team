-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=PostgreSQL 16; target_database=banquet_db; target_schema=walkerhill_v4_3
-- domain=BANQUET; script_type=PREFLIGHT_READONLY; execution_order=00
-- dependencies=none; period=2024-01-01..2026-08-31; base_seed=20260814
-- expected_rows=0; execution_default=NOT_RUN; destructive_operation=false
-- next=10_postgresql_banquet_ddl.sql

SELECT current_database() database_name,current_user execution_user,current_setting('server_version') server_version;
SELECT 'candidate_schema_collision' check_name,count(*) violation_count,
       CASE WHEN count(*)=0 THEN 'PASS' ELSE 'FAIL' END status,
       'walkerhill_v4_3 must not exist before first creation' details
FROM information_schema.schemata WHERE schema_name='walkerhill_v4_3';
