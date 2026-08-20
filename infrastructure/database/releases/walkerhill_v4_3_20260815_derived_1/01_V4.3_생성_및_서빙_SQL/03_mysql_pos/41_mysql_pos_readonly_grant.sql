-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=MySQL 8.4; domain=POS; script_type=SECURITY; execution_order=41
-- dependency=40_mysql_pos_constraints_indexes.sql; destructive_operation=false

GRANT SELECT ON walkerhill_v4_3.* TO 'pos_readonly';

