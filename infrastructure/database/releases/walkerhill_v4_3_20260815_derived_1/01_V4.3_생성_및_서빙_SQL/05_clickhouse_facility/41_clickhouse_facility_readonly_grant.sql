-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=ClickHouse 24.8+; domain=FACILITY; script_type=SECURITY; execution_order=41
-- dependency=40_clickhouse_facility_indexes_settings.sql; destructive_operation=false

GRANT SELECT ON walkerhill_v4_3.* TO facility_readonly;

