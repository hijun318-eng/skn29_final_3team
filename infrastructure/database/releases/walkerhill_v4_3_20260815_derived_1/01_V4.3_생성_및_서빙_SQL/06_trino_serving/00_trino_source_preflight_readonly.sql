-- release_id=walkerhill-v4.3-sql-20260815-derived.1
-- target_dbms=Trino 476+; domain=SERVING; script_type=PREFLIGHT_READONLY; execution_order=00
-- source_catalogs=pms,pos,crm,banquet,facility; target_catalog=serving
-- execution_default=NOT_RUN; destructive_operation=false

WITH visible AS (
 SELECT 'pms' source_catalog,COUNT(*) visible_tables,15 expected_tables FROM pms.information_schema.tables WHERE table_schema='walkerhill_v4_3'
 UNION ALL SELECT 'pos',COUNT(*),6 FROM pos.information_schema.tables WHERE table_schema='walkerhill_v4_3'
 UNION ALL SELECT 'crm',COUNT(*),7 FROM crm.information_schema.tables WHERE table_schema='walkerhill_v4_3'
 UNION ALL SELECT 'banquet',COUNT(*),5 FROM banquet.information_schema.tables WHERE table_schema='walkerhill_v4_3'
 UNION ALL SELECT 'facility',COUNT(*),5 FROM facility.information_schema.tables WHERE table_schema='walkerhill_v4_3'
)
SELECT source_catalog,visible_tables,expected_tables,
       CASE WHEN visible_tables=expected_tables THEN 'PASS' ELSE 'FAIL' END status
FROM visible ORDER BY source_catalog;

SELECT 'candidate_serving_schema_collision' check_name,COUNT(*) violation_count,
       CASE WHEN COUNT(*)=0 THEN 'PASS' ELSE 'FAIL' END status
FROM serving.information_schema.schemata WHERE schema_name='analytics_v4_3';
