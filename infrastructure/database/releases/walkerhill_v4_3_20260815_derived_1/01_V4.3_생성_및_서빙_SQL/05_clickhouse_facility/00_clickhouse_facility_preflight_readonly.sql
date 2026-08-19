-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=ClickHouse 24.8+; target_database=walkerhill_v4_3
-- domain=FACILITY; script_type=PREFLIGHT_READONLY; execution_order=00
-- period=2024-01-01..2026-08-31; base_seed=20260814; execution_default=NOT_RUN

SELECT version() AS server_version,currentUser() AS execution_user;
SELECT 'candidate_database_collision' AS check_name,count() AS violation_count,
       if(count()=0,'PASS','FAIL') AS status
FROM system.databases WHERE name='walkerhill_v4_3';

