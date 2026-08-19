-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=MySQL 8.4; target_database=walkerhill_v4_3
-- domain=POS; script_type=PREFLIGHT_READONLY; execution_order=00
-- dependencies=none; period=2024-01-01..2026-08-31; base_seed=20260814
-- expected_rows=0; execution_default=NOT_RUN; destructive_operation=false
-- next=10_mysql_pos_ddl.sql

SELECT DATABASE() database_name,CURRENT_USER() execution_user,@@version server_version,@@session.time_zone session_timezone;
SELECT 'candidate_database_collision' check_name,COUNT(*) violation_count,
       IF(COUNT(*)=0,'PASS','FAIL') status,'walkerhill_v4_3 must not exist before first creation' details
FROM information_schema.schemata WHERE schema_name='walkerhill_v4_3';
