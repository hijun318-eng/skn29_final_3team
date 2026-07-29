-- ============================================================================
-- Answervice 팀공유 SQL 산출물
-- ownership_contract=team-ownership-v2.1
-- schema_version=schema-v4.6-websql
-- snapshot_as_of_at=2026-07-28T05:00:00Z
-- generation_as_of_at=2026-07-28T05:00:00Z
-- evaluation_as_of=2026-07-28T14:00:00+09:00
-- GENERATE_FILES=true / RUN_STATIC_VALIDATION=true / EXECUTE_DB=false
-- 접속정보·healthy 컨테이너는 실행 승인으로 간주하지 않는다.
-- 실제 실행 전 해당 owner의 approval_id가 필요하다.
-- ============================================================================
-- owner=R4_김재홍
-- work_card=R4-APP-DB
-- read-only postflight. 실제 실행 결과를 R1 evidence bundle로 전달한다.
\set ON_ERROR_STOP on
\connect answervice_app

WITH expected(schema_name, table_name) AS (
  VALUES
  ('connection','data_sources'),('connection','ingestion_runs'),
  ('context','context_records'),('context','context_releases'),('context','context_packages'),
  ('chat','conversations'),('chat','analysis_requests'),
  ('query','query_executions'),('artifact','analysis_artifacts'),
  ('report','report_definitions'),('report','report_blocks'),('report','report_runs'),('report','block_runs'),
  ('governance','audit_events'),('model','model_versions'),('model','evaluation_runs'),
  ('reference','market_benchmark_annual'),('reference','demand_index_monthly'),('reference','calendar_daily')
), existing AS (
  SELECT table_schema, table_name
  FROM information_schema.tables
  WHERE table_type='BASE TABLE'
)
SELECT 'missing_p0_p1_table' AS check_name, count(*) AS violation_count
FROM expected e
LEFT JOIN existing x ON x.table_schema=e.schema_name AND x.table_name=e.table_name
WHERE x.table_name IS NULL
UNION ALL
SELECT 'unexpected_p2_table', count(*)
FROM information_schema.tables
WHERE table_type='BASE TABLE'
  AND table_schema IN ('tooling','rag','ml')
UNION ALL
SELECT 'foreign_key_without_index', count(*)
FROM (
  SELECT con.conrelid, unnest(con.conkey) AS attnum
  FROM pg_constraint con
  WHERE con.contype='f'
) fk
WHERE NOT EXISTS (
  SELECT 1 FROM pg_index i
  WHERE i.indrelid=fk.conrelid AND fk.attnum = ANY(i.indkey)
)
UNION ALL
SELECT 'alembic_head_not_single',
       CASE WHEN to_regclass('public.alembic_version') IS NULL THEN 1
            WHEN (SELECT count(*) FROM public.alembic_version) = 1 THEN 0 ELSE 1 END;

SELECT n.nspname AS schema_name, c.relname AS table_name,
       count(a.attname) FILTER (WHERE a.attnum>0 AND NOT a.attisdropped) AS column_count
FROM pg_class c
JOIN pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_attribute a ON a.attrelid=c.oid
WHERE c.relkind='r'
  AND n.nspname IN ('connection','context','chat','query','artifact','report','governance','model','reference')
GROUP BY n.nspname,c.relname
ORDER BY n.nspname,c.relname;
