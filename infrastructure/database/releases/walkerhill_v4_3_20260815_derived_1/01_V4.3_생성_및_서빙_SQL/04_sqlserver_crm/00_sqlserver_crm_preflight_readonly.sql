USE [crm_db];
GO
-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- schema_version=4.3.0; generator_version=sql-v1.1.0
-- target_dbms=SQL Server 2022; target_database=crm_db; target_schema=walkerhill_v4_3
-- domain=CRM; script_type=PREFLIGHT_READONLY; execution_order=00
-- dependencies=none; period=2024-01-01..2026-08-31; base_seed=20260814
-- expected_rows=0; execution_default=NOT_RUN; destructive_operation=false
-- next=10_sqlserver_crm_ddl.sql

SELECT DB_NAME() database_name,SUSER_SNAME() execution_user,@@VERSION server_version;
SELECT N'candidate_schema_collision' check_name,COUNT_BIG(*) violation_count,
       CASE WHEN COUNT_BIG(*)=0 THEN N'PASS' ELSE N'FAIL' END status,
       N'walkerhill_v4_3 must not exist before first creation' details
FROM sys.schemas WHERE name=N'walkerhill_v4_3';
GO
